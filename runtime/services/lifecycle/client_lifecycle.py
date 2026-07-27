from __future__ import annotations

from typing import Any


def close_runtime_client(client: Any) -> str:
    """Release one API/runtime client through exactly one terminal method.

    A client ``close`` implementation is expected to stop realtime transport and
    release HTTP sessions. ``shutdown`` is the fallback for alternate clients,
    while ``stop_realtime`` is used only when no terminal close method exists.
    The selected method name is returned for validation and diagnostics.
    """

    if client is None:
        return ""
    for method_name in ("close", "shutdown", "stop_realtime"):
        method = getattr(client, method_name, None)
        if callable(method):
            method()
            return method_name
    return ""
