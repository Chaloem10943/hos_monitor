from __future__ import annotations

import hashlib
import io
import json
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient


def agent_headers(token: str) -> dict[str, str]:
    return {"X-Agent-Token": token}


def signed_agent_bundle(private_key, version: str = "1.0.1") -> bytes:
    files = {
        "HosMonitorAgent.ps1": b"# signed agent\n",
        "HosMonitorWallpaper.ps1": b"# signed wallpaper helper\n",
        "VERSION": (version + "\n").encode(),
    }
    package_buffer = io.BytesIO()
    with zipfile.ZipFile(package_buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, content in files.items():
            package.writestr(name, content)
    package_bytes = package_buffer.getvalue()
    package_name = f"HosMonitorAgent-update-{version}.zip"
    manifest = {
        "schema": 1, "kind": "hosmonitor-agent", "version": version,
        "package": package_name, "package_sha256": hashlib.sha256(package_bytes).hexdigest(),
        "files": [
            {"path": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in files.items()
        ],
    }
    raw_manifest = (json.dumps(manifest, indent=2) + "\n").encode()
    signature = private_key.sign(raw_manifest, padding.PKCS1v15(), hashes.SHA256())
    bundle_buffer = io.BytesIO()
    with zipfile.ZipFile(bundle_buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", raw_manifest)
        bundle.writestr("manifest.sig", signature)
        bundle.writestr(package_name, package_bytes)
    return bundle_buffer.getvalue()


def install_test_public_key(client: TestClient):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client.app.state.config.update_public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return private_key


def test_admin_can_roll_out_signed_agent_release(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict,
):
    private_key = install_test_public_key(client)
    csrf = admin["csrf_token"]
    first = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()
    uploaded = client.post(
        "/api/ui/agent-updates/releases", content=signed_agent_bundle(private_key),
        headers={"X-CSRF-Token": csrf, "X-Admin-Password": "correct-horse-123", "Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 201, uploaded.text
    release_id = uploaded.json()["id"]
    rollout = client.post(
        "/api/ui/agent-updates/rollouts",
        json={
            "release_id": release_id, "target_type": "asset", "target_value": str(first["asset_id"]),
            "admin_password": "correct-horse-123", "confirmation": "UPDATE AGENT",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert rollout.status_code == 201, rollout.text
    directive = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()["agent_update"]
    assert directive["enabled"] is True
    assert directive["release_id"] == release_id
    assert client.get(directive["download_url"]).status_code == 401
    downloaded = client.get(directive["download_url"], headers=agent_headers(agent_token))
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == directive["sha256"]

    completed_payload = {
        **heartbeat_payload, "agent_version": "1.0.1", "agent_update_release_id": release_id,
        "agent_update_status": "applied", "agent_update_error": "",
    }
    completed = client.post(
        "/agent/v1/heartbeat", json=completed_payload, headers=agent_headers(agent_token)
    ).json()
    assert completed["agent_update"] == {"enabled": False}
    history = client.get("/api/ui/agent-updates").json()["rollouts"][0]
    assert history["applied"] == 1


def test_same_version_rollout_is_applied_without_download_directive(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict,
):
    private_key = install_test_public_key(client)
    csrf = admin["csrf_token"]
    first = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()
    uploaded = client.post(
        "/api/ui/agent-updates/releases", content=signed_agent_bundle(private_key, version="0.1.0"),
        headers={"X-CSRF-Token": csrf, "X-Admin-Password": "correct-horse-123", "Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 201, uploaded.text
    rollout = client.post(
        "/api/ui/agent-updates/rollouts",
        json={
            "release_id": uploaded.json()["id"], "target_type": "asset", "target_value": str(first["asset_id"]),
            "admin_password": "correct-horse-123", "confirmation": "UPDATE AGENT",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert rollout.status_code == 201, rollout.text

    directive = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()["agent_update"]
    assert directive == {"enabled": False}
    history = client.get("/api/ui/agent-updates").json()["rollouts"][0]
    assert history["delivered"] == 1
    assert history["applied"] == 1
    assert history["pending"] == 0


def test_invalid_agent_signature_and_bad_confirmation_are_rejected(
    client: TestClient, admin: dict,
):
    install_test_public_key(client)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    headers = {"X-CSRF-Token": admin["csrf_token"], "X-Admin-Password": "correct-horse-123"}
    rejected = client.post(
        "/api/ui/agent-updates/releases", content=signed_agent_bundle(wrong_key), headers=headers
    )
    assert rejected.status_code == 400
    assert "signature" in rejected.json()["detail"].lower()
