# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["run_server.py"],
    pathex=["."],
    binaries=[],
    datas=[("server/static", "server/static")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HosMonitorServer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon="assets/branding/hosmonitor.ico",
    disable_windowed_traceback=False,
)
