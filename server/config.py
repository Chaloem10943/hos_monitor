from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    data_dir: Path
    database_path: Path
    host: str
    port: int
    agent_token: str
    session_hours: int
    online_threshold_seconds: int
    cookie_secure: bool
    update_enabled: bool
    update_backup_retention: int
    update_public_key_path: Path
    server_service_name: str


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_dir() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else Path(__file__).resolve().parents[1]


def default_config() -> dict[str, Any]:
    return {
        "server": {"host": "0.0.0.0", "port": 6001, "cookie_secure": False},
        "storage": {"data_dir": "data", "database": "hos_monitor.db"},
        "security": {"agent_token": secrets.token_urlsafe(32), "session_hours": 8},
        "monitoring": {"online_threshold_seconds": 300},
        "updates": {
            "enabled": False,
            "backup_retention": 5,
            "public_key": "update_public.pem",
            "server_service_name": "HosMonitorServer",
        },
    }


def _write_initial_config(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# HosMonitor - on-premise configuration\n"
        "# Keep this file readable only by server administrators.\n"
        + yaml.safe_dump(values, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    configured = path or os.environ.get("HOS_MONITOR_CONFIG")
    config_path = Path(configured).resolve() if configured else application_dir() / "config.yaml"
    if not config_path.exists():
        _write_initial_config(config_path, default_config())
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    server = raw.get("server", {})
    storage = raw.get("storage", {})
    security = raw.get("security", {})
    monitoring = raw.get("monitoring", {})
    updates = raw.get("updates", {})
    raw_data_dir = Path(str(storage.get("data_dir", "data")))
    data_dir = raw_data_dir if raw_data_dir.is_absolute() else config_path.parent / raw_data_dir
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    raw_database = Path(str(storage.get("database", "hos_monitor.db")))
    database_path = raw_database if raw_database.is_absolute() else data_dir / raw_database
    token = str(security.get("agent_token", "")).strip()
    if len(token) < 24:
        raise ValueError("security.agent_token must contain at least 24 characters")
    raw_public_key = Path(str(updates.get("public_key", "update_public.pem")))
    public_key_path = raw_public_key if raw_public_key.is_absolute() else config_path.parent / raw_public_key
    return AppConfig(
        config_path=config_path,
        data_dir=data_dir,
        database_path=database_path.resolve(),
        host=str(server.get("host", "0.0.0.0")),
        port=int(server.get("port", 6001)),
        agent_token=token,
        session_hours=max(1, int(security.get("session_hours", 8))),
        online_threshold_seconds=max(60, int(monitoring.get("online_threshold_seconds", 300))),
        cookie_secure=bool(server.get("cookie_secure", False)),
        update_enabled=bool(updates.get("enabled", False)),
        update_backup_retention=max(1, min(20, int(updates.get("backup_retention", 5)))),
        update_public_key_path=public_key_path.resolve(),
        server_service_name=str(updates.get("server_service_name", "HosMonitorServer")).strip() or "HosMonitorServer",
    )


def save_update_config(config: AppConfig, *, enabled: bool, backup_retention: int) -> AppConfig:
    raw = yaml.safe_load(config.config_path.read_text(encoding="utf-8")) or {}
    current = raw.get("updates", {})
    raw["updates"] = {
        "enabled": bool(enabled),
        "backup_retention": max(1, min(20, int(backup_retention))),
        "public_key": str(current.get("public_key", "update_public.pem")),
        "server_service_name": str(current.get("server_service_name", "HosMonitorServer")),
    }
    temporary = config.config_path.with_suffix(config.config_path.suffix + ".tmp")
    temporary.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(temporary, config.config_path)
    return load_config(config.config_path)
