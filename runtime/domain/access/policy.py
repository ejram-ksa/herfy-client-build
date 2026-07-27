from __future__ import annotations
ALL_PERMISSION = '*'
MANAGED_ROLE_KEYS = ('system', 'region_manager', 'area_manager', 'branch_manager', 'store_user')
BASE_ROLE_LABELS = {'system': 'System Administrator', 'region_manager': 'Regional Manager', 'area_manager': 'Area Manager', 'branch_manager': 'Branch Manager', 'store_user': 'Branch team member'}
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from runtime.shared.booleans import parse_bool

def clean_string_list(values) -> list[str]:
    if values is None:
        return []
    source = values.replace(';', ',').split(',') if isinstance(values, str) else values
    cleaned: list[str] = []
    for item in source:
        text = str(item or '').strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned

def role_labels(language: str) -> dict[str, str]:
    from runtime.application.services.translations import is_rtl, language_entries
    if not is_rtl(language):
        return dict(BASE_ROLE_LABELS)
    entries = language_entries('ar')
    return {role: entries.get(label, label) for role, label in BASE_ROLE_LABELS.items()}

@dataclass(frozen=True)
class PermissionScope:
    regions: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()
    branches: tuple[str, ...] = ()
    all_regions: bool = False
    all_areas: bool = False
    all_branches: bool = False

def normalize_role(role: str | None) -> str:
    normalized = str(role or '').strip().lower().replace('-', '_').replace(' ', '_')
    if normalized in ('', 'store', 'branch', 'user', 'employee', 'crew', 'branch_user'):
        return 'store_user'
    if normalized in ('store_user', 'store'):
        return 'store_user'
    if normalized in ('admin', 'super', 'superuser', 'root'):
        return 'system'
    if normalized in ('regional_manager', 'region_manager', 'region', 'regional'):
        return 'region_manager'
    if normalized in ('area', 'supervisor'):
        return 'area_manager'
    if normalized in ('branch_manager', 'store_manager', 'manager'):
        return 'branch_manager'
    if normalized in MANAGED_ROLE_KEYS:
        return normalized
    return 'store_user'

def match_scope(values: Iterable[str], value: str) -> bool:
    lookup = str(value or '').strip().lower()
    return bool(lookup) and any((str(item).strip().lower() == lookup for item in values))

def permission_scope_from_payload(scope_payload: dict[str, Any]) -> PermissionScope:
    """Build scope only from the explicit server authority payload."""
    return PermissionScope(regions=tuple(clean_string_list(scope_payload.get('regions'))), areas=tuple(clean_string_list(scope_payload.get('areas'))), branches=tuple(clean_string_list(scope_payload.get('branches'))), all_regions=parse_bool(scope_payload.get('all_regions'), False), all_areas=parse_bool(scope_payload.get('all_areas'), False), all_branches=parse_bool(scope_payload.get('all_branches'), False))

def permissions_from_payload(permissions: Iterable[Any] | None) -> tuple[str, ...]:
    """Return only permission codes supplied by the authenticated server."""
    return tuple(clean_string_list(permissions))

def identity_matches(ctx, user_payload: dict[str, Any]) -> bool:
    own_ids = {str(getattr(ctx, 'user_id', '') or '').strip(), str(getattr(ctx, 'username', '') or '').strip()}
    target_ids = {str(user_payload.get('username') or '').strip(), str(user_payload.get('user_id') or user_payload.get('uid') or '').strip()}
    own_ids.discard('')
    target_ids.discard('')
    return bool(own_ids and target_ids and own_ids.intersection(target_ids))

def scope_candidates(data: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    branch_candidates = clean_string_list(data.get('branch_scope') or data.get('assigned_branch_ids') or data.get('branches') or ([data.get('branch_id')] if data.get('branch_id') else []))
    area_candidates = clean_string_list(data.get('area_scope') or ([data.get('area_id')] if data.get('area_id') else []))
    region_candidates = clean_string_list(data.get('region_scope') or ([data.get('region_id')] if data.get('region_id') else []))
    return (branch_candidates, area_candidates, region_candidates)

def can_view_user_record(ctx, user_payload: dict[str, Any] | None) -> bool:
    if not getattr(ctx, 'is_active', False):
        return False
    data = user_payload if isinstance(user_payload, dict) else {}
    if identity_matches(ctx, data):
        return True
    if ctx.has_permission(ALL_PERMISSION):
        return True
    branch_candidates, area_candidates, region_candidates = scope_candidates(data)
    if ctx.has_permission('users.view'):
        if branch_candidates and any((ctx.can_access_branch(branch) for branch in branch_candidates)):
            return True
        if area_candidates and any((ctx.can_access_area(area) for area in area_candidates)):
            return True
        return bool(region_candidates and any((ctx.can_access_region(region) for region in region_candidates)))
    if ctx.has_permission('users.view.assigned'):
        if branch_candidates and any((ctx.can_access_branch(branch) for branch in branch_candidates)):
            return True
        if area_candidates and any((ctx.can_access_area(area) for area in area_candidates)):
            return True
        if region_candidates and any((ctx.can_access_region(region) for region in region_candidates)):
            return True
    if ctx.has_permission('users.view.branch'):
        if branch_candidates and any((ctx.can_access_branch(branch) for branch in branch_candidates)):
            return True
        if area_candidates and any((ctx.can_access_area(area) for area in area_candidates)):
            return True
    if ctx.has_permission('users.view.area'):
        if area_candidates and any((ctx.can_access_area(area) for area in area_candidates)):
            return True
        if region_candidates and any((ctx.can_access_region(region) for region in region_candidates)):
            return True
    return bool(ctx.has_permission('users.view.region') and region_candidates and any((ctx.can_access_region(region) for region in region_candidates)))

@dataclass
class PermissionContext:
    user_id: str = ''
    username: str = ''
    role: str = 'store_user'
    permissions: tuple[str, ...] = ()
    scope: PermissionScope = field(default_factory=PermissionScope)
    region_id: str = ''
    area_id: str = ''
    area_manager_id: str = ''
    assigned_branch_ids: tuple[str, ...] = ()
    must_change_password: bool = False
    is_active: bool = True
    temporary_manager: bool = False
    active_branch: str = ''
    authority_source: str = ''
    authority_revision: int = 0

    @property
    def branches(self) -> tuple[str, ...]:
        return tuple(self.scope.branches or ())

    @property
    def areas(self) -> tuple[str, ...]:
        return tuple(self.scope.areas or ())

    @property
    def regions(self) -> tuple[str, ...]:
        return tuple(self.scope.regions or ())

    def has_permission(self, permission: str) -> bool:
        perm = str(permission or '').strip()
        if not self.is_active:
            return False
        if ALL_PERMISSION in self.permissions:
            return True
        return perm in self.permissions

    def can_view_all_branches(self) -> bool:
        return bool(self.is_active and self.scope.all_branches)

    def _can_access_scope(self, value: str | None, *, all_scope: bool, scope_values: Iterable[str]) -> bool:
        if not self.is_active:
            return False
        normalized = str(value or '').strip()
        if not normalized:
            return False
        return all_scope or match_scope(scope_values, normalized)

    def _can_use_branch_permission(self, branch: str | None, permission: str) -> bool:
        return self.can_access_branch(branch) and self.has_permission(permission)

    def can_access_region(self, region_id: str | None) -> bool:
        return self._can_access_scope(region_id, all_scope=self.scope.all_regions, scope_values=self.scope.regions)

    def can_access_branch(self, branch: str | None) -> bool:
        return self._can_access_scope(branch, all_scope=self.scope.all_branches, scope_values=self.scope.branches)

    def can_view_branch(self, branch: str | None) -> bool:
        return self._can_use_branch_permission(branch, 'branches.view')

    def can_create_tracking(self, branch: str | None) -> bool:
        return self._can_use_branch_permission(branch, 'tracking.create')

    def can_update_tracking(self, branch: str | None) -> bool:
        return self._can_use_branch_permission(branch, 'tracking.update')

    def can_delete_tracking(self, branch: str | None) -> bool:
        return self._can_use_branch_permission(branch, 'tracking.delete')

    def can_access_area(self, area_id: str | None) -> bool:
        return self._can_access_scope(area_id, all_scope=self.scope.all_areas, scope_values=self.scope.areas)

    def can_manage_area(self, area_id: str | None) -> bool:
        return self.can_access_area(area_id) and self.can_manage_org()

    def can_manage_branch(self, branch_id: str | None, *, area_id: str='') -> bool:
        branch = str(branch_id or '').strip()
        area = str(area_id or '').strip()
        if not self.can_manage_org():
            return False
        if branch and self.can_access_branch(branch):
            return True
        if area:
            return self.can_access_area(area)
        return False

    def can_view_user_record(self, user_payload: dict[str, Any] | None) -> bool:
        return can_view_user_record(self, user_payload)

    def can_reset_user_password(self, *, target_username: str='', target_area_id: str='', target_branch_id: str='', target_role: str='') -> bool:
        if not self.is_active:
            return False
        own_ids = {str(self.user_id or '').strip(), str(self.username or '').strip()}
        target_ids = {str(target_username or '').strip()}
        own_ids.discard('')
        target_ids.discard('')
        if own_ids and target_ids and own_ids.intersection(target_ids):
            return self.can_change_own_password() or self.has_permission('users.reset_password.scope')
        if self.has_permission('users.reset_password.any') or self.has_permission(ALL_PERMISSION):
            return True
        if not self.has_permission('users.reset_password.scope'):
            return False
        del target_role
        branch = str(target_branch_id or '').strip()
        area = str(target_area_id or '').strip()
        if branch:
            return self.can_access_branch(branch)
        if area:
            return self.can_access_area(area)
        return False

    def has_any_permission(self, *permissions: str) -> bool:
        return any((self.has_permission(permission) for permission in permissions))

    def can_manage_catalog(self) -> bool:
        return self.has_any_permission('catalog.manage', ALL_PERMISSION)

    def can_manage_usage(self) -> bool:
        return self.has_any_permission('usage.manage', ALL_PERMISSION)

    def can_manage_org(self) -> bool:
        return self.has_any_permission('regions.view', 'regions.manage', 'areas.manage', 'branches.manage', 'branches.assign_manager', 'areas.assign_manager', ALL_PERMISSION)

    def can_change_own_password(self) -> bool:
        return self.has_any_permission('password.change.self', ALL_PERMISSION)

    def is_single_branch_scope(self) -> bool:
        return len(self.scope.branches) == 1 and (not self.scope.all_branches)

    def default_branch(self) -> str:
        active = str(self.active_branch or '').strip()
        if active and active.lower() != 'all' and self.can_access_branch(active):
            return active
        if len(self.scope.branches) == 1:
            return str(self.scope.branches[0]).strip()
        return ''

    def role_label(self, language: str='en') -> str:
        return role_labels(language).get(self.role, self.role.replace('_', ' ').strip().title())

    def can_create_user_role(self, target_role: str) -> bool:
        role = normalize_role(target_role)
        if not self.is_active:
            return False
        if self.has_permission(ALL_PERMISSION):
            return role in MANAGED_ROLE_KEYS
        if role == 'region_manager':
            return self.has_permission('users.create.region_manager')
        if role == 'branch_manager':
            return self.has_permission('users.create.branch_manager')
        if role == 'store_user':
            return self.has_permission('users.create.store_user') or self.has_permission('users.create.branch_manager')
        if role == 'area_manager':
            return self.has_permission('users.create.area_manager')
        return False

    def to_payload(self) -> dict[str, Any]:
        return {'user_id': self.user_id, 'username': self.username, 'role': self.role, 'permissions': list(self.permissions or []), 'scope': {'regions': list(self.scope.regions or []), 'areas': list(self.scope.areas or []), 'branches': list(self.scope.branches or []), 'all_regions': bool(self.scope.all_regions), 'all_areas': bool(self.scope.all_areas), 'all_branches': bool(self.scope.all_branches)}, 'region_id': self.region_id, 'area_id': self.area_id, 'area_manager_id': self.area_manager_id, 'assigned_branch_ids': list(self.assigned_branch_ids or []), 'must_change_password': bool(self.must_change_password), 'is_active': bool(self.is_active), 'temporary_manager': bool(self.temporary_manager), 'active_branch': self.active_branch, 'permission_source': self.authority_source, 'authority_revision': int(self.authority_revision or 0)}

    @staticmethod
    def from_values(role: str | None, allowed_branches: Iterable[str] | None, active_branch: str | None) -> PermissionContext:
        """Create a descriptive, fail-closed context without local authority.

        Older callers may still provide role/branch display values, but neither
        value grants permissions or organizational scope.
        """
        del allowed_branches
        return PermissionContext(role=normalize_role(role), permissions=(), scope=PermissionScope(), assigned_branch_ids=(), active_branch=str(active_branch or '').strip(), authority_source='local.none', authority_revision=0)

    @staticmethod
    def from_payload(payload: dict[str, Any] | None, *, active_branch: str | None=None) -> PermissionContext:
        data = payload if isinstance(payload, dict) else {}
        role_norm = normalize_role(data.get('role'))
        authority_source = str(data.get('permission_source') or '').strip()
        raw_scope = data.get('scope')
        raw_permissions = data.get('permissions')
        authority_valid = authority_source == 'postgresql.role_permissions' and isinstance(raw_scope, dict) and isinstance(raw_permissions, (list, tuple, set))
        scope = permission_scope_from_payload(raw_scope) if authority_valid else PermissionScope()
        permissions = permissions_from_payload(raw_permissions) if authority_valid else ()
        active_value = str(data.get('active_branch') or active_branch or (scope.branches[0] if len(scope.branches) == 1 else '')).strip()
        if active_value.lower() == 'all':
            active_value = ''
        assigned = tuple(clean_string_list(data.get('assigned_branch_ids') or scope.branches) if authority_valid else [])
        try:
            authority_revision = int(data.get('authority_revision') or 0)
        except (TypeError, ValueError):
            authority_revision = 0
        return PermissionContext(user_id=str(data.get('user_id') or data.get('uid') or data.get('username') or '').strip(), username=str(data.get('username') or data.get('uid') or data.get('user_id') or '').strip(), role=role_norm, permissions=permissions, scope=scope, region_id=str(data.get('region_id') or (scope.regions[0] if len(scope.regions) == 1 else '') or '').strip(), area_id=str(data.get('area_id') or '').strip(), area_manager_id=str(data.get('area_manager_id') or '').strip(), assigned_branch_ids=assigned, must_change_password=parse_bool(data.get('must_change_password'), False), is_active=parse_bool(data.get('is_active'), True), temporary_manager=parse_bool(data.get('temporary_manager'), False) or data.get('status') == 'temporary_manager', active_branch=active_value, authority_source=authority_source if authority_valid else '', authority_revision=authority_revision if authority_valid else 0)

class PermissionService:

    @staticmethod
    def context(role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None, permission_context: PermissionContext | None=None) -> PermissionContext:
        if isinstance(permission_context, PermissionContext):
            return permission_context
        return PermissionContext.from_values(role, allowed_branches, active_branch)

    @staticmethod
    def has_permission(permission: str, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).has_permission(permission)

    @staticmethod
    def can_view_all(permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_view_all_branches()

    @staticmethod
    def can_access_branch(branch: str | None, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_access_branch(branch)

    @staticmethod
    def can_view_branch(branch: str | None, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_view_branch(branch)

    @staticmethod
    def can_create_tracking(branch: str | None, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_create_tracking(branch)

    @staticmethod
    def can_update_tracking(branch: str | None, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_update_tracking(branch)

    @staticmethod
    def can_delete_tracking(branch: str | None, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_delete_tracking(branch)

    @staticmethod
    def can_reset_user_password(*, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None, target_username: str='', target_area_id: str='', target_branch_id: str='', target_role: str='') -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_reset_user_password(target_username=target_username, target_area_id=target_area_id, target_branch_id=target_branch_id, target_role=target_role)

    @staticmethod
    def can_manage_catalog(*, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_manage_catalog()

    @staticmethod
    def can_manage_usage(*, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_manage_usage()

    @staticmethod
    def can_manage_org(*, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_manage_org()

    @staticmethod
    def can_change_own_password(*, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_change_own_password()

    @staticmethod
    def is_single_branch_scope(*, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).is_single_branch_scope()

    @staticmethod
    def default_branch(*, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> str:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).default_branch()

    @staticmethod
    def role_label(*, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None, language: str='en') -> str:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).role_label(language)

    @staticmethod
    def can_create_user_role(target_role: str, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_create_user_role(target_role)

    @staticmethod
    def can_access_area(area_id: str | None, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_access_area(area_id)

    @staticmethod
    def can_manage_area(area_id: str | None, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_manage_area(area_id)

    @staticmethod
    def can_manage_branch(branch_id: str | None, *, area_id: str='', permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_manage_branch(branch_id, area_id=area_id)

    @staticmethod
    def can_view_user_record(user_payload: dict | None, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> bool:
        return PermissionService.context(role, allowed_branches, active_branch, permission_context).can_view_user_record(user_payload)

    @staticmethod
    def filter_visible_users(users: Iterable[dict] | None, *, permission_context: PermissionContext | None=None, role: str | None=None, allowed_branches: Iterable[str] | None=None, active_branch: str | None=None) -> list[dict]:
        ctx = PermissionService.context(role, allowed_branches, active_branch, permission_context)
        return [dict(item) for item in users or [] if ctx.can_view_user_record(item if isinstance(item, dict) else {})]
__all__ = ['ALL_PERMISSION', 'BASE_ROLE_LABELS', 'MANAGED_ROLE_KEYS', 'PermissionScope', 'PermissionContext', 'PermissionService', 'can_view_user_record', 'clean_string_list', 'identity_matches', 'match_scope', 'normalize_role', 'permissions_from_payload', 'permission_scope_from_payload', 'role_labels', 'scope_candidates']
