# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["server_setup.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("dist/HosMonitorServer.exe", "server-setup"),
        ("dist/HosMonitorUpdater.exe", "server-setup"),
        ("dist/HosMonitorServerControl.exe", "server-setup"),
        ("agent/WinSW-x64.exe", "server-setup"),
        ("deployment/HosMonitorServerService.xml.template", "server-setup"),
        ("deployment/HosMonitorUpdaterService.xml.template", "server-setup"),
        ("update_public.pem", "server-setup"),
        ("VERSION", "server-setup"),
        ("build/server-bootstrap.json", "server-setup"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["fastapi", "uvicorn", "starlette", "cryptography"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HosMonitorServerSetup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="assets/branding/hosmonitor.ico",
    uac_admin=True,
    disable_windowed_traceback=False,
)
