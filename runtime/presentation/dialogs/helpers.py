from __future__ import annotations
from runtime.shared.objects import safe_get


def text_value(mapping: dict, *keys: str) -> str:
    for key in keys:
        value = str(safe_get(mapping, key, "") or "").strip()
        if value:
            return value
    return "-"
