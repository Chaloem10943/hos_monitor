# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["server_control.py"], pathex=["."], binaries=[], datas=[
        ("assets/branding/hosmonitor-logo-512.png", "assets/branding"),
        ("assets/branding/hosmonitor.ico", "assets/branding"),
    ], hiddenimports=["pystray._win32"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["fastapi", "uvicorn", "starlette", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name="HosMonitorServerControl",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=False, disable_windowed_traceback=True, uac_admin=False,
    icon="assets/branding/hosmonitor.ico",
)
