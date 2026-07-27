from __future__ import annotations
import json
from pathlib import Path
from runtime.shared.settings.config import bundled_or_source_path
from runtime.shared.errors import FILESYSTEM_OPERATION_EXCEPTIONS, PARSE_OPERATION_EXCEPTIONS

_VERSION_FALLBACK = "2.18.1"


def _version_file() -> Path:
    return Path(__file__).resolve().parents[3] / "version.json"


def _read_version() -> str:
    try:
        payload = json.loads(_version_file().read_text(encoding="utf-8-sig"))
    except FILESYSTEM_OPERATION_EXCEPTIONS:
        return _VERSION_FALLBACK
    except PARSE_OPERATION_EXCEPTIONS:
        return _VERSION_FALLBACK
    if not isinstance(payload, dict):
        return _VERSION_FALLBACK
    value = str(
        payload.get("app_version") or payload.get("version") or _VERSION_FALLBACK
    ).strip()
    return value or _VERSION_FALLBACK


APP_VERSION = _read_version()
__version__ = APP_VERSION
VERSION = APP_VERSION
