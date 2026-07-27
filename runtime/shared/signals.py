from __future__ import annotations
import logging
from typing import Any
from runtime.shared.errors import CALLBACK_OPERATION_EXCEPTIONS


def safe_disconnect(
    signal: Any,
    slot: Any = None,
    *,
    logger_: logging.Logger | None = None,
    context: str = "Signal disconnect",
) -> bool:
    try:
        if slot is None:
            signal.disconnect()
        else:
            signal.disconnect(slot)
        return True
    except CALLBACK_OPERATION_EXCEPTIONS:
        if logger_ is not None:
            logger_.debug("%s skipped; no active receiver", context)
        return False
