from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from server.config import load_config, save_update_config
from server.db import Database
from server.migrations import MIGRATIONS
from server.updater import UpdateError, stage_release_bundle, verify_manifest
import updater_runner


def update_config(tmp_path: Path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_path = tmp_path / "update_public.pem"
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({
        "server": {"host": "127.0.0.1", "port": 7180},
        "storage": {"data_dir": str(tmp_path / "data"), "database": "test.db"},
        "security": {"agent_token": "test-agent-token-1234567890", "session_hours": 8},
        "monitoring": {"online_threshold_seconds": 300},
        "updates": {"enabled": True, "public_key": str(public_path)},
    }), encoding="utf-8")
    return load_config(config_path), private_key


def signed_manifest(private_key, *, file_name: str = "HosMonitorServer.exe") -> tuple[bytes, bytes]:
    manifest = {
        "schema": 1,
        "version": "0.2.0",
        "minimum_version": "0.1.0",
        "package": "HosMonitorServer-update-0.2.0.zip",
        "package_sha256": "a" * 64,
        "files": [
            {"path": file_name, "size": 10, "sha256": "b" * 64},
            {"path": "VERSION", "size": 6, "sha256": "c" * 64},
        ],
    }
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    signature = private_key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
    return raw, signature


def test_signed_update_manifest_accepts_only_allowlisted_files(tmp_path: Path):
    config, private_key = update_config(tmp_path)
    raw, signature = signed_manifest(private_key)
    assert verify_manifest(raw, signature, config)["version"] == "0.2.0"

    tampered = raw.replace(b'"version": "0.2.0"', b'"version": "9.9.9"')
    with pytest.raises(UpdateError, match="signature"):
        verify_manifest(tampered, signature, config)

    unsafe_raw, unsafe_signature = signed_manifest(private_key, file_name="../HosMonitorServer.exe")
    with pytest.raises(UpdateError, match="unsafe"):
        verify_manifest(unsafe_raw, unsafe_signature, config)


def test_update_config_preserves_trust_settings(tmp_path: Path):
    config, _ = update_config(tmp_path)
    public_key = config.update_public_key_path
    updated = save_update_config(config, enabled=True, backup_retention=7)
    assert updated.update_backup_retention == 7
    assert updated.update_public_key_path == public_key
    assert updated.server_service_name == "HosMonitorServer"


def test_database_records_immutable_migrations(tmp_path: Path):
    database = Database(tmp_path / "migrations.db")
    database.initialize("2026-10-01T00:00:00Z")
    database.initialize("2026-10-01T00:01:00Z")
    with database.connect() as connection:
        rows = connection.execute("SELECT migration_id,checksum FROM schema_migrations").fetchall()
    assert len(rows) == len(MIGRATIONS)
    assert rows[0]["checksum"] == hashlib.sha256(MIGRATIONS[0].sql.encode("utf-8")).hexdigest()


def test_update_config_endpoint_requires_admin_password(client: TestClient, admin: dict):
    payload = {
        "enabled": True, "backup_retention": 5,
        "admin_password": "wrong-password",
    }
    denied = client.put("/api/ui/updates/config", json=payload, headers={"X-CSRF-Token": admin["csrf_token"]})
    assert denied.status_code == 403
    payload["admin_password"] = "correct-horse-123"
    saved = client.put("/api/ui/updates/config", json=payload, headers={"X-CSRF-Token": admin["csrf_token"]})
    assert saved.status_code == 200
    visible = client.get("/api/ui/updates/config").json()
    assert visible["enabled"] is True
    assert "token" not in visible


def test_update_import_allows_release_larger_than_default_request_limit(client: TestClient, admin: dict):
    response = client.post(
        "/api/ui/updates/import",
        content=b"x" * (16 * 1024 * 1024 + 1),
        headers={
            "X-CSRF-Token": admin["csrf_token"],
            "X-Admin-Password": "correct-horse-123",
            "X-Update-Confirmation": "UPDATE",
            "Content-Type": "application/octet-stream",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] != "request too large"


def test_offline_bundle_is_verified_and_staged(tmp_path: Path):
    config, private_key = update_config(tmp_path)
    executable = b"test-server-executable"
    version_file = b"1.0.10\n"
    package_buffer = io.BytesIO()
    with zipfile.ZipFile(package_buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("HosMonitorServer.exe", executable)
        package.writestr("VERSION", version_file)
    package_bytes = package_buffer.getvalue()
    manifest = {
        "schema": 1, "version": "1.0.10", "minimum_version": "0.1.0",
        "package": "HosMonitorServer-update-1.0.10.zip",
        "package_sha256": hashlib.sha256(package_bytes).hexdigest(),
        "files": [
            {"path": "HosMonitorServer.exe", "size": len(executable), "sha256": hashlib.sha256(executable).hexdigest()},
            {"path": "VERSION", "size": len(version_file), "sha256": hashlib.sha256(version_file).hexdigest()},
        ],
    }
    manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
    signature = private_key.sign(manifest_raw, padding.PKCS1v15(), hashes.SHA256())
    bundle_buffer = io.BytesIO()
    with zipfile.ZipFile(bundle_buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", manifest_raw)
        bundle.writestr("manifest.sig", signature)
        bundle.writestr(manifest["package"], package_bytes)
    result = stage_release_bundle(config, bundle_buffer.getvalue(), "admin")
    assert result["status"] == "pending"
    pending = json.loads((config.data_dir / "updates" / "pending.json").read_text(encoding="utf-8"))
    assert pending["to_version"] == "1.0.10"
    assert Path(pending["staged_executable"]).read_bytes() == executable


def test_rollback_uses_selected_backup_not_new_safety_backup(tmp_path: Path, monkeypatch):
    config, _ = update_config(tmp_path)
    Database(config.database_path).initialize("2026-10-01T00:00:00Z")
    install = tmp_path / "install"
    install.mkdir()
    (install / "HosMonitorServer.exe").write_bytes(b"current")
    (install / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    selected = config.data_dir / "updates" / "backups" / "selected-old"
    selected.mkdir(parents=True)
    (selected / "HosMonitorServer.exe").write_bytes(b"old")
    (selected / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (selected / "backup.json").write_text(
        json.dumps({"version": "0.1.0", "database": config.database_path.name}),
        encoding="utf-8",
    )
    monkeypatch.setattr(updater_runner, "application_dir", lambda: install)
    monkeypatch.setattr(updater_runner, "service_command", lambda *_: None)
    monkeypatch.setattr(updater_runner, "wait_service", lambda *_: None)
    monkeypatch.setattr(updater_runner, "health_check", lambda *_: None)
    updater_runner.apply_request(config, {
        "schema": 1, "action": "rollback", "requested_by": "admin",
        "requested_at": "2026-10-01T00:00:00Z", "from_version": "0.2.0",
        "to_version": "0.1.0", "release_tag": "rollback",
        "package_checksum": "", "backup_path": str(selected),
    })
    assert (install / "HosMonitorServer.exe").read_bytes() == b"old"
    assert (install / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0"
    state = json.loads((config.data_dir / "updates" / "state.json").read_text(encoding="utf-8"))
    assert state["backup_path"] == str(selected)
    assert Path(state["safety_backup_path"]).is_dir()
