from __future__ import annotations
import json
from subprocess import SubprocessError

try:
    from requests import RequestException
except ImportError:
    RequestException = RuntimeError
UI_OPERATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    AttributeError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)
STATE_OPERATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    AttributeError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)
FILESYSTEM_OPERATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    FileExistsError,
    FileNotFoundError,
    IsADirectoryError,
    NotADirectoryError,
    PermissionError,
    OSError,
)
PARSE_OPERATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TypeError,
    ValueError,
    UnicodeDecodeError,
    json.JSONDecodeError,
)
IMPORT_OPERATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    AttributeError,
    ImportError,
    ModuleNotFoundError,
)
PROCESS_OPERATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    SubprocessError,
)
CALLBACK_OPERATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    AttributeError,
    RuntimeError,
    TypeError,
    ValueError,
)
NETWORK_OPERATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    UnicodeDecodeError,
    RequestException,
)
SERVICE_OPERATION_EXCEPTIONS: tuple[type[BaseException], ...] = (
    AttributeError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    ImportError,
    ModuleNotFoundError,
    UnicodeDecodeError,
    json.JSONDecodeError,
    SubprocessError,
)


class RemoteRequestError(RuntimeError):
    """Raised when a remote API request fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SessionExpiredError(RemoteRequestError):
    """Raised when the remote endpoint rejects the current session/token."""


__all__ = [
    "UI_OPERATION_EXCEPTIONS",
    "STATE_OPERATION_EXCEPTIONS",
    "FILESYSTEM_OPERATION_EXCEPTIONS",
    "PARSE_OPERATION_EXCEPTIONS",
    "IMPORT_OPERATION_EXCEPTIONS",
    "PROCESS_OPERATION_EXCEPTIONS",
    "CALLBACK_OPERATION_EXCEPTIONS",
    "NETWORK_OPERATION_EXCEPTIONS",
    "SERVICE_OPERATION_EXCEPTIONS",
    "RemoteRequestError",
    "SessionExpiredError",
    "RequestException",
]
