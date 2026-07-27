from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
BUILD_ROOT = PROJECT_ROOT / "build"
TESTS_ROOT = PROJECT_ROOT / "tests"
INSTALLER_ROOT = BUILD_ROOT / "installer"
RELEASE_ROOT = BUILD_ROOT / "release"
VERIFY_ROOT = RELEASE_ROOT  # Backward-compatible alias for release validators.
RESOURCES_ROOT = RUNTIME_ROOT / "resources"


def bundled_root() -> Path:
    """Return the PyInstaller bundle root or the source project root."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return PROJECT_ROOT


def resource_path(*parts: str) -> Path:
    """Resolve a bundled resource without trusting caller-provided absolute paths."""
    relative = Path(*parts)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Resource path must be relative and must not contain '..'")
    return bundled_root() / "runtime" / "resources" / relative
