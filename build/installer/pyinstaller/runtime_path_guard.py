from __future__ import annotations

import sys
from pathlib import Path

_FORBIDDEN_SOURCE_DIRS = {
    "app",
    "application",
    "bootstrap",
    "core",
    "data",
    "domain",
    "presentation",
    "remote",
    "services",
    "settings",
    "ui",
}
_ALLOWED_ROOT_PYTHON_FILES: set[str] = set()


def _normalized(path: str) -> Path | None:
    try:
        return Path(path or ".").resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _assert_no_source_shadowing(executable_root: Path) -> None:
    violations: list[str] = []
    for name in sorted(_FORBIDDEN_SOURCE_DIRS):
        candidate = executable_root / name
        if candidate.exists():
            violations.append(name)
    for candidate in executable_root.glob("*.py"):
        if candidate.name not in _ALLOWED_ROOT_PYTHON_FILES:
            violations.append(candidate.name)
    if violations:
        raise RuntimeError(
            "Unsafe Python source files exist beside the frozen executable: "
            + ", ".join(sorted(set(violations)))
        )


if getattr(sys, "frozen", False):
    executable_root = Path(sys.executable).resolve().parent
    _assert_no_source_shadowing(executable_root)

    bundle_root = _normalized(str(getattr(sys, "_MEIPASS", "")))
    filtered: list[str] = []
    for entry in sys.path:
        resolved = _normalized(entry)
        if (
            resolved == executable_root
            and bundle_root is not None
            and resolved != bundle_root
        ):
            continue
        filtered.append(entry)
    sys.path[:] = filtered
