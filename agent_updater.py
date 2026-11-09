from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


INSTALL_DIRECTORY = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "HosMonitor Agent"
DATA_DIRECTORY = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "HosMonitor"
UPDATE_DIRECTORY = DATA_DIRECTORY / "agent-updates"
PENDING_PATH = UPDATE_DIRECTORY / "pending.json"
STATUS_PATH = UPDATE_DIRECTORY / "status.json"
LOG_PATH = UPDATE_DIRECTORY / "updater.log"
PUBLIC_KEY_PATH = INSTALL_DIRECTORY / "update_public.pem"
SERVICE_NAME = "HosMonitorAgent"
ALLOWED_FILES = {"HosMonitorAgent.ps1", "HosMonitorWallpaper.ps1", "VERSION"}
MAX_BUNDLE_BYTES = 50 * 1024 * 1024


def log(message: str) -> None:
    UPDATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def status(release_id: int, version: str, state: str, error: str = "") -> None:
    atomic_json(STATUS_PATH, {
        "release_id": release_id, "version": version, "status": state,
        "error": error[:500], "updated_at": datetime.now().astimezone().isoformat(),
    })


def run(command: list[str], timeout: int = 45) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, check=False, timeout=timeout, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def wait_service(running: bool, timeout: int = 30) -> bool:
    deadline = time.monotonic() + timeout
    expected = "RUNNING" if running else "STOPPED"
    while time.monotonic() < deadline:
        result = run(["sc.exe", "query", SERVICE_NAME])
        if expected in result.stdout.upper() or (not running and result.returncode != 0):
            return True
        time.sleep(1)
    return False


def verify_bundle(path: Path) -> tuple[str, dict[str, bytes]]:
    if not path.is_file() or path.stat().st_size < 1 or path.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError("Agent update bundle size is invalid")
    raw = path.read_bytes()
    try:
        outer = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError("Agent update bundle is invalid") from exc
    entries = {item.filename: item for item in outer.infolist() if not item.is_dir()}
    if len(entries) != 3 or "manifest.json" not in entries or "manifest.sig" not in entries:
        raise ValueError("Agent update bundle layout is invalid")
    raw_manifest = outer.read("manifest.json")
    try:
        key = serialization.load_pem_public_key(PUBLIC_KEY_PATH.read_bytes())
        key.verify(outer.read("manifest.sig"), raw_manifest, padding.PKCS1v15(), hashes.SHA256())
    except (OSError, ValueError, InvalidSignature) as exc:
        raise ValueError("Agent update signature is invalid") from exc
    manifest = json.loads(raw_manifest)
    package_name = str(manifest.get("package", ""))
    package_path = PurePosixPath(package_name)
    if manifest.get("schema") != 1 or manifest.get("kind") != "hosmonitor-agent":
        raise ValueError("Agent update manifest is unsupported")
    if package_path.is_absolute() or ".." in package_path.parts or len(package_path.parts) != 1 or package_name not in entries:
        raise ValueError("Agent package name is invalid")
    package = outer.read(package_name)
    if hashlib.sha256(package).hexdigest() != str(manifest.get("package_sha256", "")):
        raise ValueError("Agent package checksum is invalid")
    try:
        inner = zipfile.ZipFile(io.BytesIO(package))
    except zipfile.BadZipFile as exc:
        raise ValueError("Agent package is invalid") from exc
    names = {item.filename for item in inner.infolist() if not item.is_dir()}
    if names != ALLOWED_FILES:
        raise ValueError("Agent package contains an unapproved file")
    expected = {str(item.get("path")): item for item in manifest.get("files", []) if isinstance(item, dict)}
    if set(expected) != ALLOWED_FILES:
        raise ValueError("Agent file manifest is invalid")
    files: dict[str, bytes] = {}
    for name in ALLOWED_FILES:
        content = inner.read(name)
        item = expected[name]
        if len(content) != int(item.get("size", -1)) or hashlib.sha256(content).hexdigest() != str(item.get("sha256", "")):
            raise ValueError(f"Agent file verification failed: {name}")
        files[name] = content
    version = str(manifest.get("version", ""))
    if files["VERSION"].decode("utf-8-sig").strip() != version:
        raise ValueError("Agent VERSION does not match manifest")
    return version, files


def install_pending(pending: dict[str, object]) -> None:
    release_id = int(pending["release_id"])
    requested_version = str(pending["version"])
    bundle = Path(str(pending["bundle_path"])).resolve()
    if bundle.parent != UPDATE_DIRECTORY.resolve():
        raise ValueError("Agent update path is outside the update directory")
    version, files = verify_bundle(bundle)
    if version != requested_version:
        raise ValueError("Downloaded Agent version does not match the request")
    status(release_id, version, "installing")
    run(["sc.exe", "stop", SERVICE_NAME])
    if not wait_service(False):
        raise RuntimeError("HosMonitorAgent did not stop")
    backup = UPDATE_DIRECTORY / "backups" / f"release-{release_id}"
    backup.mkdir(parents=True, exist_ok=True)
    for name in ALLOWED_FILES:
        current = INSTALL_DIRECTORY / name
        if current.is_file():
            shutil.copy2(current, backup / name)
    try:
        for name, content in files.items():
            target = INSTALL_DIRECTORY / name
            temporary = target.with_suffix(target.suffix + ".new")
            temporary.write_bytes(content)
            os.replace(temporary, target)
        result = run(["sc.exe", "start", SERVICE_NAME])
        if result.returncode != 0 or not wait_service(True):
            raise RuntimeError("HosMonitorAgent did not restart")
    except Exception:
        for name in ALLOWED_FILES:
            saved = backup / name
            if saved.is_file():
                shutil.copy2(saved, INSTALL_DIRECTORY / name)
        run(["sc.exe", "start", SERVICE_NAME])
        wait_service(True)
        raise
    PENDING_PATH.unlink(missing_ok=True)
    bundle.unlink(missing_ok=True)
    status(release_id, version, "applied")
    log(f"Agent release {release_id} v{version} applied")


def main() -> int:
    UPDATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    log("Agent updater started")
    while True:
        if PENDING_PATH.is_file():
            release_id = 0
            version = ""
            try:
                pending = json.loads(PENDING_PATH.read_text(encoding="utf-8-sig"))
                release_id = int(pending.get("release_id", 0))
                version = str(pending.get("version", ""))
                install_pending(pending)
            except Exception as exc:
                PENDING_PATH.unlink(missing_ok=True)
                status(release_id, version, "failed", str(exc))
                log(f"ERROR release={release_id}: {exc}")
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
