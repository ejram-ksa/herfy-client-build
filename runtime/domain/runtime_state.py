from __future__ import annotations
from typing import Any
from runtime.shared.objects import noop
from runtime.domain.branches import normalize_branch, normalize_branch_list
from runtime.domain.access import PermissionContext, normalize_role


class RuntimeStateCore:

    def __init__(self) -> None:
        self._init_runtime_state()

    def _init_runtime_state(self) -> None:
        self._session: Any = None
        self._current_user: Any = None
        self._permissions = PermissionContext()
        self._current_branch = ""
        self._allowed_branches: list[str] = []
        self._connection_online = False
        self._connection_message = ""
        self._api_client: Any = None
        self._cache: dict[str, Any] = {}
        self._role = "store_user"

    _emit_session_changed = noop
    _emit_user_changed = noop
    _emit_permissions_changed = noop
    _emit_branch_changed = noop
    _emit_connection_changed = noop
    _emit_cache_changed = noop
    _emit_api_client_changed = noop

    def _set_reference_state(self, attr_name: str, value: Any, emitter) -> None:
        if getattr(self, attr_name) is value:
            return
        setattr(self, attr_name, value)
        emitter(value)


    @property
    def session(self) -> Any:
        return self._session

    def set_session(self, session: Any) -> None:
        self._set_reference_state("_session", session, self._emit_session_changed)

    @property
    def current_user(self) -> Any:
        return self._current_user

    def set_current_user(self, profile: Any) -> None:
        self._set_reference_state("_current_user", profile, self._emit_user_changed)

    @property
    def permissions(self) -> PermissionContext:
        if isinstance(self._permissions, PermissionContext):
            return self._permissions
        return PermissionContext()

    def set_permissions(self, permission_context: PermissionContext | None) -> None:
        ctx = (
            permission_context
            if isinstance(permission_context, PermissionContext)
            else PermissionContext()
        )
        self._permissions = ctx
        self._role = ctx.role or "store_user"
        self._emit_permissions_changed(ctx)

    @property
    def current_branch(self) -> str:
        return str(self._current_branch or "").strip()

    def set_current_branch(self, branch: str) -> None:
        value = normalize_branch(branch)
        if self.current_branch.lower() == value.lower():
            self._current_branch = value
            return
        self._current_branch = value
        self._emit_branch_changed(value)

    @property
    def allowed_branches(self) -> list[str]:
        return list(self._allowed_branches)

    def set_allowed_branches(
        self, branches: list[str] | tuple[str, ...] | None
    ) -> None:
        cleaned = normalize_branch_list(branches)
        self._allowed_branches = cleaned
        self._emit_cache_changed("allowed_branches", list(cleaned))

    @property
    def role(self) -> str:
        return normalize_role(self._role)

    def set_role(self, role: str) -> None:
        self._role = normalize_role(role)
        ctx = self.permissions
        if ctx.role != self._role:
            payload = ctx.to_payload()
            payload["role"] = self._role
            self.set_permissions(
                PermissionContext.from_payload(
                    payload, active_branch=self.current_branch or ctx.active_branch
                )
            )

    @property
    def connection_online(self) -> bool:
        return bool(self._connection_online)

    @property
    def connection_message(self) -> str:
        return str(self._connection_message or "")

    def set_connection_state(self, online: bool, message: str = "") -> None:
        new_online = bool(online)
        new_message = str(message or "")
        if (
            self._connection_online == new_online
            and self._connection_message == new_message
        ):
            return
        self._connection_online = new_online
        self._connection_message = new_message
        self._emit_connection_changed(new_online, new_message)

    @property
    def api_client(self) -> Any:
        return self._api_client

    def set_api_client(self, api_client: Any) -> None:
        self._set_reference_state(
            "_api_client", api_client, self._emit_api_client_changed
        )

    def set_cache(self, key: str, value: Any) -> None:
        cache_key = str(key or "").strip()
        if not cache_key:
            return
        self._cache[cache_key] = value
        self._emit_cache_changed(cache_key, value)

    def get_cache(self, key: str, default: Any = None) -> Any:
        return self._cache.get(str(key or "").strip(), default)

    def clear_cache(self, key: str | None = None) -> None:
        if key is None:
            keys = list(self._cache.keys())
            self._cache.clear()
            for cache_key in keys:
                self._emit_cache_changed(cache_key, None)
            return
        cache_key = str(key or "").strip()
        if not cache_key:
            return
        self._cache.pop(cache_key, None)
        self._emit_cache_changed(cache_key, None)

    def reset_identity(self) -> None:
        self.set_session(None)
        self.set_current_user(None)
        self.set_permissions(PermissionContext())
        self.set_allowed_branches([])
        self.set_current_branch("")
        self.set_api_client(None)
        self.set_connection_state(False, "")

    def snapshot(self) -> dict[str, Any]:
        return {
            "session": self._session,
            "current_user": self._current_user,
            "permissions": self.permissions,
            "current_branch": self.current_branch,
            "allowed_branches": self.allowed_branches,
            "connection_online": self.connection_online,
            "connection_message": self.connection_message,
            "api_client": self.api_client,
            "cache_keys": sorted(self._cache.keys()),
            "role": self.role,
        }
