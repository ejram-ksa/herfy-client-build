from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_FOLDER = "HerfyClient"
MIGRATION_MARKER = ".roaming_migration_v1"
PREVIOUS_SETTINGS_FILENAMES = ("runtime.shared.settings.ini",)
CANONICAL_SETTINGS_FILENAME = "settings.ini"
_SKIP_TOP_LEVEL = {
    "__pycache__",
    "cache",
    "logs",
    "updates",
}


def _copy_missing_tree(source: Path, target: Path) -> None:
    for child in source.iterdir():
        if child.name in _SKIP_TOP_LEVEL:
            continue
        if child.is_symlink():
            continue
        destination = target / child.name
        if child.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            _copy_missing_tree(child, destination)
            continue
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, destination)


def migrate_previous_settings_filename(target_root: Path) -> dict[str, object]:
    """Move a previously emitted settings filename to the canonical name."""

    result: dict[str, object] = {
        "migrated": False,
        "source": "",
        "target": str(target_root / CANONICAL_SETTINGS_FILENAME),
        "error": "",
    }
    canonical = target_root / CANONICAL_SETTINGS_FILENAME
    if canonical.exists():
        return result
    for name in PREVIOUS_SETTINGS_FILENAMES:
        previous = target_root / name
        if not previous.is_file() or previous.is_symlink():
            continue
        result["source"] = str(previous)
        try:
            target_root.mkdir(parents=True, exist_ok=True)
            previous.replace(canonical)
            result["migrated"] = canonical.is_file() and not previous.exists()
        except OSError as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    return result


def migrate_previous_localappdata(target_root: Path) -> dict[str, object]:
    """Move previous user data to the canonical Roaming profile once.

    New runtime writes always use ``%APPDATA%\\HerfyClient``.  The previous
    ``%LOCALAPPDATA%\\HerfyClient`` tree is read only for this one migration.
    Existing Roaming files win over previous files, and stale cache/log/update
    downloads are intentionally not migrated.
    """
    result: dict[str, object] = {
        "attempted": False,
        "migrated": False,
        "previous_removed": False,
        "source": "",
        "target": str(target_root),
        "error": "",
    }
    if not sys.platform.startswith("win"):
        return result

    local_base = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if not local_base:
        return result

    previous_root = Path(local_base) / APP_FOLDER
    result["source"] = str(previous_root)
    try:
        if (
            not previous_root.exists()
            or previous_root.is_symlink()
            or previous_root.resolve() == target_root.resolve()
        ):
            return result

        result["attempted"] = True
        target_root.mkdir(parents=True, exist_ok=True)
        _copy_missing_tree(previous_root, target_root)
        migrate_previous_settings_filename(target_root)

        marker = target_root / MIGRATION_MARKER
        marker.write_text(
            json_payload(previous_root, target_root),
            encoding="utf-8",
        )
        result["migrated"] = True

        shutil.rmtree(previous_root)
        result["previous_removed"] = not previous_root.exists()
    except (OSError, RuntimeError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def json_payload(source: Path, target: Path) -> str:
    payload = {
        "migrated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "target": str(target),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
