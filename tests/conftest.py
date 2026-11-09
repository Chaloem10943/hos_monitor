from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient


_import_root = Path(tempfile.mkdtemp(prefix="hosmonitor-import-"))
_import_config = _import_root / "config.yaml"
_import_config.write_text(yaml.safe_dump({
    "server": {"host": "127.0.0.1", "port": 7180, "cookie_secure": False},
    "storage": {"data_dir": str(_import_root / "data"), "database": "import.db"},
    "security": {"agent_token": "import-test-agent-token-1234567890", "session_hours": 8},
    "monitoring": {"online_threshold_seconds": 300},
}), encoding="utf-8")
os.environ["HOS_MONITOR_CONFIG"] = str(_import_config)

from server.app import create_app  # noqa: E402


@pytest.fixture()
def agent_token() -> str:
    return "test-agent-token-12345678901234567890"


@pytest.fixture()
def client(tmp_path: Path, agent_token: str):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "server": {"host": "127.0.0.1", "port": 7180, "cookie_secure": False},
        "storage": {"data_dir": str(tmp_path / "data"), "database": "test.db"},
        "security": {"agent_token": agent_token, "session_hours": 8},
        "monitoring": {"online_threshold_seconds": 300},
    }), encoding="utf-8")
    app = create_app(config_path)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        yield test_client


@pytest.fixture()
def admin(client: TestClient) -> dict:
    response = client.post("/api/ui/setup", json={"username": "admin", "password": "correct-horse-123"})
    assert response.status_code == 201, response.text
    result = response.json()
    headers = {"X-CSRF-Token": result["csrf_token"]}
    for name in ("OPD", "LAB"):
        created = client.post("/api/ui/departments", json={"name": name}, headers=headers)
        assert created.status_code == 201, created.text
    return result


@pytest.fixture()
def heartbeat_payload() -> dict:
    return {
        "machine_id": "machine-fixture-001",
        "hostname": "OPD-PC-01",
        "asset_tag": "MCH-0001",
        "department": "OPD",
        "agent_version": "0.1.0",
    }


@pytest.fixture()
def inventory_payload(heartbeat_payload: dict) -> dict:
    return {
        **heartbeat_payload,
        "collected_at": "2026-10-01T03:00:00Z",
        "os_name": "Microsoft Windows 11 Pro",
        "os_version": "10.0.26100",
        "cpu_name": "Test CPU",
        "cpu_cores": 8,
        "ram_total_bytes": 17179869184,
        "ram_used_bytes": 8589934592,
        "primary_ipv4": "192.168.10.21",
        "disks": [{"device_id": "C:", "label": "Windows", "total_bytes": 1000, "free_bytes": 100}],
        "network": [{"adapter_name": "Ethernet", "mac_address": "00-11-22-33-44-55", "ipv4": "192.168.10.21", "is_primary": True}],
        "software": [
            {"name": "Hospital App", "version": "1.0", "publisher": "MCH", "install_date": "20261001"},
            {"name": "Browser", "version": "2.0", "publisher": "Vendor", "install_date": ""},
        ],
        "completed_campaign_ids": [],
        "observations": [],
    }
