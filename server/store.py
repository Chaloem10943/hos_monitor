from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import Database
from .schemas import HeartbeatRequest, InventoryRequest


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def canonical_department(connection: sqlite3.Connection, department: str) -> str:
    name = department.strip()
    if not name:
        return ""
    current = connection.execute(
        "SELECT name FROM departments WHERE name=? COLLATE NOCASE", (name,)
    ).fetchone()
    if current is not None:
        return str(current["name"])
    alias = connection.execute(
        """SELECT d.name FROM department_aliases da
           JOIN departments d ON d.id=da.department_id
           WHERE da.alias=? COLLATE NOCASE""",
        (name,),
    ).fetchone()
    return str(alias["name"]) if alias is not None else name


HARDWARE_PLACEHOLDERS = {
    "to be filled by o.e.m.", "to be filled by oem", "default string",
    "system product name", "system manufacturer", "not specified", "unknown",
}


def clean_hardware_value(value: str) -> str:
    cleaned = value.strip()
    return "" if cleaned.casefold() in HARDWARE_PLACEHOLDERS else cleaned


def upsert_identity(connection: sqlite3.Connection, data: HeartbeatRequest, now: str) -> int:
    department = canonical_department(connection, data.department)
    connection.execute(
        """INSERT INTO assets
           (machine_id,hostname,asset_tag,department,agent_version,first_seen,last_seen,
            wallpaper_revision,wallpaper_status,wallpaper_error,
            agent_update_release_id,agent_update_status,agent_update_error)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(machine_id) DO UPDATE SET
             hostname=excluded.hostname,
             asset_tag=CASE WHEN assets.metadata_locked=1 THEN assets.asset_tag ELSE excluded.asset_tag END,
             department=CASE WHEN assets.metadata_locked=1 THEN assets.department ELSE excluded.department END,
             agent_version=excluded.agent_version,
             wallpaper_revision=CASE WHEN excluded.wallpaper_revision<>'' THEN excluded.wallpaper_revision ELSE assets.wallpaper_revision END,
             wallpaper_status=CASE WHEN excluded.wallpaper_status<>'' THEN excluded.wallpaper_status ELSE assets.wallpaper_status END,
             wallpaper_error=CASE WHEN excluded.wallpaper_status<>'' THEN excluded.wallpaper_error ELSE assets.wallpaper_error END,
             agent_update_release_id=COALESCE(excluded.agent_update_release_id,assets.agent_update_release_id),
             agent_update_status=CASE WHEN excluded.agent_update_status<>'' THEN excluded.agent_update_status ELSE assets.agent_update_status END,
             agent_update_error=CASE WHEN excluded.agent_update_status<>'' THEN excluded.agent_update_error ELSE assets.agent_update_error END,
             last_seen=excluded.last_seen""",
        (
            data.machine_id, data.hostname, data.asset_tag, department, data.agent_version, now, now,
            data.wallpaper_revision, data.wallpaper_status, data.wallpaper_error,
            data.agent_update_release_id, data.agent_update_status, data.agent_update_error,
        ),
    )
    return int(connection.execute("SELECT id FROM assets WHERE machine_id=?", (data.machine_id,)).fetchone()[0])


def effective_policy(connection: sqlite3.Connection, department: str) -> dict[str, Any]:
    row = None
    if department:
        row = connection.execute(
            "SELECT * FROM policies WHERE scope_type='department' AND scope_value=?", (department,)
        ).fetchone()
    if row is None:
        row = connection.execute("SELECT * FROM policies WHERE scope_type='global' AND scope_value='' ").fetchone()
    result = dict(row)
    result["daily_enabled"] = bool(result["daily_enabled"])
    return result


def pending_campaigns(connection: sqlite3.Connection, asset_id: int, department: str, now: str) -> list[int]:
    rows = connection.execute(
        """SELECT id FROM campaigns
           WHERE expires_at > ? AND (
             target_type='all' OR
             (target_type='department' AND target_value=?) OR
             (target_type='asset' AND target_value=?)
           ) ORDER BY id""",
        (now, department, str(asset_id)),
    ).fetchall()
    result: list[int] = []
    for row in rows:
        campaign_id = int(row["id"])
        connection.execute(
            "INSERT OR IGNORE INTO campaign_receipts(campaign_id,asset_id) VALUES (?,?)",
            (campaign_id, asset_id),
        )
        receipt = connection.execute(
            "SELECT completed_at FROM campaign_receipts WHERE campaign_id=? AND asset_id=?",
            (campaign_id, asset_id),
        ).fetchone()
        if receipt["completed_at"] is None:
            connection.execute(
                "UPDATE campaign_receipts SET delivered_at=COALESCE(delivered_at,?) WHERE campaign_id=? AND asset_id=?",
                (now, campaign_id, asset_id),
            )
            result.append(campaign_id)
    return result


def save_inventory(database: Database, data: InventoryRequest) -> int:
    now = iso()
    with database.transaction() as connection:
        asset_id = upsert_identity(connection, data, now)
        connection.execute(
            """UPDATE assets SET os_name=?,os_version=?,cpu_name=?,cpu_cores=?,
               ram_total_bytes=?,ram_used_bytes=?,primary_ipv4=?,manufacturer=?,model=?,
               bios_serial=?,system_uuid=?,baseboard_manufacturer=?,baseboard_product=?,
               baseboard_serial=?,last_inventory_at=? WHERE id=?""",
            (
                data.os_name, data.os_version, data.cpu_name, data.cpu_cores,
                data.ram_total_bytes, data.ram_used_bytes, data.primary_ipv4,
                clean_hardware_value(data.manufacturer), clean_hardware_value(data.model),
                clean_hardware_value(data.bios_serial), clean_hardware_value(data.system_uuid),
                clean_hardware_value(data.baseboard_manufacturer),
                clean_hardware_value(data.baseboard_product),
                clean_hardware_value(data.baseboard_serial), data.collected_at, asset_id,
            ),
        )
        connection.execute("DELETE FROM asset_disks WHERE asset_id=?", (asset_id,))
        connection.executemany(
            "INSERT INTO asset_disks(asset_id,device_id,label,total_bytes,free_bytes) VALUES (?,?,?,?,?)",
            [(asset_id, d.device_id, d.label, d.total_bytes, d.free_bytes) for d in data.disks],
        )
        connection.execute("DELETE FROM asset_network WHERE asset_id=?", (asset_id,))
        connection.executemany(
            "INSERT INTO asset_network(asset_id,adapter_name,mac_address,ipv4,is_primary) VALUES (?,?,?,?,?)",
            [(asset_id, n.adapter_name, n.mac_address, n.ipv4, int(n.is_primary)) for n in data.network],
        )
        connection.execute("DELETE FROM asset_software WHERE asset_id=?", (asset_id,))
        software_rows = {
            (s.name.strip(), s.version.strip(), s.publisher.strip(), s.install_date.strip())
            for s in data.software if s.name.strip()
        }
        connection.executemany(
            "INSERT INTO asset_software(asset_id,name,version,publisher,install_date) VALUES (?,?,?,?,?)",
            [(asset_id, *values) for values in sorted(software_rows)],
        )
        connection.execute(
            """INSERT INTO monitor_observations
               (asset_id,monitor_type,observed_at,status,severity,payload_json)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(asset_id,monitor_type) DO UPDATE SET
                 observed_at=excluded.observed_at,status=excluded.status,
                 severity=excluded.severity,payload_json=excluded.payload_json""",
            (asset_id, "inventory", data.collected_at, "current", "info", "{}"),
        )
        known_types = {
            row["name"]: int(row["schema_version"])
            for row in connection.execute("SELECT name,schema_version FROM monitor_types WHERE enabled=1")
        }
        for observation in data.observations:
            if known_types.get(observation.monitor_type) != observation.schema_version:
                continue
            connection.execute(
                """INSERT INTO monitor_observations
                   (asset_id,monitor_type,observed_at,status,severity,payload_json)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(asset_id,monitor_type) DO UPDATE SET
                     observed_at=excluded.observed_at,status=excluded.status,
                     severity=excluded.severity,payload_json=excluded.payload_json""",
                (asset_id, observation.monitor_type, observation.observed_at,
                 observation.status, observation.severity,
                 json.dumps(observation.payload, ensure_ascii=False, separators=(",", ":"))),
            )
        for campaign_id in set(data.completed_campaign_ids):
            connection.execute(
                """UPDATE campaign_receipts SET completed_at=?
                   WHERE campaign_id=? AND asset_id=?""",
                (now, campaign_id, asset_id),
            )
        return asset_id


def list_assets(
    connection: sqlite3.Connection,
    *, search: str = "", department: str = "", os_name: str = "",
    online: bool | None = None, retired: bool = False,
    page: int = 1, page_size: int = 50,
) -> dict[str, Any]:
    now = iso()
    clauses = ["a.retired_at IS NOT NULL" if retired else "a.retired_at IS NULL"]
    where_values: list[Any] = []
    if search:
        pattern = f"%{search}%"
        clauses.append("(a.hostname LIKE ? OR a.display_name LIKE ? OR a.asset_tag LIKE ? OR a.machine_id LIKE ?)")
        where_values.extend([pattern, pattern, pattern, pattern])
    if department:
        clauses.append("a.department=?")
        where_values.append(department)
    if os_name:
        clauses.append("a.os_name LIKE ?")
        where_values.append(f"%{os_name}%")
    online_expr = """((julianday(?) - julianday(a.last_seen)) * 86400 <= COALESCE(
      (SELECT p.online_threshold_seconds FROM policies p WHERE p.scope_type='department' AND p.scope_value=a.department),
      (SELECT p.online_threshold_seconds FROM policies p WHERE p.scope_type='global' AND p.scope_value=''), 300))"""
    if online is not None:
        clauses.append(online_expr + "=?")
        where_values.extend([now, int(online)])
    where = " AND ".join(clauses)
    count_sql = f"SELECT COUNT(*) FROM assets a WHERE {where}"
    total = int(connection.execute(count_sql, where_values).fetchone()[0])
    query = f"""SELECT a.*, {online_expr} AS online,
      CASE WHEN a.ram_total_bytes>0 THEN ROUND(a.ram_used_bytes*100.0/a.ram_total_bytes,1) ELSE 0 END AS ram_used_percent,
      (SELECT MIN(CASE WHEN total_bytes>0 THEN free_bytes*100.0/total_bytes ELSE 100 END)
       FROM asset_disks d WHERE d.asset_id=a.id) AS min_disk_free_percent
      FROM assets a WHERE {where} ORDER BY online DESC,COALESCE(NULLIF(a.display_name,''),a.hostname) LIMIT ? OFFSET ?"""
    # online_expr is present twice in the SELECT/WHERE only when the filter is set.
    query_values: list[Any] = [now]
    query_values.extend(where_values)
    query_values.extend([page_size, (page - 1) * page_size])
    rows = [dict(row) for row in connection.execute(query, query_values).fetchall()]
    for row in rows:
        row["online"] = bool(row["online"])
        row["metadata_locked"] = bool(row["metadata_locked"])
        row["retired"] = row["retired_at"] is not None
    return {"items": rows, "page": page, "page_size": page_size, "total": total}


def asset_detail(connection: sqlite3.Connection, asset_id: int) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["metadata_locked"] = bool(result["metadata_locked"])
    result["retired"] = result["retired_at"] is not None
    policy = effective_policy(connection, result["department"])
    try:
        seen = datetime.fromisoformat(result["last_seen"].replace("Z", "+00:00"))
        result["online"] = (utc_now() - seen).total_seconds() <= int(policy["online_threshold_seconds"])
    except (TypeError, ValueError):
        result["online"] = False
    result["disks"] = [dict(item) for item in connection.execute(
        "SELECT device_id,label,total_bytes,free_bytes FROM asset_disks WHERE asset_id=? ORDER BY device_id", (asset_id,)
    )]
    result["network"] = [dict(item) for item in connection.execute(
        "SELECT adapter_name,mac_address,ipv4,is_primary FROM asset_network WHERE asset_id=? ORDER BY is_primary DESC,adapter_name", (asset_id,)
    )]
    result["software"] = [dict(item) for item in connection.execute(
        "SELECT name,version,publisher,install_date FROM asset_software WHERE asset_id=? ORDER BY name COLLATE NOCASE", (asset_id,)
    )]
    observations = []
    for item in connection.execute(
        "SELECT monitor_type,observed_at,status,severity,payload_json FROM monitor_observations WHERE asset_id=?", (asset_id,)
    ):
        value = dict(item)
        value["payload"] = json.loads(value.pop("payload_json"))
        observations.append(value)
    result["observations"] = observations
    return result
