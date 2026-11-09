from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_key(private_path: Path, public_path: Path) -> None:
    if private_path.exists() or public_path.exists():
        raise SystemExit("refusing to overwrite an existing signing key")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def build_release(project: Path, version: str, minimum_version: str, private_key_path: Path) -> Path:
    if not VERSION_PATTERN.fullmatch(version) or not VERSION_PATTERN.fullmatch(minimum_version):
        raise SystemExit("version and minimum-version must use x.y.z")
    source_version = (project / "VERSION").read_text(encoding="utf-8").strip()
    if source_version != version:
        raise SystemExit(f"VERSION contains {source_version}; expected {version}")
    executable = project / "dist" / "HosMonitorServer.exe"
    if not executable.is_file():
        raise SystemExit("dist/HosMonitorServer.exe is missing; build the server first")
    output = project / "release-output" / f"v{version}"
    output.mkdir(parents=True, exist_ok=True)
    package = output / f"HosMonitorServer-update-{version}.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(executable, "HosMonitorServer.exe")
        archive.writestr("VERSION", version + "\n")
    version_bytes = (version + "\n").encode("utf-8")
    manifest = {
        "schema": 1,
        "version": version,
        "minimum_version": minimum_version,
        "package": package.name,
        "package_sha256": sha256(package),
        "built_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "files": [
            {
                "path": "HosMonitorServer.exe",
                "size": executable.stat().st_size,
                "sha256": sha256(executable),
            },
            {
                "path": "VERSION",
                "size": len(version_bytes),
                "sha256": hashlib.sha256(version_bytes).hexdigest(),
            },
        ],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (output / "manifest.json").write_bytes(manifest_bytes)
    key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    signature = key.sign(manifest_bytes, padding.PKCS1v15(), hashes.SHA256())
    (output / "manifest.sig").write_bytes(signature)
    bundle = output / f"HosMonitorServer-{version}.hmrelease"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        archive.writestr("manifest.sig", signature)
        archive.write(package, package.name)
    return output


def build_agent_release(project: Path, version: str, private_key_path: Path) -> Path:
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit("version must use x.y.z")
    source_version = (project / "AGENT_VERSION").read_text(encoding="utf-8").strip()
    if source_version != version:
        raise SystemExit(f"AGENT_VERSION contains {source_version}; expected {version}")
    sources = {
        "HosMonitorAgent.ps1": project / "agent" / "HosMonitorAgent.ps1",
        "HosMonitorWallpaper.ps1": project / "agent" / "HosMonitorWallpaper.ps1",
        "VERSION": project / "AGENT_VERSION",
    }
    for path in sources.values():
        if not path.is_file():
            raise SystemExit(f"missing Agent release file: {path}")
    output = project / "release-output" / f"v{version}"
    output.mkdir(parents=True, exist_ok=True)
    package = output / f"HosMonitorAgent-update-{version}.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sources.items():
            archive.write(path, name)
    manifest = {
        "schema": 1,
        "kind": "hosmonitor-agent",
        "version": version,
        "package": package.name,
        "package_sha256": sha256(package),
        "built_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "files": [
            {"path": name, "size": path.stat().st_size, "sha256": sha256(path)}
            for name, path in sources.items()
        ],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    signature = key.sign(manifest_bytes, padding.PKCS1v15(), hashes.SHA256())
    bundle = output / f"HosMonitorAgent-{version}.hmagent"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        archive.writestr("manifest.sig", signature)
        archive.write(package, package.name)
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="HosMonitor signed-release tools")
    subcommands = parser.add_subparsers(dest="command", required=True)
    key_parser = subcommands.add_parser("generate-key")
    key_parser.add_argument("--private", type=Path, required=True)
    key_parser.add_argument("--public", type=Path, required=True)
    release_parser = subcommands.add_parser("build-release")
    release_parser.add_argument("--project", type=Path, required=True)
    release_parser.add_argument("--version", required=True)
    release_parser.add_argument("--minimum-version", required=True)
    release_parser.add_argument("--private-key", type=Path, required=True)
    agent_parser = subcommands.add_parser("build-agent-release")
    agent_parser.add_argument("--project", type=Path, required=True)
    agent_parser.add_argument("--version", required=True)
    agent_parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "generate-key":
        generate_key(args.private.resolve(), args.public.resolve())
        print(f"Private key: {args.private.resolve()}")
        print(f"Public key:  {args.public.resolve()}")
    elif args.command == "build-release":
        output = build_release(
            args.project.resolve(), args.version, args.minimum_version, args.private_key.resolve()
        )
        print(f"Signed release: {output}")
    else:
        output = build_agent_release(
            args.project.resolve(), args.version, args.private_key.resolve()
        )
        print(f"Signed Agent release: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
