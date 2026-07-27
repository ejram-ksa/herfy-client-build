from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


config = read("runtime/shared/settings/config.py")
logging_setup = read("runtime/shared/settings/logging_setup.py")
updater = read("runtime/bootstrap/runtime/update_agent.py")
installer = read("build/installer/HerfyClient_Custom_Installer.iss")
updates = read("runtime/application/services/updates/service.py")
migration = read("runtime/shared/settings/runtime_migration.py")
version_data = json.loads(read("version.json"))
guard = read("build/installer/pyinstaller/runtime_path_guard.py")

require('os.environ.get("APPDATA")' in config, "Roaming APPDATA is not canonical")
require("LOCALAPPDATA" not in logging_setup, "LOCALAPPDATA path drift remains in logging")
require("migrate_previous_localappdata(target)" in config, "Roaming migration is not called")
require('os.environ.get("LOCALAPPDATA")' in migration, "Previous LOCALAPPDATA migration source is missing")
require(version_data.get("updates_base_url") == "https://herfy.online", "Static update host is not canonical")
require("_assert_no_source_shadowing" in guard, "Frozen source-shadow guard is missing")
require("DefaultDirName={autopf}\\Herfy Client" in installer, "Installer path is not canonical")
require("UsePreviousAppDir=yes" in installer, "Installer does not preserve the existing path")
require("AppMutex=Herfy.HerfyClient" in installer, "Installer/app mutex is missing")
require("expected_restart = (root / APP_EXE_NAME).resolve()" in updater, "Updater restart target is not canonical")
require("Restart target must be the existing HerfyClient.exe" in updater, "Updater permits path drift")
require('"/RESTARTAPPLICATIONS"' in updates, "Installer update does not request restart")

for py in ROOT.rglob("*.py"):
    if any(part in {".venv", "venv", "dist", "output", "publish"} for part in py.parts):
        continue
    ast.parse(py.read_text(encoding="utf-8"), filename=str(py))

print("HERFY_CANONICAL_PATHS_UPDATE_OK")
