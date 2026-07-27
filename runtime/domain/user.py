from __future__ import annotations
from dataclasses import dataclass, field
from runtime.domain.access import PermissionContext


@dataclass
class UserProfile:
    uid: str
    username: str
    role: str
    branches: list[str] = field(default_factory=list)
    active_branch: str = ""
    permission_context: PermissionContext = field(default_factory=PermissionContext)
    area_id: str = ""
    area_manager_id: str = ""
    assigned_branch_ids: list[str] = field(default_factory=list)
    must_change_password: bool = False
    is_active: bool = True
    temporary_manager: bool = False

    @classmethod
    def from_permission_context(cls, ctx: PermissionContext) -> UserProfile:
        return cls(
            uid=str(ctx.user_id or ctx.username or "").strip(),
            username=str(ctx.username or ctx.user_id or "").strip(),
            role=ctx.role,
            branches=list(ctx.scope.branches or []),
            active_branch=str(ctx.active_branch or "").strip(),
            permission_context=ctx,
            area_id=str(ctx.area_id or "").strip(),
            area_manager_id=str(ctx.area_manager_id or "").strip(),
            assigned_branch_ids=list(ctx.assigned_branch_ids or []),
            must_change_password=bool(ctx.must_change_password),
            is_active=bool(ctx.is_active),
            temporary_manager=bool(ctx.temporary_manager),
        )

    def to_cloud_user_payload(self) -> dict:
        ctx = (
            self.permission_context
            if isinstance(self.permission_context, PermissionContext)
            else PermissionContext.from_values(self.role, (), self.active_branch)
        )
        payload = {
            "username": self.username,
            "role": self.role,
            "active_branch": str(self.active_branch or ""),
            "uid": self.uid,
            "permissions": list(ctx.permissions or []),
            "scope": {
                "regions": list(
                    getattr(getattr(ctx, "scope", None), "regions", []) or []
                ),
                "areas": list(getattr(getattr(ctx, "scope", None), "areas", []) or []),
                "branches": list(
                    getattr(getattr(ctx, "scope", None), "branches", []) or []
                ),
                "all_regions": bool(
                    getattr(getattr(ctx, "scope", None), "all_regions", False)
                ),
                "all_areas": bool(
                    getattr(getattr(ctx, "scope", None), "all_areas", False)
                ),
                "all_branches": bool(
                    getattr(getattr(ctx, "scope", None), "all_branches", False)
                ),
            },
            "area_id": self.area_id,
            "area_manager_id": self.area_manager_id,
            "permission_source": str(getattr(ctx, "authority_source", "") or ""),
            "authority_revision": int(getattr(ctx, "authority_revision", 0) or 0),
        }
        payload["assigned_branch_ids"] = list(self.assigned_branch_ids or [])
        payload.update(
            must_change_password=bool(self.must_change_password),
            is_active=bool(self.is_active),
            temporary_manager=bool(self.temporary_manager),
        )
        return payload


@dataclass
class AuthSession:
    id_token: str
    uid: str
    role: str
    branches: list[str] = field(default_factory=list)
    active_branch: str = ""
    refresh_token: str = ""
    token_type: str = "bearer"
    expires_in: int = 3600
    permission_context: PermissionContext = field(default_factory=PermissionContext)

    @property
    def branch_scope(self) -> list[str]:
        return list(self.branches or [])
