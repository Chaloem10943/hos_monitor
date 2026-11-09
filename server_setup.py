from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
import winreg
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import yaml


INSTALL_DIRECTORY = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "HosMonitor Server"
DATA_DIRECTORY = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "HosMonitorServer"
LOG_DIRECTORY = DATA_DIRECTORY / "logs"
BACKUP_DIRECTORY = DATA_DIRECTORY / "setup-backups"
SETUP_LOG = DATA_DIRECTORY / "server-setup.log"
SERVER_SERVICE = "HosMonitorServer"
UPDATER_SERVICE = "HosMonitorUpdater"
FIREWALL_RULE = "HosMonitor Server 6001"
PRIVATE_NETWORKS = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"


def bundled_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / "server-setup" / name


def log(message: str) -> None:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with SETUP_LOG.open("a", encoding="utf-8") as output:
        output.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def message(text: str, *, error: bool = False) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "HosMonitor Server Setup", 0x10 if error else 0x40)


def run(command: list[str], *, check: bool = True, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    log("run: " + command[0] + " <arguments>")
    return subprocess.run(
        command,
        check=check,
        timeout=timeout,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def is_admin() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def stop_old_system() -> None:
    for service, wrapper_name in (
        (UPDATER_SERVICE, "HosMonitorUpdaterService.exe"),
        (SERVER_SERVICE, "HosMonitorServerService.exe"),
    ):
        wrapper = INSTALL_DIRECTORY / wrapper_name
        if run(["sc.exe", "query", service], check=False).returncode == 0:
            if wrapper.is_file():
                run([str(wrapper), "stop"], check=False)
                run([str(wrapper), "uninstall"], check=False)
            else:
                run(["sc.exe", "stop", service], check=False)
                run(["sc.exe", "delete", service], check=False)
    for image in ("HosMonitorServer.exe", "HosMonitorUpdater.exe", "HosMonitorControl.exe", "HosMonitorServerControl.exe"):
        run(["taskkill.exe", "/F", "/T", "/IM", image], check=False)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        active = False
        for service in (UPDATER_SERVICE, SERVER_SERVICE):
            if run(["sc.exe", "query", service], check=False).returncode == 0:
                active = True
        if not active:
            return
        time.sleep(1)
    raise RuntimeError("Service รุ่นเดิมยังหยุดไม่สมบูรณ์ กรุณา Restart Windows แล้วเปิดตัวติดตั้งอีกครั้ง")


def backup_program_files() -> Path | None:
    if not INSTALL_DIRECTORY.is_dir():
        return None
    BACKUP_DIRECTORY.mkdir(parents=True, exist_ok=True)
    version_path = INSTALL_DIRECTORY / "VERSION"
    version = version_path.read_text(encoding="utf-8-sig").strip() if version_path.is_file() else "unknown"
    target = BACKUP_DIRECTORY / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{version}"
    shutil.copytree(INSTALL_DIRECTORY, target)
    backups = sorted(BACKUP_DIRECTORY.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)
    for old in backups[3:]:
        if old.is_dir():
            shutil.rmtree(old, ignore_errors=True)
    return target


def deployment_agent_token() -> str:
    profile = json.loads(bundled_path("server-bootstrap.json").read_text(encoding="utf-8-sig"))
    token = str(profile.get("agent_token", "")).strip()
    if len(token) < 24:
        raise RuntimeError("Deployment Agent token ไม่ถูกต้อง")
    return token


def ensure_config() -> Path:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    config_path = DATA_DIRECTORY / "config.yaml"
    if config_path.is_file():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig")) or {}
    else:
        config = {
            "server": {"host": "0.0.0.0", "port": 6001, "cookie_secure": False},
            "storage": {"data_dir": str(DATA_DIRECTORY), "database": "hos_monitor.db"},
            "security": {"session_hours": 8},
            "monitoring": {"online_threshold_seconds": 300},
            "updates": {
                "enabled": True, "backup_retention": 5,
                "public_key": "update_public.pem", "server_service_name": SERVER_SERVICE,
            },
        }
    security = config.setdefault("security", {})
    current_token = str(security.get("agent_token", "")).strip()
    if len(current_token) < 24:
        security["agent_token"] = deployment_agent_token()
    temporary = config_path.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(temporary, config_path)
    return config_path


def copy_program_files(config_path: Path) -> None:
    INSTALL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for name in ("HosMonitorServer.exe", "HosMonitorUpdater.exe", "HosMonitorServerControl.exe", "WinSW-x64.exe", "VERSION"):
        source = bundled_path(name)
        target_name = {
            "WinSW-x64.exe": "HosMonitorServerService.exe",
        }.get(name, name)
        shutil.copy2(source, INSTALL_DIRECTORY / target_name)
    shutil.copy2(bundled_path("WinSW-x64.exe"), INSTALL_DIRECTORY / "HosMonitorUpdaterService.exe")
    shutil.copy2(bundled_path("update_public.pem"), DATA_DIRECTORY / "update_public.pem")
    server_xml = bundled_path("HosMonitorServerService.xml.template").read_text(encoding="utf-8")
    server_xml = server_xml.replace("{{SERVER_EXE}}", escape(str(INSTALL_DIRECTORY / "HosMonitorServer.exe")))
    server_xml = server_xml.replace("{{CONFIG_PATH}}", escape(str(config_path)))
    server_xml = server_xml.replace("{{LOG_PATH}}", escape(str(LOG_DIRECTORY)))
    (INSTALL_DIRECTORY / "HosMonitorServerService.xml").write_text(server_xml, encoding="utf-8")
    updater_xml = bundled_path("HosMonitorUpdaterService.xml.template").read_text(encoding="utf-8")
    updater_xml = updater_xml.replace("{{UPDATER_EXE}}", escape(str(INSTALL_DIRECTORY / "HosMonitorUpdater.exe")))
    updater_xml = updater_xml.replace("{{CONFIG_PATH}}", escape(str(config_path)))
    updater_xml = updater_xml.replace("{{LOG_PATH}}", escape(str(LOG_DIRECTORY)))
    (INSTALL_DIRECTORY / "HosMonitorUpdaterService.xml").write_text(updater_xml, encoding="utf-8")


def apply_acl() -> None:
    run(["icacls.exe", str(DATA_DIRECTORY), "/inheritance:r", "/grant:r",
         "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-19:(OI)(CI)M"])
    run(["icacls.exe", str(INSTALL_DIRECTORY), "/inheritance:r", "/grant:r",
         "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-19:(OI)(CI)RX"])


def configure_firewall(port: int) -> None:
    run(["netsh.exe", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE}"], check=False)
    run([
        "netsh.exe", "advfirewall", "firewall", "add", "rule", f"name={FIREWALL_RULE}",
        "dir=in", "action=allow", "protocol=TCP", f"localport={port}", f"remoteip={PRIVATE_NETWORKS}",
        "profile=domain,private",
    ])


def register_control(port: int) -> None:
    control = INSTALL_DIRECTORY / "HosMonitorServerControl.exe"
    command = f'"{control}" --tray --port {port}'
    access = winreg.KEY_SET_VALUE | getattr(winreg, "KEY_WOW64_64KEY", 0)
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", 0, access,
    ) as key:
        winreg.SetValueEx(key, "HosMonitorServerControl", 0, winreg.REG_SZ, command)


def launch_control(port: int) -> None:
    control = INSTALL_DIRECTORY / "HosMonitorServerControl.exe"
    subprocess.Popen(
        [str(control), "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_desktop_shortcuts(port: int) -> None:
    desktop = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    dashboard = f"http://127.0.0.1:{port}"
    (desktop / "HosMonitor Dashboard.url").write_text(
        f"[InternetShortcut]\nURL={dashboard}\n", encoding="utf-8",
    )

    control = INSTALL_DIRECTORY / "HosMonitorServerControl.exe"
    shortcut_path = desktop / "HosMonitor Server Control.lnk"
    script = "; ".join((
        "$shell = New-Object -ComObject WScript.Shell",
        f"$shortcut = $shell.CreateShortcut({powershell_quote(str(shortcut_path))})",
        f"$shortcut.TargetPath = {powershell_quote(str(control))}",
        f"$shortcut.Arguments = {powershell_quote(f'--port {port}')}",
        f"$shortcut.WorkingDirectory = {powershell_quote(str(INSTALL_DIRECTORY))}",
        f"$shortcut.IconLocation = {powershell_quote(str(control) + ',0')}",
        "$shortcut.Description = 'HosMonitor Server Control'",
        "$shortcut.Save()",
    ))
    run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-Command", script,
    ])


def install_services() -> None:
    updater = INSTALL_DIRECTORY / "HosMonitorUpdaterService.exe"
    server = INSTALL_DIRECTORY / "HosMonitorServerService.exe"
    run([str(updater), "install"])
    run([str(server), "install"])
    run([str(updater), "start"])
    run([str(server), "start"])


def restore_program_backup(backup: Path | None, original_config: bytes | None) -> None:
    stop_old_system()
    config_path = DATA_DIRECTORY / "config.yaml"
    if original_config is None:
        config_path.unlink(missing_ok=True)
    else:
        temporary = config_path.with_suffix(".yaml.rollback")
        temporary.write_bytes(original_config)
        os.replace(temporary, config_path)
    if backup is None or not backup.is_dir():
        return
    if INSTALL_DIRECTORY.is_dir():
        shutil.rmtree(INSTALL_DIRECTORY)
    shutil.copytree(backup, INSTALL_DIRECTORY)
    updater = INSTALL_DIRECTORY / "HosMonitorUpdaterService.exe"
    server = INSTALL_DIRECTORY / "HosMonitorServerService.exe"
    if updater.is_file():
        run([str(updater), "install"], check=False)
        run([str(updater), "start"], check=False)
    if server.is_file():
        run([str(server), "install"], check=False)
        run([str(server), "start"], check=False)
    log(f"rollback completed: {backup}")


def wait_health(port: int, version: str) -> None:
    deadline = time.monotonic() + 60
    error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
                body = response.read().decode("utf-8")
            if '"status":"ok"' in body.replace(" ", "") and version in body:
                return
            error = body
        except Exception as exc:
            error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"Server ไม่ตอบ health check: {error}")


def install() -> tuple[str, int]:
    if not is_admin():
        raise RuntimeError("กรุณากด Yes ที่หน้าต่าง UAC เพื่ออนุญาตการติดตั้ง")
    version = bundled_path("VERSION").read_text(encoding="utf-8-sig").strip()
    existing_config_path = DATA_DIRECTORY / "config.yaml"
    original_config = existing_config_path.read_bytes() if existing_config_path.is_file() else None
    config_path = ensure_config()
    raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig")) or {}
    port = int(raw_config.get("server", {}).get("port", 6001))
    stop_old_system()
    backup = backup_program_files()
    try:
        copy_program_files(config_path)
        apply_acl()
        configure_firewall(port)
        install_services()
        wait_health(port, version)
        register_control(port)
        create_desktop_shortcuts(port)
    except Exception:
        try:
            restore_program_backup(backup, original_config)
        except Exception as rollback_error:
            log(f"rollback failed: {rollback_error}")
        raise
    launch_control(port)
    return version, port


def main() -> int:
    try:
        version, port = install()
        log(f"success version={version} port={port}")
        message(
            f"ติดตั้ง HosMonitor Server v{version} เรียบร้อยแล้ว\n\n"
            f"Dashboard: http://127.0.0.1:{port}\n"
            "หน้าควบคุมจะซ่อนไปที่ System Tray เมื่อกดกากบาท\n"
            "ระบบและหน้าควบคุมจะเริ่มอัตโนมัติพร้อม Windows"
        )
        return 0
    except Exception as exc:
        try:
            log(f"ERROR: {exc}")
        except Exception:
            pass
        message(f"ติดตั้ง HosMonitor Server ไม่สำเร็จ\n\n{exc}\n\nLog: {SETUP_LOG}", error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
