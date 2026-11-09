from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_agent_uses_registry_and_filters_virtual_adapters():
    source = (ROOT / "agent" / "HosMonitorAgent.ps1").read_text(encoding="utf-8")
    assert "RegistryView" in source
    assert "Get-NetAdapter -Physical" in source
    assert "virtual|vpn|tap|tunnel|loopback" in source
    assert "last_boot_marker" in source
    assert "last_daily_date" in source
    assert "collect_requests" in source
    assert 'Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "VERSION"' in source
    assert "[math]::Max([int64]0, [int64]($ramTotal - $ramFree))" in source
    assert "[math]::Max(0, $ramTotal - $ramFree)" not in source
    forbidden = "Win32" + "_Product"
    assert forbidden not in source
    assert "ConvertTo-AgentString" in source
    assert "Invoke-InventoryCollector" in source
    assert "Test-FirstInventoryDue" in source
    assert "$firstInventoryDue -or $bootDue" in source
    assert "Select-Object -First 20000" in source
    assert "Select-Object -First 128" in source
    assert "Inventory sent successfully; disks=" in source


@pytest.mark.skipif(sys.platform != "win32", reason="Agent runs on Windows only")
def test_agent_powershell_self_test_passes():
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "agent" / "HosMonitorAgent.ps1"), "-SelfTest"],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "HosMonitor Agent self-test passed" in result.stdout


def test_agent_version_is_independent_from_server_version():
    server_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    agent_version = (ROOT / "AGENT_VERSION").read_text(encoding="utf-8").strip()
    assert server_version == "1.0.9"
    assert agent_version == "1.0.10"
    installer = (ROOT / "scripts" / "Build-AgentInstaller.ps1").read_text(encoding="utf-8")
    release = (ROOT / "scripts" / "Build-AgentRelease.ps1").read_text(encoding="utf-8")
    release_tools = (ROOT / "scripts" / "release_tools.py").read_text(encoding="utf-8")
    assert "Get-Content -LiteralPath AGENT_VERSION" in installer
    assert "Get-Content -LiteralPath AGENT_VERSION" in release
    assert 'project / "AGENT_VERSION"' in release_tools
    assert '"VERSION": project / "AGENT_VERSION"' in release_tools


def test_service_runs_as_local_service():
    xml = (ROOT / "agent" / "HosMonitorAgentService.xml.template").read_text(encoding="utf-8")
    assert "LocalService" in xml
    assert "delayedAutoStart" in xml
    assert "<logpath>{{LOG_PATH}}</logpath>" in xml


def test_one_click_agent_installer_preserves_identity_and_supports_upgrade():
    installer = (ROOT / "agent_setup.py").read_text(encoding="utf-8")
    build_script = (ROOT / "scripts" / "Build-AgentInstaller.ps1").read_text(encoding="utf-8")
    spec = (ROOT / "HosMonitorAgentSetup.spec").read_text(encoding="utf-8")
    assert "uac_admin=True" in spec
    assert "bootstrap-config.json" in spec
    assert "agent-config.json" in installer
    assert "agent-state.json" not in installer
    assert "agent-backups" in installer
    assert "restore_backup" in installer
    assert "restore_config(original_config)" in installer
    assert "ServerUrl" in build_script
    assert "AgentToken" in build_script
    assert "production-config.yaml" in build_script
    assert "Remove-Item -LiteralPath \"build\\bootstrap-config.json\"" in build_script
    assert "HosMonitorWallpaper.ps1" in spec
    assert "register_wallpaper_helper" in installer
    assert "HosMonitorAgentUpdater.exe" in spec
    assert "update_public.pem" in spec
    assert "HosMonitorAgentUpdater" in installer
    assert 'SERVICE_LOG_DIRECTORY = DATA_DIRECTORY / "service-logs"' in installer
    assert 'replace("{{LOG_PATH}}", escape(str(SERVICE_LOG_DIRECTORY)))' in installer
    assert '"HosMonitorAgent.exe"' in installer
    assert '"HosMonitorAgentUpdater.exe"' in installer
    assert '"HosMonitorAgentService.exe"' in installer
    assert '"HosMonitorAgentUpdaterService.exe"' in installer
    assert "HosMonitorAgent.ps1" in installer
    assert "copy_with_retry" in installer


def test_signed_agent_updater_has_fixed_allowlist_and_no_command_execution():
    updater = (ROOT / "agent_updater.py").read_text(encoding="utf-8")
    agent = (ROOT / "agent" / "HosMonitorAgent.ps1").read_text(encoding="utf-8")
    updater_xml = (ROOT / "agent" / "HosMonitorAgentUpdaterService.xml.template").read_text(encoding="utf-8")
    assert 'ALLOWED_FILES = {"HosMonitorAgent.ps1", "HosMonitorWallpaper.ps1", "VERSION"}' in updater
    assert "PKCS1v15" in updater
    assert "update_public.pem" in updater
    assert "LocalSystem" in updater_xml
    assert "<serviceaccount>" not in updater_xml
    assert 'Join-Path $updateDirectory "pending.json"' in agent
    assert "Get-FileHash" in agent
    assert "Invoke-Expression" not in updater
    assert "shell=True" not in updater


def test_wallpaper_collector_is_narrow_and_hash_verified():
    agent = (ROOT / "agent" / "HosMonitorAgent.ps1").read_text(encoding="utf-8")
    helper = (ROOT / "agent" / "HosMonitorWallpaper.ps1").read_text(encoding="utf-8")
    assert "Get-FileHash" in agent
    assert "wallpaper.download" in agent
    assert "NoChangingWallPaper" in helper
    assert "SystemParametersInfo" in helper
    assert "Invoke-Expression" not in agent
    assert "Invoke-Expression" not in helper


def test_no_activation_or_remote_command_surface():
    files = list((ROOT / "server").rglob("*.py")) + list((ROOT / "agent").glob("*.ps1"))
    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in files)
    forbidden = ["/acti" + "vate", "remote" + "_shell", "command" + "_execution"]
    for marker in forbidden:
        assert marker not in combined


def test_server_deployment_uses_separate_signed_updater_service():
    installer = (ROOT / "deployment" / "Install-HosMonitorServer.ps1").read_text(encoding="utf-8")
    updater_xml = (ROOT / "deployment" / "HosMonitorUpdaterService.xml.template").read_text(encoding="utf-8")
    release_tool = (ROOT / "scripts" / "release_tools.py").read_text(encoding="utf-8")
    assert "HosMonitorUpdater" in installer
    assert "<serviceaccount>" not in updater_xml
    assert "HosMonitor Updater" in updater_xml
    assert "PKCS1v15" in release_tool
    assert "private_key" in release_tool
    assert "license" not in release_tool.lower()
    server_sources = "\n".join(path.read_text(encoding="utf-8").lower() for path in (ROOT / "server").glob("*.py"))
    assert "urllib.request" not in server_sources
    assert "api.github.com" not in server_sources


def test_one_click_server_installer_stops_old_system_and_starts_services():
    setup = (ROOT / "server_setup.py").read_text(encoding="utf-8")
    setup_spec = (ROOT / "HosMonitorServerSetup.spec").read_text(encoding="utf-8")
    server_xml = (ROOT / "deployment" / "HosMonitorServerService.xml.template").read_text(encoding="utf-8")
    updater_xml = (ROOT / "deployment" / "HosMonitorUpdaterService.xml.template").read_text(encoding="utf-8")
    assert "stop_old_system" in setup
    assert "backup_program_files" in setup
    assert "configure_firewall" in setup
    assert 'PRIVATE_NETWORKS = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"' in setup
    assert 'f"remoteip={PRIVATE_NETWORKS}"' in setup
    assert '"remoteip=any"' not in setup.lower()
    assert "wait_health" in setup
    assert "uac_admin=True" in setup_spec
    assert "console=False" in setup_spec
    assert "server-bootstrap.json" in setup_spec
    assert "deployment_agent_token" in setup
    assert "original_config" in setup
    assert "yaml.rollback" in setup
    assert "HosMonitorServerControl.exe" in setup_spec
    assert "register_control" in setup
    assert "create_desktop_shortcuts" in setup
    assert "HosMonitor Server Control.lnk" in setup
    assert "HosMonitor Dashboard.url" in setup
    assert "--tray" in setup
    assert "<startmode>Automatic</startmode>" in server_xml
    assert "<startmode>Automatic</startmode>" in updater_xml
    assert "<logpath>{{LOG_PATH}}</logpath>" in server_xml
    assert "<logpath>{{LOG_PATH}}</logpath>" in updater_xml
    assert 'LOG_DIRECTORY = DATA_DIRECTORY / "logs"' in setup
    assert 'replace("{{LOG_PATH}}", escape(str(LOG_DIRECTORY)))' in setup


def test_server_control_uses_tray_and_fixed_service_actions():
    control = (ROOT / "server_control.py").read_text(encoding="utf-8")
    spec = (ROOT / "HosMonitorServerControl.spec").read_text(encoding="utf-8")
    assert "pystray" in control
    assert "WM_DELETE_WINDOW" in control
    assert "self.root.withdraw()" in control
    assert "หยุดและปิดระบบ" in control
    assert 'SERVER_SERVICE = "HosMonitorServer"' in control
    assert 'UPDATER_SERVICE = "HosMonitorUpdater"' in control
    assert 'ShellExecuteW(None, "runas"' in control
    assert "uac_admin=False" in spec
    assert "shell=True" not in control
    assert "--self-test" in control
    assert "เปิดหน้าเว็บ Dashboard" in control
    assert "buttons.pack(side=BOTTOM, fill=X)" in control


def test_asset_lifecycle_ui_and_live_search_are_present():
    html = (ROOT / "server" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "server" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="filterLifecycle"' in html
    assert 'type="submit">ค้นหา</button>' not in html
    assert '$("filterSearch").addEventListener("input"' in javascript
    assert "setTimeout(()=>{state.page=1;loadAssets();},300)" in javascript
    assert 'id="retireAssetForm"' in javascript
    assert 'id="deleteAdminPassword" type="password"' in javascript
    assert 'method:"DELETE"' in javascript


def test_agent_version_is_visible_in_inventory_and_rollout_help():
    html = (ROOT / "server" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "server" / "static" / "app.js").read_text(encoding="utf-8")
    assert "<th>Agent</th>" in html
    assert "เครื่องที่มีเวอร์ชันตรงกับรุ่นเป้าหมายแล้ว" in html
    assert "item.agent_version" in javascript
    assert "<span>Agent Version</span>" in javascript


def test_hardware_identity_and_approved_admin_ui_are_present():
    agent = (ROOT / "agent" / "HosMonitorAgent.ps1").read_text(encoding="utf-8")
    html = (ROOT / "server" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "server" / "static" / "app.js").read_text(encoding="utf-8")
    for cim_class in ("Win32_ComputerSystem", "Win32_BIOS", "Win32_ComputerSystemProduct", "Win32_BaseBoard"):
        assert cim_class in agent
    for field in (
        "manufacturer", "model", "bios_serial", "system_uuid",
        "baseboard_manufacturer", "baseboard_product", "baseboard_serial",
    ):
        assert field in agent
    assert 'id="wallpaperExclusionSearch"' in html
    assert 'id="wallpaperExclusionList"' in html
    assert '$("wallpaperExclusionSearch").addEventListener("input"' in javascript
    assert "setTimeout(()=>loadWallpaperExclusions(),300)" in javascript
    assert "department-edit" in javascript
    assert "/name" in javascript


def test_branding_assets_and_executable_icons_are_wired():
    html = (ROOT / "server" / "static" / "index.html").read_text(encoding="utf-8")
    control = (ROOT / "server_control.py").read_text(encoding="utf-8")
    master_path = ROOT / "assets" / "branding" / "hosmonitor-logo-master.png"
    icon_path = ROOT / "assets" / "branding" / "hosmonitor.ico"
    with Image.open(master_path) as master:
        assert master.mode == "RGBA"
        assert master.size == (1024, 1024)
        assert master.getchannel("A").getextrema() == (0, 255)
    with Image.open(icon_path) as icon:
        assert icon.format == "ICO"
        assert icon.size == (256, 256)
    assert "/static/assets/hosmonitor-logo-512.png" in html
    assert "/static/favicon.ico" in html
    assert "resource_path" in control
    assert "hosmonitor-logo-512.png" in control
    assert "#18a85b" in control and "#cf3b32" in control
    for spec_name in (
        "HosMonitorServer.spec", "HosMonitorUpdater.spec", "HosMonitorServerControl.spec",
        "HosMonitorServerSetup.spec", "HosMonitorAgentUpdater.spec", "HosMonitorAgentSetup.spec",
    ):
        spec = (ROOT / spec_name).read_text(encoding="utf-8")
        assert 'icon="assets/branding/hosmonitor.ico"' in spec
