from __future__ import annotations
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


def parse_plain_number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        number = float(str(value).replace(",", "").strip())
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError, OverflowError):
        logger.debug("Failed to parse plain number: %r", value, exc_info=True)
        return 0.0


def format_plain_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        logger.debug("Failed to format plain number: %r", value, exc_info=True)
        return str(value or "")
    if not math.isfinite(number):
        return str(value or "")
    if abs(number - int(number)) < 1e-09:
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def parse_excel_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else 0.0
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return 0.0
    negative = text.startswith("(") and text.endswith(")")
    numeric_text = text.strip("()").replace(",", "")
    try:
        parsed = float(numeric_text)
    except (TypeError, ValueError, OverflowError):
        logger.debug("Failed to parse Excel number: %r", value, exc_info=True)
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return -parsed if negative else parsed
