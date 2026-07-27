# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if not (ROOT / "main.py").is_file():
    raise SystemExit(f"Missing application entry point: {ROOT / 'main.py'}")

LOCAL_PACKAGES = (
    "runtime",
)

hiddenimports = []
for package in LOCAL_PACKAGES:
    hiddenimports.extend(collect_submodules(package))

hiddenimports.extend(
    [
        "PyQt5.QtCore",
        "PyQt5.QtGui",
        "PyQt5.QtWidgets",
        "PyQt5.QtMultimedia",
        "PyQt5.QtNetwork",
        "PyQt5.QtPrintSupport",
    ]
)

datas = [
    (str(ROOT / "runtime" / "resources"), "runtime/resources"),
    (str(ROOT / "version.json"), "."),
]

VERSION_INFO_FILE = os.environ.get("HERFY_PYINSTALLER_VERSION_FILE", "").strip()
if VERSION_INFO_FILE and not Path(VERSION_INFO_FILE).is_file():
    raise SystemExit(f"Missing PyInstaller version resource: {VERSION_INFO_FILE}")

block_cipher = None

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "build" / "installer" / "pyinstaller" / "runtime_path_guard.py")],
    excludes=["pytest", "unittest", "tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HerfyClient",
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
    contents_directory=".",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HerfyClient",
)
