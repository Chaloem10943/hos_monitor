from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from . import current_version
from .config import AppConfig
from .store import iso, utc_now


VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
MAX_BUNDLE_BYTES = 210 * 1024 * 1024
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
MAX_EXTRACTED_BYTES = 300 * 1024 * 1024
ALLOWED_PACKAGE_FILES = {"HosMonitorServer.exe", "VERSION"}


class UpdateError(RuntimeError):
    pass


def _version_tuple(value: str) -> tuple[int, int, int]:
    if not VERSION_PATTERN.fullmatch(value):
        raise UpdateError(f"invalid version: {value}")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def update_root(config: AppConfig) -> Path:
    path = config.data_dir / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def update_state(config: AppConfig) -> dict[str, Any]:
    state_path = update_root(config) / "state.json"
    if not state_path.exists():
        return {"status": "idle"}
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"status": "unknown"}
    except (OSError, json.JSONDecodeError):
        return {"status": "unknown"}


def verify_manifest(raw: bytes, signature: bytes, config: AppConfig) -> dict[str, Any]:
    if not config.update_public_key_path.is_file():
        raise UpdateError(f"update public key not found: {config.update_public_key_path}")
    try:
        public_key = serialization.load_pem_public_key(config.update_public_key_path.read_bytes())
        public_key.verify(signature, raw, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        raise UpdateError("release manifest signature is invalid") from exc
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpdateError("release manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise UpdateError("unsupported release manifest schema")
    version = str(manifest.get("version", ""))
    minimum = str(manifest.get("minimum_version", ""))
    _version_tuple(version)
    if _version_tuple(current_version()) < _version_tuple(minimum):
        raise UpdateError(f"version {minimum} must be installed before this release")
    package = str(manifest.get("package", ""))
    checksum = str(manifest.get("package_sha256", ""))
    if not NAME_PATTERN.fullmatch(package) or not package.endswith(".zip"):
        raise UpdateError("invalid update package name")
    if not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise UpdateError("invalid package checksum")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise UpdateError("manifest does not contain files")
    seen: set[str] = set()
    total = 0
    for item in files:
        if not isinstance(item, dict):
            raise UpdateError("invalid file entry in manifest")
        name = str(item.get("path", ""))
        size = item.get("size")
        file_hash = str(item.get("sha256", ""))
        if name not in ALLOWED_PACKAGE_FILES or name in seen:
            raise UpdateError(f"unsafe or duplicate release path: {name}")
        if not isinstance(size, int) or size < 0 or not re.fullmatch(r"[a-f0-9]{64}", file_hash):
            raise UpdateError(f"invalid release file metadata: {name}")
        total += size
        if total > MAX_EXTRACTED_BYTES:
            raise UpdateError("release expands beyond 300 MB")
        seen.add(name)
    if seen != ALLOWED_PACKAGE_FILES:
        raise UpdateError("release must contain HosMonitorServer.exe and VERSION")
    return manifest


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _safe_bundle_entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if Path(name).name != name or not NAME_PATTERN.fullmatch(name) or name in entries:
            raise UpdateError(f"unsafe or duplicate bundle path: {name}")
        entries[name] = info
    if "manifest.json" not in entries or "manifest.sig" not in entries or len(entries) != 3:
        raise UpdateError("release bundle must contain manifest.json, manifest.sig and one package")
    if entries["manifest.json"].file_size > 1024 * 1024 or entries["manifest.sig"].file_size > 16 * 1024:
        raise UpdateError("release metadata is too large")
    return entries


def stage_release_bundle(config: AppConfig, raw_bundle: bytes, requested_by: str) -> dict[str, Any]:
    if not config.update_enabled:
        raise UpdateError("system updates are disabled")
    if len(raw_bundle) > MAX_BUNDLE_BYTES:
        raise UpdateError("release bundle is larger than 210 MB")
    root = update_root(config)
    if (root / "pending.json").exists() or (root / "running.json").exists():
        raise UpdateError("another update is pending or running")
    try:
        bundle = zipfile.ZipFile(io.BytesIO(raw_bundle))
    except zipfile.BadZipFile as exc:
        raise UpdateError("release bundle is not a valid ZIP file") from exc
    with bundle:
        entries = _safe_bundle_entries(bundle)
        manifest_raw = bundle.read(entries["manifest.json"])
        signature = bundle.read(entries["manifest.sig"])
        manifest = verify_manifest(manifest_raw, signature, config)
        version = str(manifest["version"])
        if _version_tuple(version) <= _version_tuple(current_version()):
            raise UpdateError("release version must be newer than the installed version")
        package_name = str(manifest["package"])
        if package_name not in entries or entries[package_name].file_size > MAX_PACKAGE_BYTES:
            raise UpdateError("signed update package is missing or too large")
        stage = root / "staging" / f"{version}-{secrets.token_hex(4)}"
        stage.mkdir(parents=True, exist_ok=False)
        manifest_path = stage / "manifest.json"
        signature_path = stage / "manifest.sig"
        package_path = stage / package_name
        manifest_path.write_bytes(manifest_raw)
        signature_path.write_bytes(signature)
        digest = hashlib.sha256()
        with bundle.open(entries[package_name]) as source, package_path.open("wb") as output:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != manifest["package_sha256"]:
            raise UpdateError("release package checksum does not match")

    extracted = stage / "extracted"
    extracted.mkdir()
    expected = {item["path"]: item for item in manifest["files"]}
    try:
        with zipfile.ZipFile(package_path) as package:
            infos = [item for item in package.infolist() if not item.is_dir()]
            names = [item.filename for item in infos]
            if set(names) != set(expected) or len(names) != len(set(names)):
                raise UpdateError("ZIP contents do not match the signed manifest")
            for info in infos:
                if info.filename not in ALLOWED_PACKAGE_FILES or info.file_size != expected[info.filename]["size"]:
                    raise UpdateError(f"invalid ZIP entry: {info.filename}")
                target = extracted / info.filename
                digest = hashlib.sha256()
                with package.open(info) as source, target.open("wb") as output:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                        output.write(chunk)
                if digest.hexdigest() != expected[info.filename]["sha256"]:
                    raise UpdateError(f"file checksum mismatch: {info.filename}")
    except zipfile.BadZipFile as exc:
        raise UpdateError("signed update package is not a valid ZIP file") from exc

    pending = {
        "schema": 1, "action": "update", "requested_by": requested_by,
        "requested_at": iso(), "not_before": iso(utc_now() + timedelta(seconds=5)),
        "from_version": current_version(), "to_version": version,
        "release_tag": f"v{version}", "package_checksum": manifest["package_sha256"],
        "manifest_path": str(manifest_path.resolve()), "signature_path": str(signature_path.resolve()),
        "staged_executable": str((extracted / "HosMonitorServer.exe").resolve()),
        "staged_version": str((extracted / "VERSION").resolve()),
    }
    _atomic_json(root / "pending.json", pending)
    _atomic_json(root / "state.json", {"status": "pending", **pending})
    return {"status": "pending", "version": version, "message": "signed release staged; updater service will install it"}


def request_rollback(config: AppConfig, backup_path: Path, requested_by: str) -> dict[str, Any]:
    root = update_root(config)
    backups = (root / "backups").resolve()
    candidate = backup_path.resolve()
    if backups not in candidate.parents or not (candidate / "backup.json").is_file():
        raise UpdateError("invalid rollback backup")
    if (root / "pending.json").exists() or (root / "running.json").exists():
        raise UpdateError("another update is pending or running")
    details = json.loads((candidate / "backup.json").read_text(encoding="utf-8"))
    pending = {
        "schema": 1, "action": "rollback", "requested_by": requested_by,
        "requested_at": iso(), "not_before": iso(utc_now() + timedelta(seconds=5)),
        "from_version": current_version(), "to_version": str(details["version"]),
        "release_tag": "rollback", "package_checksum": "", "backup_path": str(candidate),
    }
    _atomic_json(root / "pending.json", pending)
    _atomic_json(root / "state.json", {"status": "pending", **pending})
    return {"status": "pending", "version": pending["to_version"], "message": "rollback requested"}
