from __future__ import annotations
from collections.abc import Iterable
import math
from typing import Any
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.strings import normalize_text

def safe_get(obj: Any, key: str, default: Any=None) -> Any:
    try:
        if isinstance(obj, dict):
            return obj.get(key, default)
        if obj is None:
            return default
        if hasattr(obj, 'keys'):
            try:
                keys = obj.keys()
            except SERVICE_OPERATION_EXCEPTIONS:
                keys = ()
            if key in keys:
                return obj[key]
        return getattr(obj, key, default)
    except SERVICE_OPERATION_EXCEPTIONS:
        return default

def normalize_int(value: Any, default: int=0) -> int:
    try:
        if value in (None, ''):
            return int(default)
        number = float(value)
        if not math.isfinite(number):
            return int(default)
        return int(number)
    except (*SERVICE_OPERATION_EXCEPTIONS, OverflowError):
        return int(default)

def normalize_str_list(value: Any) -> list[str]:
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, list | tuple | set):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = normalize_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out

def first_value(source: dict[str, Any] | None, *keys: str, default: Any='') -> Any:
    data = source if isinstance(source, dict) else {}
    for key in keys:
        value = data.get(key)
        if value not in (None, ''):
            return value
    return default

def clean_string_list(values: Iterable[Any] | Any | None, *, split_csv: bool=False) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str | bytes):
        iterable = [part.strip() for part in str(values).split(',')] if split_csv else [values]
    else:
        iterable = list(values)
    result: list[str] = []
    seen: set[str] = set()
    for value in iterable:
        item = str(value or '').strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result

def call_if_callable(func: Any, *args: Any, default: Any=None, **kwargs: Any) -> Any:
    if not callable(func):
        return default
    return func(*args, **kwargs)

def noop(*args: Any, **kwargs: Any) -> None:
    return None

def normalized_result_key(obj, default: str='secondary') -> str:
    return str(getattr(obj, '_result', default) or default)
