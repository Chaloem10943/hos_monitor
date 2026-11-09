from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import BOTH, BOTTOM, LEFT, RIGHT, X, Button, Frame, Label, StringVar, Tk, messagebox

import pystray
import yaml
from PIL import Image, ImageDraw


INSTALL_DIRECTORY = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "HosMonitor Server"
DATA_DIRECTORY = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "HosMonitorServer"
CONFIG_PATH = DATA_DIRECTORY / "config.yaml"
SERVER_SERVICE = "HosMonitorServer"
UPDATER_SERVICE = "HosMonitorUpdater"
MUTEX_NAME = "Local\\HosMonitorServerControlMutex"
SHOW_EVENT_NAME = "Local\\HosMonitorServerControlShow"
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
EVENT_ALL_ACCESS = 0x1F0003


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def hidden_run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, check=False, timeout=timeout, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def service_state(name: str) -> str:
    result = hidden_run(["sc.exe", "query", name])
    if result.returncode != 0:
        return "NOT INSTALLED"
    match = re.search(r"STATE\s*:\s*(\d+)\s+([A-Z_]+)", result.stdout.upper())
    if match:
        return {1: "STOPPED", 2: "STARTING", 3: "STOPPING", 4: "RUNNING"}.get(int(match.group(1)), match.group(2))
    if "RUNNING" in result.stdout.upper():
        return "RUNNING"
    if "STOPPED" in result.stdout.upper():
        return "STOPPED"
    return "UNKNOWN"


def wait_service(name: str, expected: str, timeout: int = 25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service_state(name) == expected:
            return True
        time.sleep(1)
    return False


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def stop_system() -> bool:
    if not is_admin():
        return False
    hidden_run(["sc.exe", "stop", SERVER_SERVICE])
    wait_service(SERVER_SERVICE, "STOPPED")
    hidden_run(["sc.exe", "stop", UPDATER_SERVICE])
    return wait_service(UPDATER_SERVICE, "STOPPED") and service_state(SERVER_SERVICE) == "STOPPED"


def start_system() -> bool:
    if not is_admin():
        return False
    hidden_run(["sc.exe", "start", UPDATER_SERVICE])
    wait_service(UPDATER_SERVICE, "RUNNING")
    hidden_run(["sc.exe", "start", SERVER_SERVICE])
    return wait_service(SERVER_SERVICE, "RUNNING") and service_state(UPDATER_SERVICE) == "RUNNING"


def request_elevated(argument: str) -> bool:
    ctypes.windll.shell32.ShellExecuteW.restype = ctypes.c_void_p
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, argument, None, 0)
    return bool(result) and int(result) > 32


def load_port() -> int:
    try:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig")) or {}
        return int(raw.get("server", {}).get("port", 6001))
    except Exception:
        return 6001


def local_ipv4() -> str:
    addresses: list[str] = []
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            value = item[4][0]
            if value.startswith(("127.", "169.254.")) or value in addresses:
                continue
            addresses.append(value)
    except OSError:
        pass
    private = [value for value in addresses if value.startswith("10.") or value.startswith("192.168.") or value.startswith("172.")]
    return (private or addresses or ["-"])[0]


def server_status(port: int) -> dict[str, object]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/control/v1/status", timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return {"status": "offline", "version": "-", "agents_online": 0, "agents_registered": 0}


def tray_image(online: bool = True) -> Image.Image:
    logo = resource_path("assets/branding/hosmonitor-logo-512.png")
    if logo.is_file():
        with Image.open(logo) as source:
            image = source.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
    else:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        fallback = ImageDraw.Draw(image)
        fallback.rounded_rectangle((7, 12, 57, 48), radius=8, outline="#0b7285", width=6)
        fallback.line((13, 31, 25, 31, 30, 21, 38, 41, 44, 31, 51, 31), fill="#0ea5a8", width=5)
    draw = ImageDraw.Draw(image)
    draw.ellipse((43, 43, 61, 61), fill="#18a85b" if online else "#cf3b32", outline="white", width=2)
    return image


class ControlApp:
    def __init__(self, *, start_hidden: bool = False, port: int | None = None):
        self.port = port or load_port()
        self.dashboard = f"http://127.0.0.1:{self.port}"
        self.actions: queue.Queue[str] = queue.Queue()
        self.root = Tk()
        self.root.title("HosMonitor Server Control")
        try:
            self.root.iconbitmap(default=str(resource_path("assets/branding/hosmonitor.ico")))
        except Exception:
            pass
        self.root.geometry("700x580")
        self.root.minsize(640, 520)
        self.root.configure(bg="#081923")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.values = {name: StringVar(value="กำลังตรวจสอบ...") for name in (
            "overall", "server", "updater", "version", "listen", "lan", "agents", "checked",
        )}
        self._build_ui()
        self.icon = pystray.Icon(
            "HosMonitorServerControl", tray_image(False), "HosMonitor Server",
            menu=pystray.Menu(
                pystray.MenuItem("เปิดหน้าควบคุม", lambda *_: self.actions.put("show"), default=True),
                pystray.MenuItem("เปิด Dashboard", lambda *_: self.actions.put("dashboard")),
                pystray.MenuItem("อัปเดตจาก GitHub", lambda *_: self.actions.put("update_github")),
                pystray.MenuItem("เริ่มระบบ", lambda *_: self.actions.put("start")),
                pystray.MenuItem("หยุดและปิดระบบ", lambda *_: self.actions.put("stop_exit")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("ปิดหน้าควบคุม (ระบบทำงานต่อ)", lambda *_: self.actions.put("exit_control")),
            ),
        )
        threading.Thread(target=self.icon.run, daemon=True).start()
        if start_hidden:
            self.root.withdraw()
        self.root.after(100, self._poll_actions)
        self.refresh()
        self.root.after(5000, self._periodic_refresh)

    def _build_ui(self) -> None:
        header = Frame(self.root, bg="#0b4158", padx=24, pady=20)
        header.pack(fill=X)
        Label(header, text="HOSMONITOR SERVER CONTROL", fg="#7fe5ef", bg="#0b4158", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        Label(header, textvariable=self.values["overall"], fg="white", bg="#0b4158", font=("Segoe UI", 23, "bold")).pack(anchor="w", pady=(4, 0))
        Label(header, text="กดกากบาทเพื่อซ่อนไปที่ System Tray — ระบบจะทำงานต่อ", fg="#c3d9e0", bg="#0b4158", font=("Segoe UI", 10)).pack(anchor="w", pady=(5, 0))

        body = Frame(self.root, bg="#081923", padx=24, pady=14)
        body.pack(fill=BOTH, expand=True)

        # Pack the action bar first and pin it to the bottom. This keeps every
        # button visible when Windows display scaling reduces the client area.
        buttons = Frame(body, bg="#081923", pady=12)
        buttons.pack(side=BOTTOM, fill=X)
        Button(
            buttons, text="เปิดหน้าเว็บ Dashboard", command=lambda: webbrowser.open(self.dashboard),
            bg="#16879b", fg="white", activebackground="#20a0b6", activeforeground="white",
            relief="flat", padx=18, pady=9, font=("Segoe UI", 10, "bold"),
        ).pack(side=LEFT, padx=(0, 8))
        Button(buttons, text="รีเฟรช", command=self.refresh, bg="#314d59", fg="white", relief="flat", padx=14, pady=9).pack(side=LEFT, padx=(0, 8))
        Button(buttons, text="อัปเดตจาก GitHub", command=self.update_from_github, bg="#0d6efd", fg="white", relief="flat", padx=14, pady=9).pack(side=LEFT, padx=(0, 8))
        Button(buttons, text="เริ่มระบบ", command=self.start_requested, bg="#198754", fg="white", relief="flat", padx=14, pady=9).pack(side=LEFT, padx=(0, 8))
        Button(buttons, text="หยุดระบบ", command=self.stop_requested, bg="#c4332b", fg="white", relief="flat", padx=14, pady=9).pack(side=RIGHT)

        status_rows = Frame(body, bg="#081923")
        status_rows.pack(fill=BOTH, expand=True)
        rows = [
            ("Server service", "server"), ("Updater service", "updater"), ("Version", "version"),
            ("Listen", "listen"), ("Dashboard (LAN)", "lan"), ("Agent", "agents"), ("ตรวจล่าสุด", "checked"),
        ]
        for label, key in rows:
            row = Frame(status_rows, bg="#102936", padx=16, pady=7)
            row.pack(fill=X, pady=3)
            Label(row, text=label, width=20, anchor="w", fg="#9cb7c2", bg="#102936", font=("Segoe UI", 10)).pack(side=LEFT)
            Label(row, textvariable=self.values[key], anchor="w", fg="white", bg="#102936", font=("Consolas", 11, "bold")).pack(side=LEFT, fill=X, expand=True)

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.refresh()

    def hide_window(self) -> None:
        self.root.withdraw()

    def start_requested(self) -> None:
        if not request_elevated("--start-system"):
            messagebox.showerror("HosMonitor", "ไม่ได้รับสิทธิ์ Administrator")
            return
        self.values["overall"].set("กำลังเริ่มระบบ...")
        self.root.after(3000, self.refresh)

    def stop_requested(self) -> None:
        if not messagebox.askyesno("หยุดระบบ", "ต้องการหยุด Server และ Updater หรือไม่?\nAgent และ Dashboard จะเชื่อมต่อไม่ได้จนกว่าจะเริ่มระบบอีกครั้ง"):
            return
        if not request_elevated("--stop-system"):
            messagebox.showerror("HosMonitor", "ไม่ได้รับสิทธิ์ Administrator")
            return
        self.values["overall"].set("กำลังหยุดระบบ...")
        self.root.after(3000, self.refresh)

    def stop_and_exit(self) -> None:
        if not messagebox.askyesno("หยุดและปิดระบบ", "ยืนยันหยุด Server/Updater และปิดหน้าควบคุมหรือไม่?"):
            return
        if not request_elevated("--stop-system"):
            messagebox.showerror("HosMonitor", "ไม่ได้รับสิทธิ์ Administrator")
            return
        self.root.after(2000, self._wait_stop_and_exit)

    def _wait_stop_and_exit(self, attempts: int = 0) -> None:
        if service_state(SERVER_SERVICE) == "STOPPED" and service_state(UPDATER_SERVICE) == "STOPPED":
            self.exit_control()
            return
        if attempts >= 15:
            messagebox.showerror("HosMonitor", "หยุดระบบไม่สำเร็จ กรุณาตรวจสอบ Windows Services")
            return
        self.root.after(1000, lambda: self._wait_stop_and_exit(attempts + 1))

    def exit_control(self) -> None:
        try:
            self.icon.stop()
        finally:
            self.root.destroy()

    def refresh(self) -> None:
        server = service_state(SERVER_SERVICE)
        updater = service_state(UPDATER_SERVICE)
        status = server_status(self.port)
        online = server == "RUNNING" and str(status.get("status")) == "ok"
        self.values["overall"].set("ระบบออนไลน์" if online else "ระบบหยุดทำงาน / ติดต่อไม่ได้")
        self.values["server"].set(server)
        self.values["updater"].set(updater)
        self.values["version"].set(str(status.get("version", "-")))
        self.values["listen"].set(f"0.0.0.0:{self.port}")
        self.values["lan"].set(f"http://{local_ipv4()}:{self.port}")
        self.values["agents"].set(f"online {status.get('agents_online', 0)} / registered {status.get('agents_registered', 0)}")
        self.values["checked"].set(time.strftime("%Y-%m-%d %H:%M:%S"))
        self.icon.icon = tray_image(online)
        self.icon.title = "HosMonitor Server — " + ("ONLINE" if online else "OFFLINE")

    def _periodic_refresh(self) -> None:
        self.refresh()
        self.root.after(5000, self._periodic_refresh)

    def _poll_actions(self) -> None:
        try:
            while True:
                action = self.actions.get_nowait()
                if action == "show": self.show_window()
                elif action == "dashboard": webbrowser.open(self.dashboard)
                elif action == "update_github": self.update_from_github()
                elif action == "start": self.start_requested()
                elif action == "stop_exit": self.stop_and_exit()
                elif action == "exit_control": self.exit_control(); return
        except queue.Empty:
            pass
        self.root.after(150, self._poll_actions)

    def update_from_github(self) -> None:
        self.values["overall"].set("กำลังตรวจสอบการอัปเดตจาก GitHub...")
        threading.Thread(target=self._run_github_update, daemon=True).start()

    def _run_github_update(self) -> None:
        try:
            repo = "Chaloem10943/hos_monitor"
            url = f"https://api.github.com/repos/{repo}/releases/latest"
            req = urllib.request.Request(url, headers={"User-Agent": "HosMonitorServerControl"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            tag_name = data.get("tag_name", "").lstrip("v").strip()
            if not tag_name:
                self.root.after(0, lambda: messagebox.showerror("HosMonitor Update", "ไม่พบข้อมูลเวอร์ชันใน GitHub Release"))
                self.root.after(0, self.refresh)
                return

            def parse_ver(v: str) -> tuple[int, ...]:
                nums = re.findall(r"\d+", v)
                return tuple(int(x) for x in nums) if nums else (0, 0, 0)

            stat = server_status(self.port)
            current_ver_str = str(stat.get("version", "-"))
            if current_ver_str == "-" or not current_ver_str:
                ver_file = INSTALL_DIRECTORY / "VERSION"
                if ver_file.is_file():
                    current_ver_str = ver_file.read_text(encoding="utf-8").strip()
                else:
                    alt_ver = resource_path("VERSION")
                    if alt_ver.is_file():
                        current_ver_str = alt_ver.read_text(encoding="utf-8").strip()
                    else:
                        current_ver_str = "0.0.0"

            current_ver = parse_ver(current_ver_str)
            latest_ver = parse_ver(tag_name)

            if latest_ver <= current_ver:
                self.root.after(0, lambda: messagebox.showinfo(
                    "HosMonitor Update",
                    f"ระบบ HosMonitor เป็นเวอร์ชันล่าสุดแล้ว\n\n"
                    f"เวอร์ชันปัจจุบัน: {current_ver_str}\n"
                    f"เวอร์ชันบน GitHub: {tag_name}",
                ))
                self.root.after(0, self.refresh)
                return

            proceed = messagebox.askyesno(
                "HosMonitor Update",
                f"พบ HosMonitor เวอร์ชันใหม่: v{tag_name}\n"
                f"(เวอร์ชันปัจจุบัน: {current_ver_str})\n\n"
                f"คุณต้องการดาวน์โหลดและติดตั้งอัปเดตทันทีหรือไม่?\n"
                f"(บริการ HosMonitorUpdater จะสำรองข้อมูลและดำเนินการให้อัตโนมัติ)",
            )
            if not proceed:
                self.root.after(0, self.refresh)
                return

            assets = data.get("assets", [])
            bundle_asset = None
            for item in assets:
                name = item.get("name", "")
                if name.endswith(".hmrelease"):
                    bundle_asset = item
                    break

            if not bundle_asset:
                self.root.after(0, lambda: messagebox.showerror(
                    "HosMonitor Update",
                    f"ไม่พบไฟล์แพ็กเกจ (.hmrelease) ใน Release v{tag_name}",
                ))
                self.root.after(0, self.refresh)
                return

            asset_name = bundle_asset["name"]
            download_url = bundle_asset.get("browser_download_url") or bundle_asset.get("url")
            self.root.after(0, lambda: self.values["overall"].set(f"กำลังดาวน์โหลด {asset_name}..."))

            download_dir = DATA_DIRECTORY / "updates" / "downloads"
            download_dir.mkdir(parents=True, exist_ok=True)
            local_bundle_path = download_dir / asset_name

            download_req = urllib.request.Request(download_url, headers={"User-Agent": "HosMonitorServerControl"})
            with urllib.request.urlopen(download_req, timeout=120) as resp:
                raw_bundle = resp.read()

            local_bundle_path.write_bytes(raw_bundle)

            self.root.after(0, lambda: self.values["overall"].set("กำลังจัดเตรียมการอัปเดตระบบ..."))
            from server.config import load_config, save_update_config
            from server.updater import stage_release_bundle

            config_file = CONFIG_PATH if CONFIG_PATH.is_file() else (resource_path("config.yaml") if resource_path("config.yaml").is_file() else None)
            if not config_file:
                raise RuntimeError(f"ไม่พบไฟล์คอนฟิก {CONFIG_PATH}")

            app_config = load_config(config_file)
            if not app_config.update_enabled:
                app_config = save_update_config(app_config, enabled=True, backup_retention=app_config.update_backup_retention)

            result = stage_release_bundle(app_config, raw_bundle, "HosMonitorServerControl")

            self.root.after(0, lambda: messagebox.showinfo(
                "HosMonitor Update",
                f"ดาวน์โหลดและจัดเตรียมอัปเดต v{tag_name} สำเร็จแล้ว!\n\n"
                f"ผลลัพธ์: {result.get('message', 'เรียบร้อย')}\n\n"
                f"บริการ HosMonitorUpdater กำลังดำเนินการ:\n"
                f"1. สำรองข้อมูลฐานข้อมูลและไฟล์ระบบ\n"
                f"2. สลับเป็นเวอร์ชันใหม่ v{tag_name}\n"
                f"3. เริ่มการทำงานของ Server อัตโนมัติ",
            ))
            self.root.after(5000, self.refresh)
        except urllib.error.URLError as e:
            self.root.after(0, lambda: messagebox.showerror("HosMonitor Update", f"เชื่อมต่อ GitHub ไม่สำเร็จ: {e.reason}"))
            self.root.after(0, self.refresh)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("HosMonitor Update", f"เกิดข้อผิดพลาดในการอัปเดต: {e}"))
            self.root.after(0, self.refresh)

    def run(self) -> None:
        self.root.mainloop()


def acquire_single_instance() -> tuple[int, int] | None:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateEventW.restype = ctypes.c_void_p
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not mutex:
        return None
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        event = kernel32.OpenEventW(EVENT_ALL_ACCESS, False, SHOW_EVENT_NAME)
        if event:
            kernel32.SetEvent(event)
            kernel32.CloseHandle(event)
        kernel32.CloseHandle(mutex)
        return None
    event = kernel32.CreateEventW(None, True, False, SHOW_EVENT_NAME)
    return int(mutex), int(event)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--start-system", action="store_true")
    parser.add_argument("--stop-system", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--self-test", action="store_true")
    args, _ = parser.parse_known_args()
    if args.self_test:
        tray_image(True)
        service_state("DefinitelyMissingHosMonitorService")
        return 0
    if args.start_system:
        return 0 if start_system() else 1
    if args.stop_system:
        return 0 if stop_system() else 1
    handles = acquire_single_instance()
    if handles is None:
        return 0
    app = ControlApp(start_hidden=args.tray, port=args.port or None)
    event = handles[1]

    def poll_show_event() -> None:
        if ctypes.windll.kernel32.WaitForSingleObject(event, 0) == WAIT_OBJECT_0:
            ctypes.windll.kernel32.ResetEvent(event)
            app.show_window()
        app.root.after(250, poll_show_event)

    app.root.after(250, poll_show_event)
    try:
        app.run()
    finally:
        ctypes.windll.kernel32.CloseHandle(handles[1])
        ctypes.windll.kernel32.CloseHandle(handles[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
