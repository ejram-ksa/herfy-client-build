# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os

ROOT = Path(SPECPATH).resolve().parents[2]
if not (ROOT / "runtime" / "bootstrap" / "runtime" / "update_agent.py").is_file():
    raise SystemExit(f"Missing updater entry point: {ROOT / 'runtime/bootstrap/runtime/update_agent.py'}")

VERSION_INFO_FILE = os.environ.get("HERFY_PYINSTALLER_VERSION_FILE", "").strip()
if VERSION_INFO_FILE and not Path(VERSION_INFO_FILE).is_file():
    raise SystemExit(f"Missing PyInstaller version resource: {VERSION_INFO_FILE}")

block_cipher = None

a = Analysis(
    [str(ROOT / "runtime" / "bootstrap" / "runtime" / "update_agent.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "openpyxl", "xlrd", "pytest", "unittest", "tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HerfyClientUpdateAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "runtime" / "resources" / "images" / "app_icon.ico"),
    version=VERSION_INFO_FILE or None,
)
