from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from requests import RequestException
except ImportError:  # pragma: no cover - requests is a runtime dependency.
    RequestException = RuntimeError

from runtime.shared.errors import RemoteRequestError, SessionExpiredError


@dataclass(frozen=True, slots=True)
class RestoreFailureDecision:
    clear_persistent_session: bool
    retryable: bool
    reason: str


def classify_restore_failure(error: BaseException) -> RestoreFailureDecision:
    """Classify restore failures without destroying valid remembered tokens.

    Only explicit authentication rejection is terminal. Connectivity failures,
    server outages, throttling, malformed responses, and local runtime failures
    preserve the remembered session so the user can retry later.
    """

    chain = tuple(_exception_chain(error))
    for exc in chain:
        if isinstance(exc, SessionExpiredError):
            return RestoreFailureDecision(True, False, "session_rejected")
        status = getattr(exc, "status_code", None)
        if status in {401, 403}:
            return RestoreFailureDecision(True, False, "session_rejected")
        if bool(getattr(exc, "clear_remembered_session", False)):
            return RestoreFailureDecision(
                True,
                False,
                str(getattr(exc, "reason", "session_rejected") or "session_rejected"),
            )

    retryable = any(_is_retryable(exc) for exc in chain)
    reason = "restore_temporarily_unavailable" if retryable else "restore_failed"
    return RestoreFailureDecision(False, retryable, reason)


def _is_retryable(error: BaseException) -> bool:
    explicit = getattr(error, "retryable", None)
    if explicit is not None:
        return bool(explicit)
    if isinstance(error, RequestException):
        return True
    if isinstance(error, RemoteRequestError):
        status = error.status_code
        return status is None or status in {408, 429} or status >= 500
    return isinstance(error, (ConnectionError, TimeoutError, OSError))


def _exception_chain(error: BaseException):
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        next_error: Any = current.__cause__ or current.__context__
        current = next_error if isinstance(next_error, BaseException) else None
