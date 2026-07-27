from __future__ import annotations
import logging
from pathlib import Path
from runtime.shared.settings.config import bundled_or_source_path
from runtime.shared.errors import FILESYSTEM_OPERATION_EXCEPTIONS
from runtime.shared.booleans import parse_bool
from runtime.application.services.settings_schema import (
    CANONICAL_SETTINGS_DEFAULTS,
    validate_canonical_settings,
)

logger = logging.getLogger(__name__)
INSTALLER_DEFAULTS_FILE = "installer_defaults.ini"
EXTRA_INSTALLER_DEFAULT_KEYS: dict[str, str] = {
    "check_updates_on_startup": "True",
    "refresh_remote_ui_on_startup": "True",
    "immediate_server_sync": "True",
    "start_with_windows": "False",
    "tray_show_message_on_minimize": "False",
}
_BOOLEAN_EXTRA_KEYS = {
    "check_updates_on_startup",
    "refresh_remote_ui_on_startup",
    "immediate_server_sync",
    "start_with_windows",
    "tray_show_message_on_minimize",
}


def _read_flat_ini(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("#", ";", "[")) or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                values[key] = value.strip()
    except (OSError, UnicodeError, *FILESYSTEM_OPERATION_EXCEPTIONS):
        logger.debug("Unable to read installer defaults: %s", path, exc_info=True)
    return values


def _candidate_paths() -> tuple[Path, ...]:
    packaged = bundled_or_source_path(INSTALLER_DEFAULTS_FILE)
    return (packaged,)


def load_installer_defaults() -> dict[str, str]:
    """Load safe installer-selected defaults from the installed package.

    The installer may choose language, monitoring, notification, and startup
    defaults. Server permissions and server-authoritative behavior are not
    configurable here. Unknown keys are ignored.
    """
    raw: dict[str, str] = {}
    for path in _candidate_paths():
        if path.exists():
            raw.update(_read_flat_ini(path))
            break
    if not raw:
        return {}
    canonical_input = {
        key: raw[key] for key in CANONICAL_SETTINGS_DEFAULTS if key in raw
    }
    normalized: dict[str, str] = {}
    if canonical_input:
        validation = validate_canonical_settings(canonical_input)
        normalized.update(validation.values)
        if validation.errors:
            logger.warning(
                "Installer defaults normalized with validation warnings: %s",
                validation.errors,
            )
    for key, default in EXTRA_INSTALLER_DEFAULT_KEYS.items():
        if key not in raw:
            continue
        if key in _BOOLEAN_EXTRA_KEYS:
            normalized[key] = (
                "True"
                if parse_bool(raw.get(key), parse_bool(default, True))
                else "False"
            )
        else:
            normalized[key] = str(raw.get(key) or default)
    if raw:
        normalized["tray_settings_migrated_v2"] = "True"
    return normalized


def merge_installer_defaults(defaults: dict[str, str]) -> dict[str, str]:
    """Return database defaults overridden by safe installer defaults."""
    merged = dict(defaults)
    for key, value in load_installer_defaults().items():
        if key in merged:
            merged[key] = value
    return merged
