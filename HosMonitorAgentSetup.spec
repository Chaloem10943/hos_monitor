# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["agent_setup.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("agent/HosMonitorAgent.ps1", "agent"),
        ("agent/HosMonitorWallpaper.ps1", "agent"),
        ("agent/HosMonitorAgentService.xml.template", "agent"),
        ("agent/HosMonitorAgentUpdaterService.xml.template", "agent"),
        ("agent/WinSW-x64.exe", "agent"),
        ("dist/HosMonitorAgentUpdater.exe", "agent"),
        ("update_public.pem", "agent"),
        ("build/bootstrap-config.json", "agent"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["fastapi", "uvicorn", "starlette", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HosMonitorAgentSetup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="assets/branding/hosmonitor.ico",
    disable_windowed_traceback=True,
    uac_admin=True,
)
