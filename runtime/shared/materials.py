from __future__ import annotations
import math
import re
from typing import Any


def normalize_material_code(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).strip()
    if isinstance(value, int):
        return str(value).strip()
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
        text = f"{value:f}".rstrip("0").rstrip(".")
        return text.strip()
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    text = text.replace(",", "")
    if re.fullmatch("\\d+\\.0+", text):
        return text.split(".", 1)[0]
    return text
