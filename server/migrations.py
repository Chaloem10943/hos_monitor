from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Migration:
    migration_id: str
    version: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


# Append new, forward-only migrations to this tuple. Never edit a migration after
# it has shipped; the checksum guard deliberately stops startup if that happens.
MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        migration_id="0001_update_history_indexes",
        version="0.1.0",
        sql="""
        CREATE INDEX IF NOT EXISTS idx_system_updates_started_at
          ON system_updates(started_at);
        CREATE INDEX IF NOT EXISTS idx_system_updates_status
          ON system_updates(status);
        """,
    ),
    Migration(
        migration_id="0002_agent_admin_and_wallpaper",
        version="0.2.0",
        sql="""
        ALTER TABLE assets ADD COLUMN display_name TEXT NOT NULL DEFAULT '';
        ALTER TABLE assets ADD COLUMN wallpaper_revision TEXT NOT NULL DEFAULT '';
        ALTER TABLE assets ADD COLUMN wallpaper_status TEXT NOT NULL DEFAULT '';
        ALTER TABLE assets ADD COLUMN wallpaper_error TEXT NOT NULL DEFAULT '';

        CREATE TABLE IF NOT EXISTS departments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE COLLATE NOCASE,
          enabled INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO departments(name,enabled,created_at)
          SELECT DISTINCT department,1,CURRENT_TIMESTAMP FROM assets WHERE department<>'';

        CREATE TABLE IF NOT EXISTS wallpaper_settings (
          id INTEGER PRIMARY KEY CHECK(id=1),
          enabled INTEGER NOT NULL DEFAULT 0,
          revision TEXT NOT NULL DEFAULT '',
          filename TEXT NOT NULL DEFAULT '',
          mime_type TEXT NOT NULL DEFAULT '',
          sha256 TEXT NOT NULL DEFAULT '',
          size_bytes INTEGER NOT NULL DEFAULT 0,
          style TEXT NOT NULL DEFAULT 'fill',
          locked INTEGER NOT NULL DEFAULT 1,
          updated_by INTEGER REFERENCES users(id),
          updated_at TEXT
        );
        INSERT OR IGNORE INTO wallpaper_settings(id) VALUES (1);
        """,
    ),
    Migration(
        migration_id="0003_signed_agent_rollouts",
        version="1.0.0",
        sql="""
        ALTER TABLE assets ADD COLUMN agent_update_release_id INTEGER;
        ALTER TABLE assets ADD COLUMN agent_update_status TEXT NOT NULL DEFAULT '';
        ALTER TABLE assets ADD COLUMN agent_update_error TEXT NOT NULL DEFAULT '';

        CREATE TABLE agent_releases (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          version TEXT NOT NULL UNIQUE,
          filename TEXT NOT NULL,
          sha256 TEXT NOT NULL UNIQUE,
          size_bytes INTEGER NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          uploaded_by INTEGER NOT NULL REFERENCES users(id),
          uploaded_at TEXT NOT NULL
        );
        CREATE TABLE agent_rollouts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          release_id INTEGER NOT NULL REFERENCES agent_releases(id),
          target_type TEXT NOT NULL CHECK(target_type IN ('all','department','asset')),
          target_value TEXT NOT NULL DEFAULT '',
          created_by INTEGER NOT NULL REFERENCES users(id),
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL
        );
        CREATE TABLE agent_rollout_receipts (
          rollout_id INTEGER NOT NULL REFERENCES agent_rollouts(id) ON DELETE CASCADE,
          asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
          delivered_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          error_message TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL,
          PRIMARY KEY(rollout_id,asset_id)
        );
        CREATE INDEX idx_agent_rollouts_created_at ON agent_rollouts(created_at);
        CREATE INDEX idx_agent_receipts_status ON agent_rollout_receipts(status);
        """,
    ),
    Migration(
        migration_id="0004_asset_lifecycle",
        version="1.0.7",
        sql="""
        ALTER TABLE assets ADD COLUMN retired_at TEXT;
        ALTER TABLE assets ADD COLUMN retired_by INTEGER REFERENCES users(id);
        ALTER TABLE assets ADD COLUMN retired_reason TEXT NOT NULL DEFAULT '';
        CREATE INDEX idx_assets_retired_at ON assets(retired_at);
        """,
    ),
    Migration(
        migration_id="0005_department_aliases",
        version="1.0.8",
        sql="""
        CREATE TABLE department_aliases (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
          alias TEXT NOT NULL UNIQUE COLLATE NOCASE,
          created_at TEXT NOT NULL
        );
        CREATE INDEX idx_department_aliases_department_id
          ON department_aliases(department_id);
        """,
    ),
    Migration(
        migration_id="0006_hardware_identity",
        version="1.0.8",
        sql="""
        ALTER TABLE assets ADD COLUMN manufacturer TEXT NOT NULL DEFAULT '';
        ALTER TABLE assets ADD COLUMN model TEXT NOT NULL DEFAULT '';
        ALTER TABLE assets ADD COLUMN bios_serial TEXT NOT NULL DEFAULT '';
        ALTER TABLE assets ADD COLUMN system_uuid TEXT NOT NULL DEFAULT '';
        ALTER TABLE assets ADD COLUMN baseboard_manufacturer TEXT NOT NULL DEFAULT '';
        ALTER TABLE assets ADD COLUMN baseboard_product TEXT NOT NULL DEFAULT '';
        ALTER TABLE assets ADD COLUMN baseboard_serial TEXT NOT NULL DEFAULT '';
        """,
    ),
    Migration(
        migration_id="0007_wallpaper_exclusions",
        version="1.0.8",
        sql="""
        CREATE TABLE wallpaper_exclusions (
          asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
          reason TEXT NOT NULL DEFAULT '',
          created_by INTEGER NOT NULL REFERENCES users(id),
          created_at TEXT NOT NULL
        );
        CREATE INDEX idx_wallpaper_exclusions_created_at
          ON wallpaper_exclusions(created_at);
        """,
    ),
)


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
             migration_id TEXT PRIMARY KEY,
             version TEXT NOT NULL,
             checksum TEXT NOT NULL,
             applied_at TEXT NOT NULL
           )"""
    )
    for migration in MIGRATIONS:
        existing = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE migration_id=?",
            (migration.migration_id,),
        ).fetchone()
        if existing:
            if str(existing["checksum"]) != migration.checksum:
                raise RuntimeError(
                    f"database migration checksum changed: {migration.migration_id}"
                )
            continue
        applied_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        values = [
            value.replace("'", "''")
            for value in (migration.migration_id, migration.version, migration.checksum, applied_at)
        ]
        script = (
            "BEGIN IMMEDIATE;\n"
            + migration.sql
            + "\nINSERT INTO schema_migrations(migration_id,version,checksum,applied_at) "
            + f"VALUES ('{values[0]}','{values[1]}','{values[2]}','{values[3]}');\nCOMMIT;"
        )
        try:
            connection.executescript(script)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
