from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .config import AppConfig


MAX_AGENT_BUNDLE_BYTES = 50 * 1024 * 1024
MAX_AGENT_PACKAGE_BYTES = 75 * 1024 * 1024
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
ALLOWED_AGENT_FILES = {"HosMonitorAgent.ps1", "HosMonitorWallpaper.ps1", "VERSION"}


class AgentUpdateError(ValueError):
    pass


def agent_release_root(config: AppConfig) -> Path:
    root = (config.data_dir / "agent-releases").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and len(path.parts) == 1


def verify_agent_bundle(config: AppConfig, raw_bundle: bytes) -> dict[str, Any]:
    if len(raw_bundle) < 1 or len(raw_bundle) > MAX_AGENT_BUNDLE_BYTES:
        raise AgentUpdateError("Agent release must be between 1 byte and 50 MB")
    try:
        outer = zipfile.ZipFile(io.BytesIO(raw_bundle))
    except zipfile.BadZipFile as exc:
        raise AgentUpdateError("Agent release is not a valid ZIP") from exc
    entries = {entry.filename: entry for entry in outer.infolist()}
    if "manifest.json" not in entries or "manifest.sig" not in entries or len(entries) != 3:
        raise AgentUpdateError("Agent release must contain signed manifest and one package")
    raw_manifest = outer.read("manifest.json")
    signature = outer.read("manifest.sig")
    if not config.update_public_key_path.is_file():
        raise AgentUpdateError("update public key is missing")
    try:
        public_key = serialization.load_pem_public_key(config.update_public_key_path.read_bytes())
        public_key.verify(signature, raw_manifest, padding.PKCS1v15(), hashes.SHA256())
    except (ValueError, InvalidSignature) as exc:
        raise AgentUpdateError("Agent release signature is invalid") from exc
    try:
        manifest = json.loads(raw_manifest)
    except json.JSONDecodeError as exc:
        raise AgentUpdateError("Agent release manifest is invalid") from exc
    if manifest.get("schema") != 1 or manifest.get("kind") != "hosmonitor-agent":
        raise AgentUpdateError("unsupported Agent release manifest")
    version = str(manifest.get("version", ""))
    package_name = str(manifest.get("package", ""))
    if not VERSION_PATTERN.fullmatch(version) or not _safe_name(package_name) or package_name not in entries:
        raise AgentUpdateError("invalid Agent release metadata")
    package = outer.read(package_name)
    if len(package) > MAX_AGENT_PACKAGE_BYTES:
        raise AgentUpdateError("Agent package is too large")
    digest = hashlib.sha256(package).hexdigest()
    if digest != str(manifest.get("package_sha256", "")):
        raise AgentUpdateError("Agent package checksum does not match")
    try:
        inner = zipfile.ZipFile(io.BytesIO(package))
    except zipfile.BadZipFile as exc:
        raise AgentUpdateError("Agent package is not a valid ZIP") from exc
    names = {entry.filename for entry in inner.infolist() if not entry.is_dir()}
    if names != ALLOWED_AGENT_FILES:
        raise AgentUpdateError("Agent package contains files outside the allowlist")
    expected = {str(item.get("path")): item for item in manifest.get("files", []) if isinstance(item, dict)}
    if set(expected) != ALLOWED_AGENT_FILES:
        raise AgentUpdateError("Agent manifest file list is invalid")
    for name in ALLOWED_AGENT_FILES:
        content = inner.read(name)
        item = expected[name]
        if len(content) != int(item.get("size", -1)) or hashlib.sha256(content).hexdigest() != item.get("sha256"):
            raise AgentUpdateError(f"Agent file verification failed: {name}")
    if inner.read("VERSION").decode("utf-8-sig").strip() != version:
        raise AgentUpdateError("Agent VERSION does not match manifest")
    return {"version": version, "sha256": hashlib.sha256(raw_bundle).hexdigest(), "size_bytes": len(raw_bundle)}


def store_agent_bundle(config: AppConfig, raw_bundle: bytes, version: str, digest: str) -> Path:
    root = agent_release_root(config)
    target = root / f"HosMonitorAgent-{version}-{digest[:12]}.hmagent"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(raw_bundle)
    os.replace(temporary, target)
    return target
