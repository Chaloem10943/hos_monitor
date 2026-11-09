from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import winreg
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape


AGENT_SERVICE_NAME = "HosMonitorAgent"
UPDATER_SERVICE_NAME = "HosMonitorAgentUpdater"
INSTALL_DIRECTORY = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "HosMonitor Agent"
DATA_DIRECTORY = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "HosMonitor"
SERVICE_LOG_DIRECTORY = DATA_DIRECTORY / "service-logs"
BACKUP_DIRECTORY = DATA_DIRECTORY / "agent-backups"
SETUP_LOG = DATA_DIRECTORY / "agent-setup.log"


def bundled_path(*parts: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root.joinpath(*parts)


def log(message: str) -> None:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with SETUP_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def message(text: str, *, error: bool = False) -> None:
    flags = 0x10 if error else 0x40
    ctypes.windll.user32.MessageBoxW(None, text, "HosMonitor Agent", flags)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run(command: list[str], *, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    log("run: " + " ".join(command[:1] + ["<arguments>"]))
    return subprocess.run(
        command,
        check=check,
        timeout=timeout,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def load_bootstrap() -> dict[str, str]:
    path = bundled_path("agent", "bootstrap-config.json")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    server_url = str(raw.get("server_url", "")).strip().rstrip("/")
    token = str(raw.get("agent_token", "")).strip()
    version = str(raw.get("version", "")).strip()
    parsed = urlparse(server_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("ข้อมูลเครื่องแม่ในไฟล์ติดตั้งไม่ถูกต้อง")
    if len(token) < 24:
        raise RuntimeError("Agent token ในไฟล์ติดตั้งไม่ถูกต้อง")
    if not version:
        raise RuntimeError("ไม่พบหมายเลขเวอร์ชัน Agent")
    return {"server_url": server_url, "agent_token": token, "version": version}


def service_exists(service_name: str) -> bool:
    result = run(["sc.exe", "query", service_name], check=False)
    return result.returncode == 0


def wait_for_service_removed(service_name: str, timeout: int = 20) -> None:
    deadline = time.monotonic() + timeout
    while service_exists(service_name) and time.monotonic() < deadline:
        time.sleep(0.5)


def stop_and_remove_service(service_name: str, wrapper_name: str) -> None:
    if not service_exists(service_name):
        return
    wrapper = INSTALL_DIRECTORY / wrapper_name
    if wrapper.is_file():
        run([str(wrapper), "stop"], check=False)
        run([str(wrapper), "uninstall"], check=False)
    else:
        run(["sc.exe", "stop", service_name], check=False)
        run(["sc.exe", "delete", service_name], check=False)
    wait_for_service_removed(service_name)
    if service_exists(service_name):
        raise RuntimeError("ไม่สามารถหยุด Service รุ่นเดิมได้ กรุณา Restart Windows แล้วลองใหม่")


def stop_and_remove_services() -> None:
    stop_and_remove_service(AGENT_SERVICE_NAME, "HosMonitorAgentService.exe")
    stop_and_remove_service(UPDATER_SERVICE_NAME, "HosMonitorAgentUpdaterService.exe")
    # Clean up pre-installer Agent builds and orphaned PowerShell collectors.
    for image_name in (
        "HosMonitorAgent.exe", "HosMonitorAgentUpdater.exe",
        "HosMonitorAgentService.exe", "HosMonitorAgentUpdaterService.exe",
    ):
        run(["taskkill.exe", "/F", "/T", "/IM", image_name], check=False)
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    cleanup = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.ProcessId -ne $PID -and $_.Name -in @('powershell.exe','pwsh.exe') -and "
        "$_.CommandLine -like '*HosMonitorAgent.ps1*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", cleanup], check=False)
    time.sleep(1)


def copy_with_retry(source: Path, destination: Path, attempts: int = 10) -> None:
    for attempt in range(attempts):
        try:
            shutil.copy2(source, destination)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(1)


def installed_version() -> str:
    version_path = INSTALL_DIRECTORY / "VERSION"
    if not version_path.is_file():
        return "unknown"
    return version_path.read_text(encoding="utf-8-sig").strip() or "unknown"


def make_backup() -> Path | None:
    if not INSTALL_DIRECTORY.is_dir():
        return None
    BACKUP_DIRECTORY.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = BACKUP_DIRECTORY / f"{installed_version()}-{stamp}"
    shutil.copytree(INSTALL_DIRECTORY, destination)
    backups = sorted((item for item in BACKUP_DIRECTORY.iterdir() if item.is_dir()), key=lambda item: item.stat().st_mtime)
    for old in backups[:-3]:
        shutil.rmtree(old, ignore_errors=True)
    log(f"backup: {destination}")
    return destination


def read_existing_config() -> dict[str, object]:
    path = DATA_DIRECTORY / "agent-config.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_config(profile: dict[str, str]) -> None:
    existing = read_existing_config()
    config = {
        "server_url": profile["server_url"],
        "agent_token": profile["agent_token"],
        "asset_tag": str(existing.get("asset_tag", "")),
        "department": str(existing.get("department", "")),
    }
    temporary = DATA_DIRECTORY / "agent-config.json.tmp"
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, DATA_DIRECTORY / "agent-config.json")


def restore_config(original: bytes | None) -> None:
    path = DATA_DIRECTORY / "agent-config.json"
    if original is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(original)


def copy_program_files(profile: dict[str, str]) -> None:
    INSTALL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    resources = bundled_path("agent")
    copy_with_retry(resources / "HosMonitorAgent.ps1", INSTALL_DIRECTORY / "HosMonitorAgent.ps1")
    copy_with_retry(resources / "HosMonitorWallpaper.ps1", INSTALL_DIRECTORY / "HosMonitorWallpaper.ps1")
    copy_with_retry(resources / "HosMonitorAgentUpdater.exe", INSTALL_DIRECTORY / "HosMonitorAgentUpdater.exe")
    copy_with_retry(resources / "update_public.pem", INSTALL_DIRECTORY / "update_public.pem")
    copy_with_retry(resources / "WinSW-x64.exe", INSTALL_DIRECTORY / "HosMonitorAgentService.exe")
    copy_with_retry(resources / "WinSW-x64.exe", INSTALL_DIRECTORY / "HosMonitorAgentUpdaterService.exe")
    copy_with_retry(Path(sys.executable), INSTALL_DIRECTORY / "HosMonitorAgentSetup.exe")
    (INSTALL_DIRECTORY / "VERSION").write_text(profile["version"] + "\n", encoding="utf-8")

    xml = (resources / "HosMonitorAgentService.xml.template").read_text(encoding="utf-8")
    xml = xml.replace("{{AGENT_SCRIPT}}", escape(str(INSTALL_DIRECTORY / "HosMonitorAgent.ps1")))
    xml = xml.replace("{{CONFIG_PATH}}", escape(str(DATA_DIRECTORY / "agent-config.json")))
    xml = xml.replace("{{LOG_PATH}}", escape(str(SERVICE_LOG_DIRECTORY)))
    (INSTALL_DIRECTORY / "HosMonitorAgentService.xml").write_text(xml, encoding="utf-8")
    updater_xml = (resources / "HosMonitorAgentUpdaterService.xml.template").read_text(encoding="utf-8")
    updater_xml = updater_xml.replace("{{UPDATER_EXE}}", escape(str(INSTALL_DIRECTORY / "HosMonitorAgentUpdater.exe")))
    updater_xml = updater_xml.replace("{{LOG_PATH}}", escape(str(SERVICE_LOG_DIRECTORY)))
    (INSTALL_DIRECTORY / "HosMonitorAgentUpdaterService.xml").write_text(updater_xml, encoding="utf-8")


def apply_acl() -> None:
    # SID values avoid failures on Thai or otherwise localized Windows installations.
    run([
        "icacls.exe", str(DATA_DIRECTORY), "/inheritance:r", "/grant:r",
        "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-19:(OI)(CI)M",
    ])
    run([
        "icacls.exe", str(INSTALL_DIRECTORY), "/inheritance:r", "/grant:r",
        "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-19:(OI)(CI)RX",
    ])
    wallpaper_directory = DATA_DIRECTORY / "wallpaper"
    wallpaper_directory.mkdir(parents=True, exist_ok=True)
    run([
        "icacls.exe", str(wallpaper_directory), "/inheritance:r", "/grant:r",
        "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-19:(OI)(CI)M",
        "*S-1-5-32-545:(OI)(CI)RX",
    ])


def register_wallpaper_helper() -> None:
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    helper = INSTALL_DIRECTORY / "HosMonitorWallpaper.ps1"
    policy = DATA_DIRECTORY / "wallpaper" / "wallpaper-policy.json"
    command = (
        f'"{powershell}" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass '
        f'-WindowStyle Hidden -File "{helper}" -PolicyPath "{policy}"'
    )
    access = winreg.KEY_SET_VALUE | getattr(winreg, "KEY_WOW64_64KEY", 0)
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
        0,
        access,
    ) as key:
        winreg.SetValueEx(key, "HosMonitorWallpaper", 0, winreg.REG_SZ, command)
    subprocess.Popen(
        [
            str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-File", str(helper), "-PolicyPath", str(policy),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def read_wallpaper_run_value() -> str | None:
    access = winreg.KEY_QUERY_VALUE | getattr(winreg, "KEY_WOW64_64KEY", 0)
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
            0,
            access,
        ) as key:
            return str(winreg.QueryValueEx(key, "HosMonitorWallpaper")[0])
    except FileNotFoundError:
        return None


def restore_wallpaper_run_value(original: str | None) -> None:
    access = winreg.KEY_SET_VALUE | getattr(winreg, "KEY_WOW64_64KEY", 0)
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
        0,
        access,
    ) as key:
        if original is None:
            try:
                winreg.DeleteValue(key, "HosMonitorWallpaper")
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(key, "HosMonitorWallpaper", 0, winreg.REG_SZ, original)


def install_and_start_services() -> None:
    updater_wrapper = INSTALL_DIRECTORY / "HosMonitorAgentUpdaterService.exe"
    agent_wrapper = INSTALL_DIRECTORY / "HosMonitorAgentService.exe"
    run([str(updater_wrapper), "install"])
    run([str(agent_wrapper), "install"])
    run([str(updater_wrapper), "start"])
    run([str(agent_wrapper), "start"])
    time.sleep(2)
    for service_name in (UPDATER_SERVICE_NAME, AGENT_SERVICE_NAME):
        result = run(["sc.exe", "query", service_name], check=False)
        if "RUNNING" not in result.stdout.upper():
            raise RuntimeError(f"ติดตั้งแล้วแต่ {service_name} Service ไม่ทำงาน กรุณาดู agent-setup.log")


SERVER_AUTHENTICATED = "authenticated"
SERVER_UNREACHABLE = "unreachable"
SERVER_TOKEN_INVALID = "invalid_token"


def check_server_access(server_url: str, agent_token: str) -> str:
    try:
        request = urllib.request.Request(server_url + "/health", headers={"User-Agent": "HosMonitorAgentSetup"})
        with urllib.request.urlopen(request, timeout=4) as response:
            if response.status != 200:
                log(f"health warning: HTTP {response.status}")
                return SERVER_UNREACHABLE
    except Exception as exc:
        log(f"health warning: {exc}")
        return SERVER_UNREACHABLE

    request = urllib.request.Request(
        server_url + "/agent/v1/update/0",
        headers={"User-Agent": "HosMonitorAgentSetup", "X-Agent-Token": agent_token},
    )
    try:
        with urllib.request.urlopen(request, timeout=4):
            return SERVER_AUTHENTICATED
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return SERVER_AUTHENTICATED
        if exc.code in {401, 403}:
            log(f"agent authentication rejected: HTTP {exc.code}")
            return SERVER_TOKEN_INVALID
        log(f"agent authentication warning: HTTP {exc.code}")
        return SERVER_UNREACHABLE
    except Exception as exc:
        log(f"agent authentication warning: {exc}")
        return SERVER_UNREACHABLE


def restore_backup(backup: Path | None) -> None:
    if backup is None or not backup.is_dir():
        return
    stop_and_remove_services()
    if INSTALL_DIRECTORY.exists():
        shutil.rmtree(INSTALL_DIRECTORY)
    shutil.copytree(backup, INSTALL_DIRECTORY)
    install_and_start_services()
    log(f"rollback completed: {backup}")


def install() -> tuple[str, bool, bool]:
    if not is_admin():
        raise RuntimeError("กรุณาคลิกขวาไฟล์แล้วเลือก Run as administrator")
    profile = load_bootstrap()
    preflight = check_server_access(profile["server_url"], profile["agent_token"])
    if preflight == SERVER_TOKEN_INVALID:
        raise RuntimeError(
            "Agent token ไม่ตรงกับเครื่องแม่ กรุณาใช้ตัวติดตั้งที่สร้างจาก config ของเครื่องแม่ปัจจุบัน"
        )
    previous = installed_version() if INSTALL_DIRECTORY.exists() else ""
    backup: Path | None = None
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    SERVICE_LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    config_path = DATA_DIRECTORY / "agent-config.json"
    original_config = config_path.read_bytes() if config_path.is_file() else None
    original_wallpaper_run = read_wallpaper_run_value()
    try:
        stop_and_remove_services()
        backup = make_backup()
        copy_program_files(profile)
        write_config(profile)
        apply_acl()
        register_wallpaper_helper()
        install_and_start_services()
    except Exception:
        restore_config(original_config)
        restore_wallpaper_run_value(original_wallpaper_run)
        if backup is not None:
            try:
                restore_backup(backup)
            except Exception as rollback_error:
                log(f"rollback failed: {rollback_error}")
        raise
    postflight = preflight
    if postflight == SERVER_UNREACHABLE:
        postflight = check_server_access(profile["server_url"], profile["agent_token"])
    if postflight == SERVER_TOKEN_INVALID:
        log("agent authentication rejected after offline installation")
    reachable = postflight == SERVER_AUTHENTICATED
    upgraded = bool(previous)
    log(f"success version={profile['version']} upgraded={upgraded} reachable={reachable}")
    return profile["version"], upgraded, reachable


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--silent", action="store_true")
    args, _ = parser.parse_known_args()
    try:
        version, upgraded, reachable = install()
        action = "อัปเดต" if upgraded else "ติดตั้ง"
        status = "เชื่อมต่อเครื่องแม่ได้แล้ว" if reachable else "ติดตั้งสำเร็จ แต่ยังติดต่อเครื่องแม่ไม่ได้ ระบบจะลองใหม่อัตโนมัติ"
        if not args.silent:
            message(f"{action} HosMonitor Agent v{version} เรียบร้อยแล้ว\n\n{status}")
        return 0
    except Exception as exc:
        try:
            log(f"ERROR: {exc}")
        except Exception:
            pass
        if not args.silent:
            message(f"ติดตั้ง HosMonitor Agent ไม่สำเร็จ\n\n{exc}\n\nLog: {SETUP_LOG}", error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
