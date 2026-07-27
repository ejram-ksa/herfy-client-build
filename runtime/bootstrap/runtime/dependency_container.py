from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from runtime.bootstrap.session.runtime_session import AppState
from runtime.infrastructure.persistence.database_sections import LocalDataStore
from runtime.services.session import SessionStore
from runtime.services.lifecycle import ApplicationLifecycle, BackgroundScheduler
from runtime.application.ports import CloudRuntimePort, configure_cloud_runtime
from runtime.application.ports import HttpTransportPort, configure_http_transport
from runtime.shared.errors import RemoteRequestError, SessionExpiredError
from runtime.application.ports import StartupRegistrationPort, configure_startup_registration
from runtime.domain.user import UserProfile
from runtime.infrastructure.network.api import ApiClient, fetch_client_bootstrap as api_fetch_client_bootstrap
from runtime.infrastructure.network.http import (
    RemoteRequestError as HttpRemoteRequestError,
    SessionExpiredError as HttpSessionExpiredError,
    api_fetch_json as http_api_fetch_json,
    api_post_json as http_api_post_json,
    api_request as http_api_request,
    get_server_base_url as http_get_server_base_url,
)
from runtime.application.services.preferences import SettingsService
from runtime.application.services.tracking import TrackingService
from runtime.application.services.updates import UpdateManager
from runtime.application.services.usage import UsageService
from runtime.application.services.usage import UsageWorkspaceService


def _convert_remote_error(exc: Exception) -> RemoteRequestError:
    status_code = getattr(exc, "status_code", None)
    if isinstance(exc, HttpSessionExpiredError):
        return SessionExpiredError(str(exc), status_code=status_code)
    return RemoteRequestError(str(exc), status_code=status_code)


def _api_request(
    method: str, path_or_url: str, *, base_url: str | None = None, **kwargs: Any
) -> Any:
    try:
        return http_api_request(method, path_or_url, base_url=base_url, **kwargs)
    except HttpRemoteRequestError as exc:
        raise _convert_remote_error(exc) from exc


def _api_fetch_json(
    path_or_url: str, *, base_url: str | None = None, **kwargs: Any
) -> dict[str, Any]:
    try:
        return http_api_fetch_json(path_or_url, base_url=base_url, **kwargs)
    except HttpRemoteRequestError as exc:
        raise _convert_remote_error(exc) from exc


def _api_post_json(
    path_or_url: str,
    payload: dict[str, Any] | None = None,
    *,
    base_url: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        return http_api_post_json(
            path_or_url,
            payload if isinstance(payload, dict) else {},
            base_url=base_url,
            **kwargs,
        )
    except HttpRemoteRequestError as exc:
        raise _convert_remote_error(exc) from exc


def _fetch_client_bootstrap(
    client_version: str, *, base_url: str | None = None
) -> dict[str, Any]:
    try:
        return api_fetch_client_bootstrap(client_version, base_url=base_url)
    except HttpRemoteRequestError as exc:
        raise _convert_remote_error(exc) from exc


def configure_application_ports() -> None:
    from runtime.application.services.sync import profile_to_cloud_user_payload
    from runtime.application.services.sync import (
        apply_remote_catalog_snapshot,
        fetch_cloud_snapshot_payload,
        prepare_update_check,
    )
    from runtime.application.services.sync import sync_startup_from_preferences

    configure_http_transport(
        HttpTransportPort(
            api_request=_api_request,
            api_fetch_json=_api_fetch_json,
            api_post_json=_api_post_json,
            get_server_base_url=http_get_server_base_url,
            fetch_client_bootstrap=_fetch_client_bootstrap,
        )
    )
    configure_startup_registration(
        StartupRegistrationPort(
            sync_startup_from_preferences=sync_startup_from_preferences
        )
    )
    configure_cloud_runtime(
        CloudRuntimePort(
            apply_remote_catalog_snapshot=apply_remote_catalog_snapshot,
            fetch_cloud_snapshot_payload=fetch_cloud_snapshot_payload,
            prepare_update_check=prepare_update_check,
            profile_to_cloud_user_payload=profile_to_cloud_user_payload,
        )
    )


@dataclass
class DependencyContainer:
    app_state: AppState = field(default_factory=AppState)
    db_manager: LocalDataStore = field(init=False)
    api_client_factory: Callable[..., ApiClient] = ApiClient
    update_manager_factory: Callable[[str], UpdateManager] = UpdateManager
    sync_manager_factory: Callable[..., Any] | None = None
    tracking_service_factory: Callable[..., TrackingService] = TrackingService
    usage_service_factory: Callable[..., UsageService] = UsageService
    usage_workspace_service_factory: Callable[..., UsageWorkspaceService] = (
        UsageWorkspaceService
    )
    preferences_service_factory: Callable[..., SettingsService] = SettingsService
    session_store_factory: Callable[..., SessionStore] = SessionStore
    lifecycle: ApplicationLifecycle = field(default_factory=ApplicationLifecycle)
    background_scheduler: BackgroundScheduler = field(default_factory=BackgroundScheduler)

    def __post_init__(self) -> None:
        self.db_manager = LocalDataStore(app_state=self.app_state)
        self.lifecycle.register_resource(
            "background_scheduler",
            self.background_scheduler,
            stop_method="stop",
            wait_method="wait",
            timeout_seconds=5.0,
        )

    def create_api_client(
        self, id_token: str, user: UserProfile | None = None
    ) -> ApiClient:
        return self.api_client_factory(id_token=id_token, user=user)

    def create_sync_manager(self, owner) -> Any:
        factory = self.sync_manager_factory
        if factory is None:
            from runtime.bootstrap.runtime.background_workers import SyncManager

            factory = SyncManager
        return factory(owner)

    def create_tracking_service(self) -> TrackingService:
        return self.tracking_service_factory(self.db_manager)

    def create_session_store(self) -> SessionStore:
        return self.session_store_factory()

    def create_usage_service(self) -> UsageService:
        return self.usage_service_factory(self.db_manager)

    def create_usage_workspace_service(self) -> UsageWorkspaceService:
        return self.usage_workspace_service_factory()

    def create_preferences_service(self) -> SettingsService:
        return self.preferences_service_factory(self.db_manager)


def create_dependency_container() -> DependencyContainer:
    return DependencyContainer()
