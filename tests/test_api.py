from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient


def agent_headers(token: str) -> dict[str, str]:
    return {"X-Agent-Token": token}


def test_agent_inventory_and_read_only_integration_api(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict, inventory_payload: dict
):
    heartbeat = client.post("/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token))
    assert heartbeat.status_code == 200
    assert heartbeat.json()["policy"]["heartbeat_seconds"] == 120
    inventory = client.post("/agent/v1/inventory", json=inventory_payload, headers=agent_headers(agent_token))
    assert inventory.status_code == 200

    key_response = client.post(
        "/api/ui/api-keys",
        json={"name": "asset-integration"},
        headers={"X-CSRF-Token": admin["csrf_token"]},
    )
    assert key_response.status_code == 201
    api_key = key_response.json()["api_key"]

    integration = TestClient(client.app, base_url="http://127.0.0.1")
    listed = integration.get(
        "/api/v1/assets?department=OPD&online=true",
        headers={"X-API-Key": api_key},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    asset = listed.json()["items"][0]
    assert asset["asset_tag"] == "MCH-0001"
    assert asset["agent_version"] == "0.1.0"
    assert asset["online"] is True

    detail = integration.get(f"/api/v1/assets/{asset['id']}", headers={"X-API-Key": api_key})
    assert detail.status_code == 200
    assert detail.json()["agent_version"] == "0.1.0"
    assert len(detail.json()["software"]) == 2
    assert detail.json()["online"] is True

    exported = client.get("/api/ui/export.csv")
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["agent_version"] == "0.1.0"

    inventory_payload["software"] = [inventory_payload["software"][0]]
    assert client.post("/agent/v1/inventory", json=inventory_payload, headers=agent_headers(agent_token)).status_code == 200
    refreshed = integration.get(f"/api/v1/assets/{asset['id']}", headers={"X-API-Key": api_key})
    assert [item["name"] for item in refreshed.json()["software"]] == ["Hospital App"]

    keys = client.get("/api/ui/api-keys").json()["items"]
    disabled = client.patch(
        f"/api/ui/api-keys/{keys[0]['id']}", json={"enabled": False},
        headers={"X-CSRF-Token": admin["csrf_token"]},
    )
    assert disabled.status_code == 200
    assert integration.get("/api/v1/assets", headers={"X-API-Key": api_key}).status_code == 401


def test_campaign_delivery_completion_and_admin_metadata_lock(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict, inventory_payload: dict
):
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    first = client.post("/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)).json()
    asset_id = first["asset_id"]
    patch = client.patch(
        f"/api/ui/assets/{asset_id}", json={"asset_tag": "ADMIN-TAG", "department": "LAB"}, headers=headers
    )
    assert patch.status_code == 200
    campaign = client.post(
        "/api/ui/campaigns", json={"target_type": "asset", "target_value": str(asset_id)}, headers=headers
    )
    campaign_id = campaign.json()["id"]

    heartbeat_payload["asset_tag"] = "AGENT-TAG"
    heartbeat_payload["department"] = "OTHER"
    second = client.post("/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)).json()
    assert second["collect_requests"] == [campaign_id]

    inventory_payload.update(heartbeat_payload)
    inventory_payload["completed_campaign_ids"] = [campaign_id]
    assert client.post("/agent/v1/inventory", json=inventory_payload, headers=agent_headers(agent_token)).status_code == 200
    third = client.post("/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)).json()
    assert third["collect_requests"] == []
    detail = client.get(f"/api/v1/assets/{asset_id}").json()
    assert detail["asset_tag"] == "ADMIN-TAG"
    assert detail["department"] == "LAB"


def test_viewer_cannot_mutate(client: TestClient, admin: dict):
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    created = client.post(
        "/api/ui/users", json={"username": "viewer1", "password": "viewer-password-123", "role": "viewer"}, headers=headers
    )
    assert created.status_code == 201
    client.post("/api/ui/logout", headers=headers)
    login = client.post("/api/ui/login", json={"username": "viewer1", "password": "viewer-password-123"})
    csrf = login.json()["csrf_token"]
    denied = client.post(
        "/api/ui/campaigns", json={"target_type": "all", "target_value": ""}, headers={"X-CSRF-Token": csrf}
    )
    assert denied.status_code == 403
    assert client.get("/api/v1/assets").status_code == 200


def test_agent_token_is_required(client: TestClient, heartbeat_payload: dict):
    assert client.post("/agent/v1/heartbeat", json=heartbeat_payload).status_code == 401
    assert client.post("/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers("wrong")).status_code == 401


def test_local_control_status(client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict):
    client.post("/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token))
    response = client.get("/control/v1/status")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["agents_registered"] == 1
    assert response.json()["agents_online"] == 1


def test_department_policy_and_campaign_scopes(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict
):
    csrf = {"X-CSRF-Token": admin["csrf_token"]}
    opd = client.post("/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)).json()
    lab_payload = {**heartbeat_payload, "machine_id": "machine-lab-002", "hostname": "LAB-PC-02", "department": "LAB"}
    client.post("/agent/v1/heartbeat", json=lab_payload, headers=agent_headers(agent_token))

    policy = {
        "scope_type": "department", "scope_value": "OPD", "heartbeat_seconds": 60,
        "online_threshold_seconds": 180, "boot_delay_seconds": 300,
        "daily_enabled": True, "daily_time": "03:15",
    }
    assert client.put("/api/ui/policies", json=policy, headers=csrf).status_code == 200
    department_campaign = client.post(
        "/api/ui/campaigns", json={"target_type": "department", "target_value": "OPD"}, headers=csrf
    ).json()["id"]
    opd_heartbeat = client.post("/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)).json()
    lab_heartbeat = client.post("/agent/v1/heartbeat", json=lab_payload, headers=agent_headers(agent_token)).json()
    assert opd_heartbeat["policy"]["heartbeat_seconds"] == 60
    assert opd_heartbeat["policy"]["daily_enabled"] is True
    assert department_campaign in opd_heartbeat["collect_requests"]
    assert department_campaign not in lab_heartbeat["collect_requests"]

    all_campaign = client.post(
        "/api/ui/campaigns", json={"target_type": "all", "target_value": ""}, headers=csrf
    ).json()["id"]
    assert all_campaign in client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()["collect_requests"]
    assert all_campaign in client.post(
        "/agent/v1/heartbeat", json=lab_payload, headers=agent_headers(agent_token)
    ).json()["collect_requests"]


def test_offline_filter_uses_last_seen_threshold(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict
):
    response = client.post("/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token))
    asset_id = response.json()["asset_id"]
    with client.app.state.database.connect() as connection:
        connection.execute("UPDATE assets SET last_seen='2020-01-01T00:00:00Z' WHERE id=?", (asset_id,))
    offline = client.get("/api/v1/assets?online=false")
    assert offline.status_code == 200
    assert offline.json()["total"] == 1
    assert offline.json()["items"][0]["online"] is False


def test_admin_agent_name_department_choices_and_wallpaper(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict
):
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    heartbeat = client.post("/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token))
    asset_id = heartbeat.json()["asset_id"]

    invalid = client.patch(
        f"/api/ui/assets/{asset_id}",
        json={"display_name": "เครื่องห้องบัตร", "asset_tag": "MCH-1", "department": "UNKNOWN"},
        headers=headers,
    )
    assert invalid.status_code == 422
    saved = client.patch(
        f"/api/ui/assets/{asset_id}",
        json={"display_name": "เครื่องห้องบัตร", "asset_tag": "MCH-1", "department": "OPD"},
        headers=headers,
    )
    assert saved.status_code == 200
    assert client.get(f"/api/v1/assets/{asset_id}").json()["display_name"] == "เครื่องห้องบัตร"

    departments = client.get("/api/ui/departments").json()["items"]
    assert {item["name"] for item in departments} == {"OPD", "LAB"}
    assert client.post("/api/ui/departments", json={"name": "OPD"}, headers=headers).status_code == 409

    image = b"\x89PNG\r\n\x1a\n" + b"test-wallpaper-content"
    uploaded = client.post(
        "/api/ui/wallpaper", content=image,
        headers={**headers, "Content-Type": "image/png"},
    )
    assert uploaded.status_code == 200, uploaded.text
    revision = uploaded.json()["revision"]
    directive = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()["wallpaper"]
    assert directive["enabled"] is True
    assert directive["revision"] == revision
    assert directive["locked"] is True
    downloaded = client.get(directive["download_url"], headers=agent_headers(agent_token))
    assert downloaded.status_code == 200
    assert downloaded.content == image

    reported = {**heartbeat_payload, "wallpaper_revision": revision, "wallpaper_status": "downloaded"}
    assert client.post("/agent/v1/heartbeat", json=reported, headers=agent_headers(agent_token)).status_code == 200
    detail = client.get(f"/api/v1/assets/{asset_id}").json()
    assert detail["wallpaper_revision"] == revision
    assert detail["wallpaper_status"] == "downloaded"
    assert client.delete("/api/ui/wallpaper", headers=headers).status_code == 200
    disabled = client.post(
        "/agent/v1/heartbeat", json=reported, headers=agent_headers(agent_token)
    ).json()["wallpaper"]
    assert disabled == {"enabled": False, "revision": ""}


def test_admin_can_retire_restore_and_permanently_delete_offline_asset(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict, inventory_payload: dict
):
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    created = client.post("/agent/v1/inventory", json=inventory_payload, headers=agent_headers(agent_token))
    assert created.status_code == 200
    asset_id = created.json()["asset_id"]

    retired = client.post(
        f"/api/ui/assets/{asset_id}/retire", json={"reason": "ลง Windows ใหม่"}, headers=headers
    )
    assert retired.status_code == 200
    assert client.get("/api/v1/assets").json()["total"] == 0
    retired_list = client.get("/api/v1/assets?retired=true").json()
    assert retired_list["total"] == 1
    assert retired_list["items"][0]["retired"] is True
    assert retired_list["items"][0]["retired_reason"] == "ลง Windows ใหม่"
    assert client.get("/api/ui/dashboard").json()["retired"] == 1

    still_reporting = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    )
    assert still_reporting.status_code == 200
    assert still_reporting.json()["collect_requests"] == []
    assert still_reporting.json()["wallpaper"] == {"enabled": False, "revision": ""}
    assert still_reporting.json()["agent_update"] == {"enabled": False}

    online_delete = client.request(
        "DELETE", f"/api/ui/assets/{asset_id}", headers=headers,
        json={"admin_password": "correct-horse-123", "confirmation": "DELETE"},
    )
    assert online_delete.status_code == 409

    restored = client.post(f"/api/ui/assets/{asset_id}/restore", json={}, headers=headers)
    assert restored.status_code == 200
    assert client.get("/api/v1/assets").json()["total"] == 1
    assert client.post(
        f"/api/ui/assets/{asset_id}/retire", json={"reason": "เครื่องเสีย"}, headers=headers
    ).status_code == 200
    with client.app.state.database.connect() as connection:
        connection.execute("UPDATE assets SET last_seen='2020-01-01T00:00:00Z' WHERE id=?", (asset_id,))

    wrong_password = client.request(
        "DELETE", f"/api/ui/assets/{asset_id}", headers=headers,
        json={"admin_password": "wrong-password", "confirmation": "DELETE"},
    )
    assert wrong_password.status_code == 403
    wrong_confirmation = client.request(
        "DELETE", f"/api/ui/assets/{asset_id}", headers=headers,
        json={"admin_password": "correct-horse-123", "confirmation": "delete"},
    )
    assert wrong_confirmation.status_code == 422

    deleted = client.request(
        "DELETE", f"/api/ui/assets/{asset_id}", headers=headers,
        json={"admin_password": "correct-horse-123", "confirmation": "DELETE"},
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/assets/{asset_id}").status_code == 404
    with client.app.state.database.connect() as connection:
        for table in ("asset_disks", "asset_network", "asset_software", "monitor_observations"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE asset_id=?", (asset_id,)).fetchone()[0] == 0


def test_hardware_identity_is_stored_and_oem_placeholders_are_removed(
    client: TestClient, admin: dict, agent_token: str, inventory_payload: dict
):
    inventory_payload.update({
        "manufacturer": "Dell Inc.", "model": "Latitude 5440", "bios_serial": "BIOS-123",
        "system_uuid": "12345678-1234-1234-1234-123456789abc",
        "baseboard_manufacturer": "Dell Inc.", "baseboard_product": "0ABC12",
        "baseboard_serial": "BOARD-456",
    })
    created = client.post("/agent/v1/inventory", json=inventory_payload, headers=agent_headers(agent_token))
    assert created.status_code == 200
    asset_id = created.json()["asset_id"]
    detail = client.get(f"/api/v1/assets/{asset_id}").json()
    assert detail["manufacturer"] == "Dell Inc."
    assert detail["model"] == "Latitude 5440"
    assert detail["bios_serial"] == "BIOS-123"
    assert detail["system_uuid"] == "12345678-1234-1234-1234-123456789abc"
    assert detail["baseboard_product"] == "0ABC12"
    assert detail["baseboard_serial"] == "BOARD-456"

    inventory_payload.update({
        "manufacturer": "To Be Filled By O.E.M.", "model": "Default String",
        "bios_serial": "Unknown", "baseboard_manufacturer": "System Manufacturer",
    })
    assert client.post(
        "/agent/v1/inventory", json=inventory_payload, headers=agent_headers(agent_token)
    ).status_code == 200
    cleaned = client.get(f"/api/v1/assets/{asset_id}").json()
    assert cleaned["manufacturer"] == ""
    assert cleaned["model"] == ""
    assert cleaned["bios_serial"] == ""
    assert cleaned["baseboard_manufacturer"] == ""


def test_department_rename_updates_references_and_maps_old_agent_name(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict
):
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    asset_id = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()["asset_id"]
    departments = client.get("/api/ui/departments").json()["items"]
    department_id = next(item["id"] for item in departments if item["name"] == "OPD")
    policy = {
        "scope_type": "department", "scope_value": "OPD", "heartbeat_seconds": 60,
        "online_threshold_seconds": 180, "boot_delay_seconds": 300,
        "daily_enabled": False, "daily_time": "02:00",
    }
    assert client.put("/api/ui/policies", json=policy, headers=headers).status_code == 200
    assert client.post(
        "/api/ui/campaigns", json={"target_type": "department", "target_value": "OPD"}, headers=headers
    ).status_code == 201
    with client.app.state.database.transaction() as connection:
        user_id = connection.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        release_id = connection.execute(
            """INSERT INTO agent_releases(version,filename,sha256,size_bytes,enabled,uploaded_by,uploaded_at)
               VALUES ('9.9.9','test.hmagent','rename-test-sha',1,1,?,?)""",
            (user_id, "2026-10-02T00:00:00Z"),
        ).lastrowid
        connection.execute(
            """INSERT INTO agent_rollouts(release_id,target_type,target_value,created_by,created_at,expires_at)
               VALUES (?,'department','OPD',?,'2026-10-02T00:00:00Z','2026-10-09T00:00:00Z')""",
            (release_id, user_id),
        )

    renamed = client.put(
        f"/api/ui/departments/{department_id}/name", json={"name": "งานผู้ป่วยนอก"}, headers=headers
    )
    assert renamed.status_code == 200, renamed.text
    with client.app.state.database.connect() as connection:
        assert connection.execute("SELECT department FROM assets WHERE id=?", (asset_id,)).fetchone()[0] == "งานผู้ป่วยนอก"
        assert connection.execute("SELECT scope_value FROM policies WHERE scope_type='department'").fetchone()[0] == "งานผู้ป่วยนอก"
        assert connection.execute("SELECT target_value FROM campaigns WHERE target_type='department'").fetchone()[0] == "งานผู้ป่วยนอก"
        assert connection.execute("SELECT target_value FROM agent_rollouts WHERE target_type='department'").fetchone()[0] == "งานผู้ป่วยนอก"
        assert connection.execute("SELECT alias FROM department_aliases WHERE department_id=?", (department_id,)).fetchone()[0] == "OPD"

    # An older Agent may keep reporting OPD; the Server must preserve the new name.
    assert client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).status_code == 200
    assert client.get(f"/api/v1/assets/{asset_id}").json()["department"] == "งานผู้ป่วยนอก"
    assert client.post("/api/ui/departments", json={"name": "opd"}, headers=headers).status_code == 409
    assert client.put(
        f"/api/ui/departments/{department_id}/name", json={"name": "OPD"}, headers=headers
    ).status_code == 409
    assert client.put(
        f"/api/ui/departments/{department_id}/name", json={"name": "LAB"}, headers=headers
    ).status_code == 409


def test_wallpaper_exclusion_search_delivery_and_removal(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict
):
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    heartbeat = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()
    asset_id = heartbeat["asset_id"]
    image = b"\x89PNG\r\n\x1a\n" + b"wallpaper-exclusion-test"
    uploaded = client.post(
        "/api/ui/wallpaper", content=image, headers={**headers, "Content-Type": "image/png"}
    )
    assert uploaded.status_code == 200
    assert client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()["wallpaper"]["enabled"] is True

    searched = client.get("/api/ui/wallpaper/exclusions?search=OPD-PC").json()
    assert [item["asset_id"] for item in searched["candidates"]] == [asset_id]
    assert client.post(
        "/api/ui/wallpaper/exclusions", json={"asset_id": asset_id, "reason": "จอประชาสัมพันธ์"},
    ).status_code == 403
    excluded = client.post(
        "/api/ui/wallpaper/exclusions", json={"asset_id": asset_id, "reason": "จอประชาสัมพันธ์"}, headers=headers
    )
    assert excluded.status_code == 201, excluded.text
    assert client.post(
        "/api/ui/wallpaper/exclusions", json={"asset_id": asset_id}, headers=headers
    ).status_code == 409
    directive = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()["wallpaper"]
    assert directive == {"enabled": False, "revision": ""}
    settings = client.get("/api/ui/wallpaper").json()
    assert settings["excluded_count"] == 1
    exclusions = client.get("/api/ui/wallpaper/exclusions").json()
    assert exclusions["total"] == 1
    assert exclusions["items"][0]["reason"] == "จอประชาสัมพันธ์"
    assert client.post(
        "/api/ui/wallpaper/exclusions", json={"asset_id": 999999}, headers=headers
    ).status_code == 404

    assert client.delete(f"/api/ui/wallpaper/exclusions/{asset_id}", headers=headers).status_code == 200
    restored = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()["wallpaper"]
    assert restored["enabled"] is True
    assert restored["revision"] == uploaded.json()["revision"]
    assert client.delete(f"/api/ui/wallpaper/exclusions/{asset_id}", headers=headers).status_code == 404


def test_wallpaper_exclusion_rejects_retired_asset_and_cascades_on_delete(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict
):
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    asset_id = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()["asset_id"]
    assert client.post(
        f"/api/ui/assets/{asset_id}/retire", json={"reason": "ทดสอบ"}, headers=headers
    ).status_code == 200
    assert client.post(
        "/api/ui/wallpaper/exclusions", json={"asset_id": asset_id}, headers=headers
    ).status_code == 409
    assert client.post(f"/api/ui/assets/{asset_id}/restore", json={}, headers=headers).status_code == 200
    assert client.post(
        "/api/ui/wallpaper/exclusions", json={"asset_id": asset_id}, headers=headers
    ).status_code == 201
    with client.app.state.database.transaction() as connection:
        connection.execute("DELETE FROM assets WHERE id=?", (asset_id,))
        assert connection.execute(
            "SELECT COUNT(*) FROM wallpaper_exclusions WHERE asset_id=?", (asset_id,)
        ).fetchone()[0] == 0


def test_viewer_can_read_but_cannot_change_wallpaper_exclusions(
    client: TestClient, admin: dict, agent_token: str, heartbeat_payload: dict
):
    admin_headers = {"X-CSRF-Token": admin["csrf_token"]}
    asset_id = client.post(
        "/agent/v1/heartbeat", json=heartbeat_payload, headers=agent_headers(agent_token)
    ).json()["asset_id"]
    assert client.post(
        "/api/ui/users", json={"username": "wallviewer", "password": "viewer-password-123", "role": "viewer"},
        headers=admin_headers,
    ).status_code == 201
    client.post("/api/ui/logout", headers=admin_headers)
    viewer = client.post(
        "/api/ui/login", json={"username": "wallviewer", "password": "viewer-password-123"}
    ).json()
    assert client.get("/api/ui/wallpaper/exclusions").status_code == 200
    denied = client.post(
        "/api/ui/wallpaper/exclusions", json={"asset_id": asset_id},
        headers={"X-CSRF-Token": viewer["csrf_token"]},
    )
    assert denied.status_code == 403


def test_branding_static_assets_are_served(client: TestClient):
    for path in (
        "/static/favicon.ico", "/static/assets/favicon-32.png",
        "/static/assets/apple-touch-icon.png", "/static/assets/hosmonitor-logo-512.png",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert len(response.content) > 100
