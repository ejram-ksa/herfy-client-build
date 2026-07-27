from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

import logging
import threading
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.domain.branches import normalize_branch_list

logger = logging.getLogger(__name__)


class CloudBranchRepositoryMixin:

    def set_allowed_branches(self, branches):
        cleaned = normalize_branch_list(branches)
        self._allowed_branches = cleaned
        state = getattr(self, "app_state", None)
        if state is not None:
            state.set_allowed_branches(cleaned)

    def allowed_branches(self):
        state = getattr(self, "app_state", None)
        state_branches = (
            list(getattr(state, "allowed_branches", []) or [])
            if state is not None
            else []
        )
        if state_branches:
            self._allowed_branches = state_branches
            return state_branches
        if self._allowed_branches:
            return list(self._allowed_branches)
        ctx = self.perm_ctx()
        if ctx.scope.all_branches and self._cloud_service() is not None:
            if threading.current_thread() is threading.main_thread():
                logger.debug(
                    "Skipping synchronous cloud branch fetch on GUI thread; background branch hydration will refresh the scope."
                )
            else:
                try:
                    branches = self._cloud_service().meta_branches()
                    if branches:
                        self.set_allowed_branches(list(branches))
                        return list(self._allowed_branches)
                except SERVICE_OPERATION_EXCEPTIONS:
                    logger.debug(
                        "DatabaseCloudContextMixin.allowed_branches fallback failed",
                        exc_info=True,
                    )
        scoped = list(ctx.scope.branches or [])
        if scoped:
            self.set_allowed_branches(scoped)
            return list(self._allowed_branches)
        return []

    def _resolve_branch_case(self, branch: str) -> str:
        b = str(branch or "").strip()
        if not b:
            return ""
        try:
            for x in self.allowed_branches() or []:
                if str(x).strip().lower() == b.lower():
                    return str(x).strip()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "DatabaseCloudContextMixin._resolve_branch_case fallback failed",
                exc_info=True,
            )
        return b

    def set_active_branch(self, branch: str):
        state = getattr(self, "app_state", None)
        old = str(
            getattr(state, "current_branch", "") or self._active_branch or ""
        ).strip()
        b = str(branch or "").strip()
        if b and b.lower() != "all":
            b = self._resolve_branch_case(b)
        self._active_branch = b
        if state is not None:
            state.set_current_branch(b)
        if old.lower() != b.lower():
            self.invalidate_cloud_cache(old or None)
            self.invalidate_cloud_cache(b or None)

    def get_active_branch(self):
        state = getattr(self, "app_state", None)
        if state is not None:
            current = str(getattr(state, "current_branch", "") or "").strip()
            if current:
                self._active_branch = current
                return current
        return str(self._active_branch or "").strip()

    def _ensure_writable_branch(self, branch: str) -> str:
        value = str(branch or "").strip()
        if not value or not self.can_write_branch(value):
            raise RuntimeError("You don't have permission for this branch.")
        return value

    def _pick_branch_for_write(self) -> str:
        b = self.get_active_branch()
        if b and b.lower() != "all":
            return self._ensure_writable_branch(self._resolve_branch_case(b))
        branches = self.allowed_branches()
        if len(branches) == 1:
            return self._ensure_writable_branch(str(branches[0]).strip())
        raise RuntimeError("Branch is required. Choose a branch first.")


from runtime.shared.objects import normalize_int
from runtime.domain.access import PermissionContext, PermissionService



class CloudContextStateRepositoryMixin:

    def _app_state_value(self, attr: str, default=None):
        state = getattr(self, "app_state", None)
        return getattr(state, attr, default) if state is not None else default

    def _call_app_state_setter(self, setter: str, value) -> None:
        state = getattr(self, "app_state", None)
        if state is not None:
            getattr(state, setter)(value)

    def _cloud_service(self):
        return self._app_state_value("api_client")

    def _current_profile(self):
        return self._app_state_value("current_user")

    def _role(self) -> str:
        return str(self._app_state_value("role", "store_user") or "store_user").strip()

    def _set_role(self, role: str) -> None:
        self._call_app_state_setter("set_role", role)

    def _permission_context(self) -> PermissionContext:
        ctx = self._app_state_value("permissions")
        return ctx if isinstance(ctx, PermissionContext) else PermissionContext()

    def _set_permission_context(self, permission_context) -> None:
        self._call_app_state_setter("set_permissions", permission_context)

    def set_cloud_context(self, service, profile):
        logger.info(
            "Setting cloud context - service: %s, profile: %s",
            service is not None,
            profile is not None,
        )
        if service is None or profile is None:
            self.app_state.set_api_client(None)
            self.app_state.set_current_user(None)
            self._set_role("store_user")
            self._set_permission_context(PermissionContext())
            self.set_allowed_branches([])
            self.set_active_branch("")
            self.invalidate_cloud_cache()
            self._cloud_cache_by_id.clear()
            logger.info("Cloud context cleared")
            return
        self.app_state.set_api_client(service)
        self.app_state.set_current_user(profile)
        try:
            saved_cursor = normalize_int(self.get_setting("server_sync_cursor", "0"))
            if saved_cursor > 0 and hasattr(service, "set_sync_cursor"):
                service.set_sync_cursor(saved_cursor)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Cloud sync cursor restore skipped", exc_info=True)
        profile_context = getattr(profile, "permission_context", None)
        self._set_permission_context(
            profile_context
            if isinstance(profile_context, PermissionContext)
            else PermissionContext()
        )
        self._set_role(self._permission_context().role)
        self.set_allowed_branches(self._permission_context().scope.branches or [])
        self.invalidate_cloud_cache()
        cached_branches = list(
            getattr(self.app_state, "allowed_branches", []) or []
        ) or list(getattr(self._permission_context().scope, "branches", []) or [])
        logger.info(
            "Cloud context set - role=%s branches=%s", self._role(), cached_branches
        )
        active_branch = str(
            getattr(profile, "active_branch", "")
            or self._permission_context().active_branch
            or ""
        ).strip()
        if active_branch:
            self.set_active_branch(active_branch)
        else:
            default_branch = PermissionService.default_branch(
                permission_context=self._permission_context()
            )
            if default_branch:
                self.set_active_branch(default_branch)

    def perm_ctx(self) -> PermissionContext:
        ctx = self._permission_context()
        if isinstance(ctx, PermissionContext):
            scope = getattr(ctx, "scope", None)
            scope_areas = [
                str(a).strip()
                for a in getattr(scope, "areas", None) or []
                if str(a).strip()
            ]
            scope_branches = [
                str(b).strip()
                for b in getattr(scope, "branches", None) or []
                if str(b).strip()
            ]
            active = str(
                getattr(getattr(self, "app_state", None), "current_branch", "")
                or getattr(self, "_active_branch", "")
                or ctx.active_branch
                or ""
            ).strip()
            if not active and len(scope_branches) == 1:
                active = scope_branches[0]
            payload = {
                "user_id": ctx.user_id,
                "username": ctx.username,
                "role": ctx.role,
                "permissions": list(ctx.permissions or []),
                "scope": {
                    "regions": [
                        str(region).strip()
                        for region in getattr(scope, "regions", None) or []
                        if str(region).strip()
                    ],
                    "areas": scope_areas,
                    "branches": scope_branches,
                    "all_regions": bool(getattr(scope, "all_regions", False)),
                    "all_areas": bool(getattr(scope, "all_areas", False)),
                    "all_branches": bool(getattr(scope, "all_branches", False)),
                },
                "area_id": ctx.area_id,
                "area_manager_id": ctx.area_manager_id,
                "assigned_branch_ids": [
                    str(b).strip()
                    for b in ctx.assigned_branch_ids or []
                    if str(b).strip()
                ],
                "must_change_password": bool(ctx.must_change_password),
                "is_active": bool(ctx.is_active),
                "temporary_manager": bool(ctx.temporary_manager),
                "active_branch": active,
                "permission_source": str(getattr(ctx, "authority_source", "") or ""),
                "authority_revision": int(getattr(ctx, "authority_revision", 0) or 0),
            }
            return PermissionContext.from_payload(payload, active_branch=active)
        return PermissionContext.from_values(
            self._role(), (), str(getattr(self, "_active_branch", "") or "").strip()
        )




class CloudPermissionRepositoryMixin:

    def has_permission(self, permission: str) -> bool:
        return PermissionService.has_permission(
            permission, permission_context=self.perm_ctx()
        )

    def can_view_all_branches(self) -> bool:
        return PermissionService.can_view_all(permission_context=self.perm_ctx())

    def can_access_branch(self, branch: str | None) -> bool:
        return PermissionService.can_access_branch(
            branch, permission_context=self.perm_ctx()
        )

    def can_view_branch(self, branch: str | None) -> bool:
        return PermissionService.can_view_branch(
            branch, permission_context=self.perm_ctx()
        )

    def _can_tracking_action(self, action: str, branch: str | None) -> bool:
        checker = {
            "create": PermissionService.can_create_tracking,
            "update": PermissionService.can_update_tracking,
            "delete": PermissionService.can_delete_tracking,
        }.get(str(action or "").strip().lower())
        return bool(checker and checker(branch, permission_context=self.perm_ctx()))

    def can_write_branch(self, branch: str | None) -> bool:
        return any(
            (
                self._can_tracking_action(action, branch)
                for action in ("create", "update")
            )
        )

    def can_create_tracking(self, branch: str | None) -> bool:
        return self._can_tracking_action("create", branch)

    def can_update_tracking(self, branch: str | None) -> bool:
        return self._can_tracking_action("update", branch)

    def can_delete_tracking(self, branch: str | None) -> bool:
        return self._can_tracking_action("delete", branch)

    def can_reset_user_password(
        self,
        *,
        target_username: str = "",
        target_area_id: str = "",
        target_branch_id: str = "",
        target_role: str = "",
    ) -> bool:
        return PermissionService.can_reset_user_password(
            permission_context=self.perm_ctx(),
            target_username=target_username,
            target_area_id=target_area_id,
            target_branch_id=target_branch_id,
            target_role=target_role,
        )

    def can_manage_catalog(self) -> bool:
        return PermissionService.can_manage_catalog(permission_context=self.perm_ctx())

    def can_manage_usage(self) -> bool:
        return PermissionService.can_manage_usage(permission_context=self.perm_ctx())

    def can_manage_org(self) -> bool:
        return PermissionService.can_manage_org(permission_context=self.perm_ctx())


from runtime.infrastructure.persistence import CloudCacheContextRepositoryMixin


class DatabaseCloudContextMixin(
    CloudContextStateRepositoryMixin,
    CloudPermissionRepositoryMixin,
    CloudBranchRepositoryMixin,
    CloudCacheContextRepositoryMixin,
):
    """Composition surface for cloud context, branch scope and local permission adapters."""


# --- package exports ---
__all__ = [
    "CloudBranchRepositoryMixin",
    "CloudContextStateRepositoryMixin",
    "CloudPermissionRepositoryMixin",
    "DatabaseCloudContextMixin",
]
