from __future__ import annotations
import os
from typing import Any

_TRUE_VALUES = {"true", "1", "yes", "on"}
_FALSE_VALUES = {"false", "0", "no", "off"}


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return bool(default)


def normalize_bool(value: Any, default: bool = False) -> bool:
    return parse_bool(value, default)


def setting_bool(getter, key: str, default: bool = False) -> bool:
    raw = getter(key, "True" if default else "False")
    return parse_bool(raw, default)


def truthy_env(name: str, default: bool) -> bool:
    return parse_bool(os.getenv(name), default)


def should_require_update_sha256() -> bool:
    return truthy_env("PTS_REQUIRE_UPDATE_SHA256", True)
