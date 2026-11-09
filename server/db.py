from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .migrations import apply_migrations


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','viewer')),
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  key_prefix TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  scope TEXT NOT NULL DEFAULT 'assets:read',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  machine_id TEXT NOT NULL UNIQUE,
  hostname TEXT NOT NULL,
  asset_tag TEXT NOT NULL DEFAULT '',
  department TEXT NOT NULL DEFAULT '',
  metadata_locked INTEGER NOT NULL DEFAULT 0,
  os_name TEXT NOT NULL DEFAULT '',
  os_version TEXT NOT NULL DEFAULT '',
  cpu_name TEXT NOT NULL DEFAULT '',
  cpu_cores INTEGER NOT NULL DEFAULT 0,
  ram_total_bytes INTEGER NOT NULL DEFAULT 0,
  ram_used_bytes INTEGER NOT NULL DEFAULT 0,
  primary_ipv4 TEXT NOT NULL DEFAULT '',
  agent_version TEXT NOT NULL DEFAULT '',
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  last_inventory_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_assets_hostname ON assets(hostname);
CREATE INDEX IF NOT EXISTS idx_assets_department ON assets(department);
CREATE INDEX IF NOT EXISTS idx_assets_last_seen ON assets(last_seen);
CREATE TABLE IF NOT EXISTS asset_disks (
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  device_id TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  total_bytes INTEGER NOT NULL DEFAULT 0,
  free_bytes INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(asset_id, device_id)
);
CREATE TABLE IF NOT EXISTS asset_network (
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  adapter_name TEXT NOT NULL,
  mac_address TEXT NOT NULL DEFAULT '',
  ipv4 TEXT NOT NULL,
  is_primary INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(asset_id, adapter_name, ipv4)
);
CREATE TABLE IF NOT EXISTS asset_software (
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '',
  publisher TEXT NOT NULL DEFAULT '',
  install_date TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(asset_id, name, version, publisher)
);
CREATE INDEX IF NOT EXISTS idx_software_name ON asset_software(name);
CREATE TABLE IF NOT EXISTS policies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope_type TEXT NOT NULL CHECK(scope_type IN ('global','department')),
  scope_value TEXT NOT NULL DEFAULT '',
  heartbeat_seconds INTEGER NOT NULL DEFAULT 120,
  online_threshold_seconds INTEGER NOT NULL DEFAULT 300,
  boot_delay_seconds INTEGER NOT NULL DEFAULT 600,
  daily_enabled INTEGER NOT NULL DEFAULT 0,
  daily_time TEXT NOT NULL DEFAULT '02:00',
  updated_at TEXT NOT NULL,
  UNIQUE(scope_type, scope_value)
);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_type TEXT NOT NULL CHECK(target_type IN ('all','department','asset')),
  target_value TEXT NOT NULL DEFAULT '',
  created_by INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_receipts (
  campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  delivered_at TEXT,
  completed_at TEXT,
  PRIMARY KEY(campaign_id, asset_id)
);
CREATE TABLE IF NOT EXISTS monitor_types (
  name TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS monitor_observations (
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  monitor_type TEXT NOT NULL REFERENCES monitor_types(name),
  observed_at TEXT NOT NULL,
  status TEXT NOT NULL,
  severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
  payload_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(asset_id, monitor_type)
);
CREATE TABLE IF NOT EXISTS schema_migrations (
  migration_id TEXT PRIMARY KEY,
  version TEXT NOT NULL,
  checksum TEXT NOT NULL,
  applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS system_updates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_version TEXT NOT NULL,
  to_version TEXT NOT NULL,
  release_tag TEXT NOT NULL,
  package_checksum TEXT,
  action TEXT NOT NULL CHECK(action IN ('update','rollback')),
  status TEXT NOT NULL CHECK(status IN ('pending','installing','completed','failed')),
  started_by TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL,
  completed_at TEXT,
  backup_path TEXT,
  error_message TEXT,
  details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_system_updates_started_at ON system_updates(started_at);
CREATE INDEX IF NOT EXISTS idx_system_updates_status ON system_updates(status);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def initialize(self, now: str) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            apply_migrations(connection)
            connection.execute(
                """INSERT OR IGNORE INTO policies
                   (scope_type, scope_value, heartbeat_seconds, online_threshold_seconds,
                    boot_delay_seconds, daily_enabled, daily_time, updated_at)
                   VALUES ('global','',120,300,600,0,'02:00',?)""",
                (now,),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO monitor_types(name,display_name,schema_version,enabled) VALUES (?,?,1,1)",
                [("heartbeat", "Agent heartbeat"), ("inventory", "IT asset inventory")],
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
