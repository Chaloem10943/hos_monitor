from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from server.config import AppConfig, application_dir, load_config
from server.store import iso
from server.updater import UpdateError, update_root, verify_manifest


def log(config: AppConfig, message: str) -> None:
    path = update_root(config) / "updater.log"
    with path.open("a", encoding="utf-8") as output:
        output.write(f"{iso()} {message}\n")


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def service_command(name: str, action: str) -> None:
    result = subprocess.run(["sc.exe", action, name], capture_output=True, text=True, timeout=30)
    if result.returncode != 0 and not (action == "stop" and "1062" in (result.stdout + result.stderr)):
        raise UpdateError(f"cannot {action} service {name}: {(result.stdout + result.stderr).strip()}")


def wait_service(name: str, desired: str, timeout: int = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(["sc.exe", "query", name], capture_output=True, text=True, timeout=15)
        if desired in result.stdout:
            return
        time.sleep(1)
    raise UpdateError(f"service {name} did not reach {desired}")


def sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)


def health_check(config: AppConfig, expected_version: str, timeout: int = 60) -> None:
    url = f"http://127.0.0.1:{config.port}/health"
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                body = json.loads(response.read())
            if body.get("status") == "ok" and body.get("version") == expected_version:
                return
            last_error = f"unexpected health response: {body}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(2)
    raise UpdateError(f"server health check failed: {last_error}")


def backup_current(config: AppConfig, version: str, label: str) -> Path:
    root = update_root(config) / "backups"
    name = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + f"-{label}-{version}"
    target = root / name
    target.mkdir(parents=True, exist_ok=False)
    server_exe = application_dir() / "HosMonitorServer.exe"
    version_file = application_dir() / "VERSION"
    if not server_exe.is_file() or not version_file.is_file():
        raise UpdateError("installed server executable or VERSION is missing")
    shutil.copy2(server_exe, target / "HosMonitorServer.exe")
    shutil.copy2(version_file, target / "VERSION")
    if config.database_path.is_file():
        sqlite_backup(config.database_path, target / "hos_monitor.db")
    shutil.copy2(config.config_path, target / "config.yaml")
    atomic_json(target / "backup.json", {"version": version, "created_at": iso(), "database": config.database_path.name})
    return target


def restore_backup(config: AppConfig, backup: Path) -> str:
    details = json.loads((backup / "backup.json").read_text(encoding="utf-8"))
    shutil.copy2(backup / "HosMonitorServer.exe", application_dir() / "HosMonitorServer.exe.new")
    os.replace(application_dir() / "HosMonitorServer.exe.new", application_dir() / "HosMonitorServer.exe")
    shutil.copy2(backup / "VERSION", application_dir() / "VERSION.new")
    os.replace(application_dir() / "VERSION.new", application_dir() / "VERSION")
    if (backup / "hos_monitor.db").is_file():
        Path(str(config.database_path) + "-wal").unlink(missing_ok=True)
        Path(str(config.database_path) + "-shm").unlink(missing_ok=True)
        shutil.copy2(backup / "hos_monitor.db", config.database_path)
    return str(details["version"])


def write_history(config: AppConfig, request: dict, status: str, backup: Path | None, error: str = "") -> None:
    try:
        with sqlite3.connect(config.database_path, timeout=30) as connection:
            connection.execute(
                """INSERT INTO system_updates
                   (from_version,to_version,release_tag,package_checksum,action,status,started_by,
                    started_at,completed_at,backup_path,error_message,details_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (request.get("from_version", ""), request.get("to_version", ""), request.get("release_tag", ""),
                 request.get("package_checksum", ""), request.get("action", "update"), status,
                 request.get("requested_by", ""), request.get("requested_at", iso()), iso(),
                 str(backup) if backup else None, error or None, json.dumps(request, ensure_ascii=False)),
            )
    except Exception as exc:
        log(config, f"history write failed: {exc}")


def prune_backups(config: AppConfig) -> None:
    root = update_root(config) / "backups"
    if not root.exists():
        return
    items = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in items[config.update_backup_retention:]:
        shutil.rmtree(path)


def verify_pending_update(config: AppConfig, request: dict) -> None:
    manifest_path = Path(request["manifest_path"]).resolve()
    signature_path = Path(request["signature_path"]).resolve()
    stage_root = (update_root(config) / "staging").resolve()
    if stage_root not in manifest_path.parents or stage_root not in signature_path.parents:
        raise UpdateError("staged update path escaped update storage")
    manifest = verify_manifest(manifest_path.read_bytes(), signature_path.read_bytes(), config)
    if manifest["version"] != request["to_version"] or manifest["package_sha256"] != request["package_checksum"]:
        raise UpdateError("pending request does not match signed manifest")
    expected = {item["path"]: item["sha256"] for item in manifest["files"]}
    import hashlib
    for key, name in (("staged_executable", "HosMonitorServer.exe"), ("staged_version", "VERSION")):
        path = Path(request[key]).resolve()
        if stage_root not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]:
            raise UpdateError(f"staged file verification failed: {name}")


def apply_request(config: AppConfig, request: dict) -> None:
    root = update_root(config)
    running = root / "running.json"
    pending = root / "pending.json"
    maintenance = root / "maintenance.json"
    state = root / "state.json"
    action = request.get("action")
    rollback_source: Path | None = None
    if action == "update":
        verify_pending_update(config, request)
    elif action == "rollback":
        rollback_source = Path(str(request.get("backup_path", "")))
        if not rollback_source.is_dir():
            raise UpdateError("rollback source backup is missing")
    else:
        raise UpdateError("unknown updater action")
    atomic_json(running, request)
    pending.unlink(missing_ok=True)
    atomic_json(maintenance, {"status": "maintenance", **request})
    atomic_json(state, {"status": "installing", **request})
    backup: Path | None = None
    stopped = False
    try:
        backup = backup_current(config, str(request["from_version"]), action)
        request["safety_backup_path"] = str(backup)
        if action == "update":
            request["backup_path"] = str(backup)
        atomic_json(running, request)
        atomic_json(maintenance, {"status": "maintenance", **request})
        atomic_json(state, {"status": "installing", **request})
        service_command(config.server_service_name, "stop")
        wait_service(config.server_service_name, "STOPPED")
        stopped = True
        if action == "update":
            shutil.copy2(Path(request["staged_executable"]), application_dir() / "HosMonitorServer.exe.new")
            os.replace(application_dir() / "HosMonitorServer.exe.new", application_dir() / "HosMonitorServer.exe")
            shutil.copy2(Path(request["staged_version"]), application_dir() / "VERSION.new")
            os.replace(application_dir() / "VERSION.new", application_dir() / "VERSION")
            target_version = str(request["to_version"])
        else:
            if rollback_source is None:
                raise UpdateError("rollback source backup is missing")
            target_version = restore_backup(config, rollback_source)
        service_command(config.server_service_name, "start")
        stopped = False
        wait_service(config.server_service_name, "RUNNING")
        health_check(config, target_version)
        write_history(config, request, "completed", backup)
        atomic_json(state, {"status": "completed", "completed_at": iso(), **request})
        maintenance.unlink(missing_ok=True)
        running.unlink(missing_ok=True)
        prune_backups(config)
        log(config, f"{action} completed: {request['from_version']} -> {target_version}")
    except Exception as exc:
        log(config, f"{action} failed: {exc}")
        recovery_error = ""
        try:
            if not stopped:
                service_command(config.server_service_name, "stop")
                wait_service(config.server_service_name, "STOPPED")
            if backup:
                restored = restore_backup(config, backup)
                service_command(config.server_service_name, "start")
                wait_service(config.server_service_name, "RUNNING")
                health_check(config, restored)
        except Exception as recovery:
            recovery_error = f"; automatic recovery failed: {recovery}"
        message = str(exc) + recovery_error
        write_history(config, request, "failed", backup, message)
        atomic_json(state, {"status": "failed", "completed_at": iso(), "error": message, **request})
        maintenance.unlink(missing_ok=True)
        running.unlink(missing_ok=True)


def recover_interrupted(config: AppConfig) -> None:
    root = update_root(config)
    running = root / "running.json"
    if not running.exists():
        return
    request = json.loads(running.read_text(encoding="utf-8"))
    backup_text = request.get("safety_backup_path") or request.get("backup_path")
    try:
        if not backup_text or not Path(backup_text).is_dir():
            raise UpdateError("interrupted update has no usable backup")
        service_command(config.server_service_name, "stop")
        try:
            wait_service(config.server_service_name, "STOPPED")
        except UpdateError:
            pass
        restored = restore_backup(config, Path(backup_text))
        service_command(config.server_service_name, "start")
        health_check(config, restored)
        write_history(config, request, "failed", Path(backup_text), "recovered after interrupted update")
        atomic_json(root / "state.json", {"status": "failed", "error": "recovered after interrupted update", **request})
    except Exception as exc:
        log(config, f"interrupted update requires manual recovery: {exc}")
        return
    (root / "maintenance.json").unlink(missing_ok=True)
    running.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--stage", help="Path to .hmrelease bundle to stage for installation")
    parser.add_argument("--requested-by", default="Administrator", help="Identity requesting update")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.stage:
        from server.config import save_update_config
        from server.updater import stage_release_bundle
        if not config.update_enabled:
            config = save_update_config(config, enabled=True, backup_retention=config.update_backup_retention)
        raw = Path(args.stage).read_bytes()
        res = stage_release_bundle(config, raw, args.requested_by)
        print(f"Staged update successfully: {res}")
        return 0
    recover_interrupted(config)
    while True:
        try:
            config = load_config(args.config)
        except Exception as exc:
            log(config, f"config reload failed; keeping previous settings: {exc}")
        pending = update_root(config) / "pending.json"
        if pending.exists():
            try:
                request = json.loads(pending.read_text(encoding="utf-8"))
                not_before = datetime.fromisoformat(str(request["not_before"]).replace("Z", "+00:00"))
                if datetime.now(UTC) >= not_before:
                    apply_request(config, request)
            except Exception as exc:
                log(config, f"pending request rejected: {exc}")
                atomic_json(update_root(config) / "state.json", {"status": "failed", "error": str(exc), "completed_at": iso()})
                pending.unlink(missing_ok=True)
        if args.once:
            return 0
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
