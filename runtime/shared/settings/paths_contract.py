from __future__ import annotations

import os
import sys
from pathlib import Path

APP_FOLDER = "HerfyClient"
INSTALL_FOLDER = "Herfy Client"
APP_EXE = "HerfyClient.exe"
UPDATE_AGENT_EXE = "HerfyClientUpdateAgent.exe"


def roaming_root() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_FOLDER
        return Path.home() / "AppData" / "Roaming" / APP_FOLDER
    return Path.home() / ".config" / APP_FOLDER


def installed_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def installed_executable() -> Path:
    return installed_root() / APP_EXE


def update_agent_executable() -> Path:
    return installed_root() / UPDATE_AGENT_EXE


def assert_runtime_path_contract() -> None:
    root = roaming_root().resolve()
    install = installed_root().resolve()
    if root == install or root in install.parents or install in root.parents:
        raise RuntimeError(
            "Writable Roaming data must be separated from installation files"
        )
