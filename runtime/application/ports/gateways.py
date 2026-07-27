from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CloudRuntimePort:
    apply_remote_catalog_snapshot: Callable[
        [Any, dict[str, Any] | None], dict[str, str]
    ]
    fetch_cloud_snapshot_payload: Callable[..., dict[str, Any]]
    prepare_update_check: Callable[..., tuple[object | None, str, bool]]
    profile_to_cloud_user_payload: Callable[[Any], dict[str, Any]]


_cloud_runtime_port: CloudRuntimePort | None = None


def configure_cloud_runtime(port: CloudRuntimePort) -> None:
    global _cloud_runtime_port
    _cloud_runtime_port = port


def _require_cloud_runtime_port() -> CloudRuntimePort:
    if _cloud_runtime_port is None:
        raise RuntimeError("Cloud runtime adapter is not configured.")
    return _cloud_runtime_port


def apply_remote_catalog_snapshot(
    db_manager, snapshot: dict[str, Any] | None
) -> dict[str, str]:
    return _require_cloud_runtime_port().apply_remote_catalog_snapshot(
        db_manager, snapshot
    )


def fetch_cloud_snapshot_payload(
    cloud_service, *, include_snapshot: bool = False
) -> dict[str, Any]:
    return _require_cloud_runtime_port().fetch_cloud_snapshot_payload(
        cloud_service, include_snapshot=include_snapshot
    )


def prepare_update_check(settings_store, *, force: bool = False):
    return _require_cloud_runtime_port().prepare_update_check(
        settings_store, force=force
    )


def profile_to_cloud_user_payload(profile) -> dict[str, Any]:
    return _require_cloud_runtime_port().profile_to_cloud_user_payload(profile)


from runtime.shared.errors import RemoteRequestError


@dataclass(frozen=True)
class HttpTransportPort:
    api_request: Callable[..., Any]
    api_fetch_json: Callable[..., dict[str, Any]]
    api_post_json: Callable[..., dict[str, Any]]
    get_server_base_url: Callable[..., str]
    fetch_client_bootstrap: Callable[..., dict[str, Any]]


_transport: HttpTransportPort | None = None


def configure_http_transport(transport: HttpTransportPort) -> None:
    global _transport
    _transport = transport


def _require_transport() -> HttpTransportPort:
    if _transport is None:
        raise RemoteRequestError("HTTP transport adapter is not configured.")
    return _transport


def api_request(
    method: str, path_or_url: str, *, base_url: str | None = None, **kwargs: Any
) -> Any:
    return _require_transport().api_request(
        method, path_or_url, base_url=base_url, **kwargs
    )


def api_fetch_json(
    path_or_url: str, *, base_url: str | None = None, **kwargs: Any
) -> dict[str, Any]:
    payload = _require_transport().api_fetch_json(
        path_or_url, base_url=base_url, **kwargs
    )
    return payload if isinstance(payload, dict) else {}


def api_post_json(
    path_or_url: str,
    payload: dict[str, Any] | None = None,
    *,
    base_url: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """POST a JSON payload through the configured transport.

    The application port mirrors ``runtime.infrastructure.network.http.api_post_json`` so
    authentication refresh and other service calls can pass the request payload
    as the second positional argument.  Keeping this signature compatible avoids
    falling back to a failed restore/refresh path while the UI is active.
    """
    request_payload = payload if isinstance(payload, dict) else {}
    response_payload = _require_transport().api_post_json(
        path_or_url, request_payload, base_url=base_url, **kwargs
    )
    return response_payload if isinstance(response_payload, dict) else {}


def get_server_base_url(default: str | None = None) -> str:
    """Return the configured API base URL.

    During isolated UI construction/tests the HTTP transport may not be configured yet.
    When a caller provides a default, keep the call safe and return that default instead
    of raising before the application bootstrap has installed the real transport.
    """
    if _transport is None:
        if default is not None:
            return str(default or "").strip()
        raise RemoteRequestError("HTTP transport adapter is not configured.")
    if default is None:
        return str(_transport.get_server_base_url()).strip()
    return str(_transport.get_server_base_url(default)).strip()


def fetch_client_bootstrap(
    client_version: str, *, base_url: str | None = None
) -> dict[str, Any]:
    payload = _require_transport().fetch_client_bootstrap(
        client_version, base_url=base_url
    )
    return payload if isinstance(payload, dict) else {}


from collections.abc import Mapping


@dataclass(frozen=True)
class StartupRegistrationPort:
    sync_startup_from_preferences: Callable[[Mapping[str, bool]], bool]


_startup_registration_port: StartupRegistrationPort | None = None


def configure_startup_registration(port: StartupRegistrationPort) -> None:
    global _startup_registration_port
    _startup_registration_port = port


def sync_startup_from_preferences(preferences: Mapping[str, bool]) -> bool:
    if _startup_registration_port is None:
        return False
    return bool(_startup_registration_port.sync_startup_from_preferences(preferences))
