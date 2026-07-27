from __future__ import annotations
from typing import Any
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS


def normalize_text(value: Any, default: str = "") -> str:
    try:
        text = str(value if value is not None else default).strip()
        return text if text else str(default)
    except SERVICE_OPERATION_EXCEPTIONS:
        return str(default)


def looks_like_material_code(value: object, material: str = "") -> bool:
    text = str(value or "").strip()
    material_text = str(material or "").strip()
    if not text:
        return True
    if material_text and text.casefold() == material_text.casefold():
        return True
    compact = text.replace(" ", "").replace("-", "").replace("_", "")
    return compact.isdigit()


def best_product_name(material: str, *candidates: object) -> str:
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text and (not looks_like_material_code(text, material)):
            return text
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return str(material or "").strip()


def clean_text(value: object = "") -> str:
    return str(value or "").strip()


def safe_text(value: object = "", *, fallback: str = "") -> str:
    return str(value if value is not None else fallback)
