from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != "win32", reason="Agent runs on Windows only")
def test_new_agent_sends_bounded_inventory_immediately(tmp_path: Path):
    requests: list[tuple[str, dict]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8-sig"))
            requests.append((self.path, payload))
            if self.path == "/agent/v1/heartbeat":
                response = {
                    "asset_id": 1,
                    "server_time": "2026-10-04T00:00:00Z",
                    "policy": {
                        "heartbeat_seconds": 30,
                        "online_threshold_seconds": 300,
                        "boot_delay_seconds": 86400,
                        "daily_enabled": False,
                        "daily_time": "02:00",
                    },
                    "collect_requests": [],
                    "wallpaper": {"enabled": False, "revision": ""},
                    "agent_update": {"enabled": False},
                }
            elif self.path == "/agent/v1/inventory":
                response = {"asset_id": 1, "accepted": True}
            else:
                self.send_error(404)
                return
            raw = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, _format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = "runtime-test-agent-token-1234567890"
    config_path = tmp_path / "agent-config.json"
    config_path.write_text(json.dumps({
        "server_url": f"http://127.0.0.1:{server.server_port}",
        "agent_token": token,
        "asset_tag": "A" * 150,
        "department": "D" * 250,
    }), encoding="utf-8")
    command = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(ROOT / "agent" / "HosMonitorAgent.ps1"), "-ConfigPath", str(config_path), "-Once",
    ]
    try:
        first_result = subprocess.run(
            command,
            cwd=ROOT, capture_output=True, text=True, timeout=90, check=False,
        )
        second_result = subprocess.run(
            command,
            cwd=ROOT, capture_output=True, text=True, timeout=90, check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert [path for path, _ in requests] == [
        "/agent/v1/heartbeat", "/agent/v1/inventory", "/agent/v1/heartbeat",
    ]
    heartbeat = requests[0][1]
    inventory = requests[1][1]
    assert len(heartbeat["asset_tag"]) == 100
    assert len(heartbeat["department"]) == 200
    assert inventory["os_name"]
    assert inventory["cpu_name"]
    assert inventory["cpu_cores"] >= 1
    assert inventory["ram_total_bytes"] >= 1
    assert inventory["disks"]
    assert len(inventory["disks"]) <= 128
    assert len(inventory["network"]) <= 128
    assert len(inventory["software"]) <= 20_000
    assert all(len(item["name"]) <= 500 for item in inventory["software"])
    assert all(len(item["version"]) <= 200 for item in inventory["software"])
    assert all(len(item["publisher"]) <= 500 for item in inventory["software"])
    state = json.loads((tmp_path / "agent-state.json").read_text(encoding="utf-8-sig"))
    assert state["last_inventory_at"]
    log = (tmp_path / "agent.log").read_text(encoding="utf-8-sig")
    assert "Inventory sent successfully; disks=" in log
    assert token not in log
