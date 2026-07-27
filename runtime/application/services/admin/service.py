from __future__ import annotations
import logging
from typing import Any, ClassVar
from runtime.shared.strings import clean_text
logger = logging.getLogger(__name__)
ADMIN_CACHE_PREFIXES = ('meta_', 'admin_', 'items:', 'alerts:')

def invalidate_admin_cache(cloud: Any) -> None:
    if cloud is None:
        return
    for prefix in ADMIN_CACHE_PREFIXES:
        try:
            cloud._invalidate_prefix(prefix)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Admin cache invalidation skipped for prefix %s', prefix, exc_info=True)

def emit_admin_event(state: Any, action: str, payload: Any=None) -> None:
    if state is None:
        return
    normalized_action = str(action or '').strip().lower()
    data = dict(payload or {})
    data.setdefault('action', normalized_action)
    if normalized_action == 'delete':
        state.emit_item_deleted('admin', data)
    else:
        state.emit_item_updated('admin', data)

class AdminCloudServiceBase:

    def __init__(self, cloud_service: Any=None, *, app_state: Any=None) -> None:
        self.cloud_service = cloud_service
        self.app_state = app_state

    def set_cloud_service(self, cloud_service: Any) -> None:
        self.cloud_service = cloud_service

    def _require_cloud(self) -> Any:
        if self.cloud_service is None:
            raise RuntimeError('Admin service is not connected to the cloud client.')
        return self.cloud_service

    @staticmethod
    def _clean_token(value: Any) -> str:
        return clean_text(value)

    def _change_payload(self, *, kind: str, scope_id: Any | None=None, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {'kind': self._clean_token(kind)}
        scope = self._clean_token(scope_id)
        if scope:
            payload['scope_id'] = scope
        for key, value in extra.items():
            cleaned = self._clean_token(value)
            if cleaned:
                payload[str(key)] = cleaned
        return payload

    def invalidate_admin_cache(self) -> None:
        invalidate_admin_cache(self.cloud_service)

    def _emit_admin_event(self, action: str, payload: dict[str, Any] | None=None) -> None:
        emit_admin_event(self.app_state, action, dict(payload or {}))

    def _record_admin_change(self, action: str, payload: dict[str, Any] | None=None) -> None:
        self.invalidate_admin_cache()
        self._emit_admin_event(action, payload)

    def _record_scope_change(self, action: str, *, kind: str, scope_id: Any | None=None, payload_action: str | None=None, **extra: Any) -> None:
        if payload_action:
            extra['action'] = payload_action
        self._record_admin_change(action, self._change_payload(kind=kind, scope_id=scope_id, **extra))

def parse_bulk_branch_lines(lines_in: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for line in lines_in:
        text = str(line or '').strip()
        if not text:
            continue
        parts = [part.strip() for part in text.split(',', 1)]
        branch_id = parts[0]
        branch_name = parts[1] if len(parts) > 1 else parts[0]
        if branch_id:
            parsed.append((branch_id, branch_name or branch_id))
    return parsed
from runtime.shared.objects import clean_string_list
from runtime.shared.booleans import parse_bool
from runtime.domain.access import PermissionContext, PermissionService, normalize_role
FULL_SYSTEM_ADMIN_CAPABILITIES: tuple[str, ...] = ('structure.view', 'structure.write', 'structure.create.region', 'structure.create.area', 'structure.create.branch', 'structure.delete', 'structure.bulk_branches', 'users.view', 'users.create', 'users.delete', 'users.reset_password', 'permissions.view', 'permissions.edit')

def _current_user_has_full_admin(payload: dict[str, Any]) -> bool:
    permissions = {str(item or '').strip() for item in payload.get('permissions') or []}
    return '*' in permissions

def _server_contract_warnings(snapshot: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    regions = list(snapshot.get('regions') or [])
    areas = list(snapshot.get('areas') or [])
    branches = list(snapshot.get('branches') or [])
    if branches and (not regions):
        warnings.append('Server returned branch records without Region records. Create or sync Regions on the server.')
    if branches and (not areas):
        warnings.append('Server returned branch records without Area records. Create or sync Areas on the server before assigning branches.')
    if areas and (not regions):
        warnings.append('Server returned Area records without Region records. Link every Area to a Region on the server.')
    return warnings

class AdminPermissionsService(AdminCloudServiceBase):

    def current_user_payload(self) -> dict[str, Any]:
        payload = getattr(self._require_cloud(), 'user', {}) or {}
        return dict(payload) if isinstance(payload, dict) else {}

    def permission_context(self) -> PermissionContext:
        return PermissionContext.from_payload(self.current_user_payload())

    def filter_visible_users(self, users: list[dict[str, Any]], permission_context: PermissionContext) -> list[dict[str, Any]]:
        return list(PermissionService.filter_visible_users(users, permission_context=permission_context) or [])

    def set_role_permissions(self, role_key: str, permissions: list[str]) -> dict[str, Any]:
        role = str(role_key or '').strip()
        if not role:
            raise ValueError('Please select a role first.')
        cloud = self._require_cloud()
        result = dict(cloud.admin_set_role_permissions(role, clean_string_list(permissions)) or {})
        self._record_scope_change('upsert', kind='role_permissions', scope_id=role)
        return result
from collections.abc import Iterable
from dataclasses import dataclass
from runtime.shared.settings.config import _

@dataclass(frozen=True)
class StructureFormState:
    kind: str
    existing: bool
    field_labels: tuple[str, str, str, str]
    code: str
    name: str
    role_items: list[tuple[str, str]]
    scope_items: list[tuple[str, str]]
    scope_value: str
    manager_role: str
    manager_value: str
    summary_text: str
    is_active: bool
    id_read_only: bool

@dataclass(frozen=True)
class StructureSavePlan:
    kind: str
    code: str
    name: str
    scope: str
    manager: str
    is_active: bool
    manager_role: str
    manager_required: bool
    success_message: str
    assignment_only: bool
    old_area: str

class AdminStructureService(AdminCloudServiceBase):

    def _fetch_meta_list(self, method_name: str) -> list[dict]:
        method = getattr(self._require_cloud(), method_name)
        return list(method() or [])

    def _fetch_admin_list(self, primary_method: str, fallback_method: str) -> list[dict]:
        cloud = self._require_cloud()
        method = getattr(cloud, primary_method, None)
        if callable(method):
            return list(method() or [])
        return self._fetch_meta_list(fallback_method)

    def fetch_regions(self) -> list[dict]:
        return self._fetch_admin_list('admin_list_regions', 'meta_regions')

    def fetch_areas(self) -> list[dict]:
        return self._fetch_admin_list('admin_list_areas', 'meta_areas')

    def fetch_branches_full(self) -> list[dict]:
        return self._fetch_admin_list('admin_list_branches', 'meta_branches_full')

    def upsert_region(self, region_id: str, name: str) -> dict:
        cloud = self._require_cloud()
        result = dict(cloud.admin_upsert_region(region_id, name) or {})
        self._record_scope_change('upsert', kind='region', scope_id=region_id)
        return result

    def upsert_area(self, area_id: str, name: str, *, region_id: str | None=None) -> dict:
        cloud = self._require_cloud()
        result = dict(cloud.admin_upsert_area(area_id, name, region_id=region_id) or {})
        self._record_scope_change('upsert', kind='area', scope_id=area_id, region_id=region_id)
        return result

    def upsert_branch(self, branch_id: str, area_id: str, name: str | None=None, **extra) -> dict:
        cloud = self._require_cloud()
        result = dict(cloud.admin_upsert_branch(branch_id, area_id, name, **extra) or {})
        self._record_scope_change('upsert', kind='branch', scope_id=branch_id, area_id=area_id)
        return result

    def transfer_branch(self, branch_id: str, target_area_id: str, **extra) -> dict:
        cloud = self._require_cloud()
        result = dict(cloud.admin_transfer_branch(branch_id, target_area_id, **extra) or {})
        self._record_scope_change('upsert', kind='branch', scope_id=branch_id, area_id=target_area_id, payload_action='transfer')
        return result

    def assign_manager(self, *, kind: str, scope_id: str, user_id: str | None, temporary_manager: bool=False) -> dict:
        cloud = self._require_cloud()
        kind = str(kind or '').strip().lower()
        scope_id = str(scope_id or '').strip()
        if not scope_id:
            raise ValueError('Scope id is required for manager assignment.')
        if kind == 'region':
            result = dict(cloud.admin_assign_region_manager(scope_id, str(user_id or '').strip()) or {})
            self._record_scope_change('upsert', kind='region', scope_id=scope_id, user_id=user_id)
            return result
        if kind == 'area':
            result = dict(cloud.admin_assign_area_manager(scope_id, str(user_id or '').strip(), temporary_manager=bool(temporary_manager)) or {})
            self._record_scope_change('upsert', kind='area', scope_id=scope_id, user_id=user_id)
            return result
        if kind == 'branch':
            result = dict(cloud.admin_assign_branch_manager(scope_id, str(user_id or '').strip() or None) or {})
            self._record_scope_change('upsert', kind='branch', scope_id=scope_id, user_id=user_id)
            return result
        raise ValueError(f'Unsupported manager assignment kind: {kind}')

    def assign_region_manager(self, region_id: str, user_id: str) -> dict:
        return self.assign_manager(kind='region', scope_id=region_id, user_id=user_id)

    def assign_area_manager(self, area_id: str, user_id: str, temporary_manager: bool=False) -> dict:
        return self.assign_manager(kind='area', scope_id=area_id, user_id=user_id, temporary_manager=temporary_manager)

    def assign_branch_manager(self, branch_id: str, user_id: str | None) -> dict:
        return self.assign_manager(kind='branch', scope_id=branch_id, user_id=user_id)

    def bulk_upsert_branches(self, area_id: str, rows: Iterable[tuple[str, str]], *, is_active: bool=True) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for branch_id, branch_name in rows or []:
            bid = str(branch_id or '').strip()
            bname = str(branch_name or bid).strip()
            if not bid:
                continue
            out.append(self.upsert_branch(bid, str(area_id or '').strip(), bname, is_active=bool(is_active)))
        return out

    def _delete_scope(self, kind: str, scope_id: str, cloud_method_name: str) -> dict:
        cloud = self._require_cloud()
        method = getattr(cloud, cloud_method_name)
        result = dict(method(scope_id) or {})
        self._record_scope_change('delete', kind=kind, scope_id=scope_id)
        return result

    def delete_region(self, region_id: str) -> dict:
        return self._delete_scope('region', region_id, 'admin_delete_region')

    def delete_area(self, area_id: str) -> dict:
        return self._delete_scope('area', area_id, 'admin_delete_area')

    def delete_branch(self, branch_id: str) -> dict:
        return self._delete_scope('branch', branch_id, 'admin_delete_branch')
    FIELD_LABELS: ClassVar[dict[str, tuple[str, str, str, str]]] = {'region': ('Region ID', 'Region Name', 'Scope', 'Region Manager'), 'area': ('Area ID', 'Area Name', 'Parent Region', 'Area Manager'), 'branch': ('Branch ID', 'Branch Name', 'Parent Area', 'Branch Manager')}
    SUMMARY_TEXT: ClassVar[dict[str, str]] = {'region': 'Enter the Region ID and name, then assign the Regional Manager.', 'area': 'Choose the parent Region, then assign the Area Manager.', 'branch': 'Choose the parent Area, then assign the Branch Manager.'}
    ROLE_ITEMS: ClassVar[dict[str, tuple[tuple[str, str], ...]]] = {'region': (('Region Manager', 'region_manager'),), 'area': (('Area Manager', 'area_manager'),), 'branch': (('Branch Manager', 'branch_manager'),)}
    MANAGER_FIELD: ClassVar[dict[str, tuple[str, str]]] = {'region': ('region_manager', 'region_manager_id'), 'area': ('area_manager', 'area_manager_id'), 'branch': ('branch_manager', 'branch_manager_id')}

    def prepare_new_scope(self, kind: str, selected_kind: str, selected_payload: dict[str, Any] | None) -> str:
        payload = selected_payload if isinstance(selected_payload, dict) else {}
        selected_kind = str(selected_kind or '').strip()
        kind = str(kind or 'region').strip().lower()
        if kind == 'area' and selected_kind == 'region':
            return str(payload.get('region_id') or '').strip()
        if kind == 'branch' and selected_kind in {'area', 'branch'}:
            return str(payload.get('area_id') or '').strip()
        return ''

    def build_form_state(self, kind: str, payload: dict[str, Any] | None, *, regions: Iterable[dict[str, Any]] | None, areas: Iterable[dict[str, Any]] | None) -> StructureFormState:
        kind = str(kind or 'region').strip().lower()
        payload = payload if isinstance(payload, dict) else {}
        existing = bool(payload)
        field_labels = self.FIELD_LABELS.get(kind, ('ID', 'Name', 'Scope', 'Manager'))
        role_items = list(self.ROLE_ITEMS.get(kind, [('System', 'system')]))
        manager_role, manager_key = self.MANAGER_FIELD.get(kind, ('', 'manager_id'))
        if kind == 'region':
            code = str(payload.get('region_id') or '').strip()
            name = str(payload.get('name') or code).strip()
            scope_items = [('All Regions', '*')]
            scope_value = '*'
        elif kind == 'area':
            code = str(payload.get('area_id') or '').strip()
            name = str(payload.get('name') or code).strip()
            scope_value = str(payload.get('region_id') or '').strip()
            scope_items = []
            for region in regions or []:
                region_id = str((region or {}).get('region_id') or '').strip()
                if region_id:
                    scope_items.append((f"{region_id} — {(region or {}).get('name') or region_id}", region_id))
        elif kind == 'branch':
            code = str(payload.get('branch_id') or '').strip()
            name = str(payload.get('name') or code).strip()
            scope_value = str(payload.get('area_id') or '').strip()
            scope_items = []
            for area in areas or []:
                area_id = str((area or {}).get('area_id') or '').strip()
                region_id = str((area or {}).get('region_id') or '').strip()
                if area_id:
                    scope_items.append((f"{area_id} — {(area or {}).get('name') or area_id} ({region_id or 'No Region'})", area_id))
        else:
            code = ''
            name = ''
            scope_items = [('All', '*')]
            scope_value = '*'
        manager_value = str(payload.get(manager_key) or payload.get('manager_id') or '').strip()
        is_active = parse_bool(payload.get('is_active'), True)
        summary_text = self.SUMMARY_TEXT.get(kind, '')
        return StructureFormState(kind=kind, existing=existing, field_labels=field_labels, code=code, name=name, role_items=role_items, scope_items=scope_items, scope_value=scope_value, manager_role=manager_role, manager_value=manager_value, summary_text=summary_text, is_active=is_active, id_read_only=existing)

    def extract_structure_code(self, kind: str, payload: dict[str, Any] | None, fallback_text: str='') -> str:
        payload = payload if isinstance(payload, dict) else {}
        key = {'region': 'region_id', 'area': 'area_id', 'branch': 'branch_id'}.get(str(kind or '').strip(), '')
        return str(payload.get(key) or fallback_text or '').strip()

    def build_delete_confirmation(self, kind: str, code: str, areas: Iterable[dict[str, Any]], branches: Iterable[dict[str, Any]]) -> str:
        kind = str(kind or '').strip()
        code = str(code or '').strip()
        area_rows = [row for row in areas or [] if isinstance(row, dict)]
        branch_rows = [row for row in branches or [] if isinstance(row, dict)]
        child_msg = ''
        if kind == 'region':
            child_msg = _('\n\nRelated records found: {areas} area(s), {branches} restaurant branch(es).').format(areas=len(area_rows), branches=len(branch_rows))
        elif kind == 'area':
            child_msg = _('\n\nRelated records found: {branches} restaurant branch(es).').format(branches=len(branch_rows))
        return _('Are you sure you want to delete this {kind}?\n\nID: {code}{child_msg}').format(kind=_(kind.title() if kind != 'branch' else 'Restaurant branch'), code=code, child_msg=child_msg)

    def permission_denied_message(self, current_role: str) -> str:
        current_role = normalize_role(current_role)
        if current_role == 'region_manager':
            return _('Region Manager has view-only administration access.')
        if current_role == 'area_manager':
            return _('Area Manager can assign Branch Managers only and cannot create or modify Regions or Areas.')
        return _('You do not have permission to modify this structure from the current scope.')

    def build_save_plan(self, *, kind: str, code: str, name: str, scope: str, manager: str, is_active: bool, editing_existing: bool, structure_exists: bool, current_role: str, old_area: str='') -> StructureSavePlan:
        kind = str(kind or '').strip().lower()
        code = str(code or '').strip()
        name = str(name or code).strip()
        scope = str(scope or '').strip()
        manager = str(manager or '').strip()
        current_role = normalize_role(current_role)
        if not code:
            raise ValueError('Please enter the structure ID first.')
        if not editing_existing and structure_exists:
            raise FileExistsError(f"{kind.title()} '{code}' already exists.")
        if kind == 'region':
            return StructureSavePlan(kind, code, name, scope or '*', manager, bool(is_active), 'region_manager', False, 'Region saved and synchronized with server.', False, '')
        if kind == 'area':
            if not scope or scope == '*':
                raise ValueError('Please select the parent Region before saving the Area.')
            return StructureSavePlan(kind, code, name, scope, manager, bool(is_active), 'area_manager', False, 'Area saved under the selected Region and synchronized with server.', False, '')
        if kind == 'branch':
            if not scope or scope == '*':
                raise ValueError('Please select the parent Area before saving the Branch.')
            assignment_only = current_role == 'area_manager'
            return StructureSavePlan(kind, code, name, scope, manager, bool(is_active), 'branch_manager', assignment_only, 'Branch Manager assignment synchronized with server.' if assignment_only else 'Branch saved under the selected Area and synchronized with server.', assignment_only, str(old_area or '').strip())
        raise ValueError('Please select a Region, Area, or Branch.')

class AdminUserService(AdminCloudServiceBase):

    def list_users(self) -> list[dict[str, Any]]:
        cloud = self._require_cloud()
        return list(cloud.admin_list_users() or [])

    def upsert_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        cloud = self._require_cloud()
        result = dict(cloud.admin_upsert_user(payload) or {})
        self._record_scope_change('upsert', kind='user', username=(payload or {}).get('username'))
        return result

    def reset_password(self, username: str, temporary_password: str) -> dict[str, Any]:
        cloud = self._require_cloud()
        clean_password = str(temporary_password or '').strip()
        if not clean_password:
            raise ValueError('A temporary password is required')
        if len(clean_password) < 8:
            raise ValueError('Temporary password must contain at least 8 characters.')
        result = dict(cloud.admin_reset_password(username, clean_password) or {})
        self._record_scope_change('upsert', kind='user', username=username, payload_action='reset_password')
        return result

    def delete_user(self, username: str) -> dict[str, Any]:
        cloud = self._require_cloud()
        result = dict(cloud.admin_delete_user(username) or {})
        self._record_scope_change('delete', kind='user', username=username)
        return result
import threading
import time
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.concurrency import wait_for_inflight_event

class AdminDashboardUnavailable(RuntimeError):
    """Raised when the cloud client has no admin dashboard endpoint."""

class AdminService:

    def __init__(self, cloud_service: Any, app_state: Any=None):
        self.cloud_service = cloud_service
        self.app_state = app_state
        self.structure = AdminStructureService(cloud_service, app_state=app_state)
        self.users = AdminUserService(cloud_service, app_state=app_state)
        self.permissions = AdminPermissionsService(cloud_service, app_state=app_state)
        self._snapshot_lock = threading.RLock()
        self._snapshot_cache: tuple[float, tuple[Any, ...], dict[str, Any]] | None = None
        self._snapshot_ttl_seconds = 1.5
        self._snapshot_event: threading.Event | None = None

    def invalidate_admin_cache(self) -> None:
        self.structure.invalidate_admin_cache()
        with self._snapshot_lock:
            self._snapshot_cache = None

    @staticmethod
    def _permission_cache_key(ctx: PermissionContext) -> tuple[Any, ...]:
        scope = getattr(ctx, 'scope', None)
        return (normalize_role(getattr(ctx, 'role', '')), str(getattr(ctx, 'user_id', '') or '').strip().lower(), bool(getattr(ctx, 'is_active', False)), tuple(sorted((str(item).strip().lower() for item in getattr(ctx, 'regions', ()) if str(item).strip()))), tuple(sorted((str(item).strip().lower() for item in getattr(ctx, 'areas', ()) if str(item).strip()))), tuple(sorted((str(item).strip().lower() for item in getattr(ctx, 'branches', ()) if str(item).strip()))), bool(getattr(scope, 'all_regions', False)), bool(getattr(scope, 'all_areas', False)), bool(getattr(scope, 'all_branches', False)))

    @staticmethod
    def _copy_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
        snap = snapshot if isinstance(snapshot, dict) else {}
        return {'regions': list(snap.get('regions') or []), 'areas': list(snap.get('areas') or []), 'branches': list(snap.get('branches') or []), 'users': list(snap.get('users') or []), 'roles': list(snap.get('roles') or []), 'allowed_role_keys': clean_string_list(snap.get('allowed_role_keys') or []), 'permission_templates': dict(snap.get('permission_templates') or {}), 'permission_catalog': list(snap.get('permission_catalog') or []), 'capabilities': clean_string_list(snap.get('capabilities') or []), 'contract': str(snap.get('contract') or ''), 'structure_mutation_contract_ready': parse_bool(snap.get('structure_mutation_contract_ready'), False), 'source': str(snap.get('source') or ''), 'read_only': parse_bool(snap.get('read_only'), False), 'read_only_reason': str(snap.get('read_only_reason') or ''), 'server_contract_warnings': list(snap.get('server_contract_warnings') or [])}

    def _load_admin_rows(self, label: str, loader) -> list[dict[str, Any]]:
        try:
            return list(loader() or [])
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            detail = str(exc or '').strip()
            if detail:
                raise RuntimeError(f'{label} could not be loaded from the server. {detail}') from exc
            raise RuntimeError(f'{label} could not be loaded from the server.') from exc

    def _filter_fallback_snapshot_for_context(self, snapshot: dict[str, Any], ctx: PermissionContext) -> dict[str, Any]:
        """Fail-closed filtering based only on explicit server scope."""
        regions = list(snapshot.get('regions') or [])
        areas = list(snapshot.get('areas') or [])
        branches = list(snapshot.get('branches') or [])
        users = list(snapshot.get('users') or [])
        scope = getattr(ctx, 'scope', None)
        allowed_regions = {str(value).strip().lower() for value in getattr(scope, 'regions', ()) or () if str(value).strip()}
        allowed_areas = {str(value).strip().lower() for value in getattr(scope, 'areas', ()) or () if str(value).strip()}
        allowed_branches = {str(value).strip().lower() for value in getattr(scope, 'branches', ()) or () if str(value).strip()}
        all_regions = bool(getattr(scope, 'all_regions', False))
        all_areas = bool(getattr(scope, 'all_areas', False))
        all_branches = bool(getattr(scope, 'all_branches', False))
        if not all_branches:
            branches = [row for row in branches if str(row.get('branch_id') or '').strip().lower() in allowed_branches]
        branch_area_ids = {str(row.get('area_id') or '').strip().lower() for row in branches if str(row.get('area_id') or '').strip()}
        effective_area_ids = allowed_areas | branch_area_ids
        if not all_areas:
            areas = [row for row in areas if str(row.get('area_id') or '').strip().lower() in effective_area_ids]
        area_region_ids = {str(row.get('region_id') or '').strip().lower() for row in areas if str(row.get('region_id') or '').strip()}
        branch_region_ids = {str(row.get('region_id') or '').strip().lower() for row in branches if str(row.get('region_id') or '').strip()}
        effective_region_ids = allowed_regions | area_region_ids | branch_region_ids
        if not all_regions:
            regions = [row for row in regions if str(row.get('region_id') or '').strip().lower() in effective_region_ids]
        snapshot['regions'] = regions
        snapshot['areas'] = areas
        snapshot['branches'] = branches
        snapshot['users'] = self.permissions.filter_visible_users(users, permission_context=ctx)
        return snapshot

    def _fallback_metadata_snapshot(self, ctx: PermissionContext) -> dict[str, Any]:
        snapshot = {'regions': self._load_admin_rows('Regions', self.structure.fetch_regions), 'areas': self._load_admin_rows('Areas', self.structure.fetch_areas), 'branches': self._load_admin_rows('Branches', self.structure.fetch_branches_full), 'users': self._load_admin_rows('Users', self.users.list_users), 'roles': [], 'allowed_role_keys': [], 'permission_templates': {}, 'permission_catalog': [], 'capabilities': [], 'source': 'local_metadata_fallback', 'read_only': True, 'read_only_reason': 'Server administration dashboard endpoint is unavailable; showing metadata in read-only mode.'}
        return self._filter_fallback_snapshot_for_context(snapshot, ctx)

    def _authoritative_dashboard_snapshot(self) -> dict[str, Any]:
        cloud = self.cloud_service
        dashboard = getattr(cloud, 'admin_dashboard', None)
        if not callable(dashboard):
            raise AdminDashboardUnavailable('Server administration dashboard endpoint is unavailable.')
        snapshot = self._copy_snapshot(dict(dashboard() or {}))
        if snapshot.get('source') != 'admin_dashboard':
            snapshot['source'] = 'admin_dashboard'
        snapshot['read_only'] = parse_bool(snapshot.get('read_only'), False)
        current_user = self.permissions.current_user_payload()
        if _current_user_has_full_admin(current_user):
            capabilities = set(clean_string_list(snapshot.get('capabilities') or []))
            capabilities.update(FULL_SYSTEM_ADMIN_CAPABILITIES)
            capabilities.add('*')
            snapshot['capabilities'] = sorted(capabilities)
        warnings = list(snapshot.get('server_contract_warnings') or [])
        warnings.extend(_server_contract_warnings(snapshot))
        if warnings:
            snapshot['server_contract_warnings'] = list(dict.fromkeys(warnings))
        return snapshot

    def fetch_dashboard_snapshot(self, *, permission_context=None) -> dict[str, Any]:
        ctx = permission_context or self.permissions.permission_context()
        context_key = self._permission_cache_key(ctx)
        now = time.monotonic()
        with self._snapshot_lock:
            cached = self._snapshot_cache
            if cached is not None and cached[1] == context_key and (now - float(cached[0]) <= float(self._snapshot_ttl_seconds)):
                return self._copy_snapshot(cached[2])
            wait_event = self._snapshot_event
            if wait_event is None:
                wait_event = threading.Event()
                self._snapshot_event = wait_event
                should_load = True
            else:
                should_load = False
        if not should_load:
            wait_for_inflight_event(wait_event, timeout_seconds=8.0, context='AdminService.fetch_dashboard_snapshot')
            with self._snapshot_lock:
                cached = self._snapshot_cache
                if cached is not None and cached[1] == context_key and (time.monotonic() - float(cached[0]) <= float(self._snapshot_ttl_seconds)):
                    return self._copy_snapshot(cached[2])
            logger.debug('Skipped duplicate admin dashboard snapshot fetch while another worker is loading')
            return self._fallback_metadata_snapshot(ctx)
        try:
            try:
                snapshot = self._authoritative_dashboard_snapshot()
            except AdminDashboardUnavailable:
                snapshot = self._fallback_metadata_snapshot(ctx)
            except SERVICE_OPERATION_EXCEPTIONS as exc:
                if int(getattr(exc, 'status_code', 0) or 0) != 404:
                    raise
                snapshot = self._fallback_metadata_snapshot(ctx)
            with self._snapshot_lock:
                self._snapshot_cache = (time.monotonic(), context_key, self._copy_snapshot(snapshot))
            return self._copy_snapshot(snapshot)
        finally:
            with self._snapshot_lock:
                event = self._snapshot_event
                self._snapshot_event = None
            if event is not None:
                event.set()
