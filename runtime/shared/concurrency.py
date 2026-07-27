from __future__ import annotations
import logging
import threading
from typing import Any
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS


def wait_for_inflight_event(
    event: Any,
    *,
    timeout_seconds: float,
    logger_: logging.Logger | None = None,
    context: str = "Shared load wait",
    allow_main_thread_wait: bool = False,
) -> bool:
    """Wait for a shared in-flight load without freezing the GUI thread.

    Repository/cache coalescing uses threading.Event to avoid duplicate server
    pulls.  Waiting on that event from the Qt/main thread can make Windows show
    the application as not responding.  UI callers should receive stale or
    currently available data and let the worker that owns the fetch update the
    UI later.
    """
    try:
        if (
            not bool(allow_main_thread_wait)
            and threading.current_thread() is threading.main_thread()
            and (not bool(event.is_set()))
        ):
            if logger_ is not None:
                logger_.debug("%s skipped blocking wait on main thread", context)
            return False
        finished = bool(event.wait(timeout=max(0.1, float(timeout_seconds))))
    except SERVICE_OPERATION_EXCEPTIONS:
        if logger_ is not None:
            logger_.debug("%s failed while waiting", context, exc_info=True)
        return False
    if not finished and logger_ is not None:
        logger_.debug("%s timed out after %.1fs", context, float(timeout_seconds))
    return finished
