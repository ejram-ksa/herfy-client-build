from __future__ import annotations
from typing import Any
from runtime.shared.objects import call_if_callable, clean_string_list
from runtime.application.dto import normalize_area_payload, normalize_branch_payload, normalize_region_payload
from runtime.shared.strings import normalize_text
from runtime.shared.booleans import parse_bool
from runtime.application.dto import normalize_user
import logging
logger = logging.getLogger(__name__)

class AdminPayloadHelpers(object):

    def _invalidate_admin_sync_cache(self) -> None:
        invalidator = getattr(self, '_invalidate_prefix', None)
        if not callable(invalidator):
            return
        for prefix in ('meta_', 'admin_', 'items:', 'alerts:'):
            call_if_callable(invalidator, prefix)

    @staticmethod
    def _clean_scope_values(values: Any) -> list[str]:
        return clean_string_list(values if isinstance(values, list | tuple | set) else [values] if values not in (None, '') else [])

    @staticmethod
    def _user_scope_payload(user: dict[str, Any]) -> dict[str, Any]:
        data = dict(user or {})
        scope = data.get('scope') if isinstance(data.get('scope'), dict) else {}
        regions = data.get('region_ids') or data.get('regions') or data.get('region_scope') or scope.get('regions') or []
        areas = data.get('area_ids') or data.get('areas') or data.get('area_scope') or scope.get('areas') or []
        branches = data.get('branch_ids') or data.get('assigned_branch_ids') or data.get('branch_scope') or data.get('branches') or scope.get('branches') or []
        return {'region_ids': AdminPayloadHelpers._clean_scope_values(regions), 'area_ids': AdminPayloadHelpers._clean_scope_values(areas), 'branch_ids': AdminPayloadHelpers._clean_scope_values(branches)}

    @staticmethod
    def _items_from_admin_payload(data: dict[str, Any], *keys: str) -> list[Any]:
        payload = data if isinstance(data, dict) else {}
        containers = [payload]
        for nested_key in ('data', 'structure', 'dashboard', 'payload'):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                containers.append(nested)
        for container in containers:
            for key in keys:
                items = container.get(key) if isinstance(container, dict) else None
                if isinstance(items, list):
                    return list(items)
        items = payload.get('items') if isinstance(payload, dict) else None
        return list(items) if isinstance(items, list) else []

    @staticmethod
    def _payload_value(data: dict[str, Any], key: str, default: Any=None) -> Any:
        payload = data if isinstance(data, dict) else {}
        for container_key in (None, 'data', 'structure', 'dashboard', 'payload'):
            container = payload if container_key is None else payload.get(container_key)
            if isinstance(container, dict) and key in container:
                return container.get(key)
        return default

    @staticmethod
    def _normalize_permission_template_payload(data: Any) -> dict[str, dict[str, list[str]]]:
        normalized: dict[str, dict[str, list[str]]] = {}

        def _store(role_value: Any, permission_value: Any) -> None:
            role = normalize_text(role_value)
            if not role or role == 'permissions':
                return
            permissions = clean_string_list(permission_value if isinstance(permission_value, list | tuple | set) else [])
            normalized[role] = {'permissions': permissions}
        if isinstance(data, list):
            for item in data:
                row = item if isinstance(item, dict) else {}
                _store(row.get('role') or row.get('role_key') or row.get('key'), row.get('permissions') or row.get('permission_codes') or [])
            return normalized
        if not isinstance(data, dict):
            return {}
        if 'permissions' in data and ('role' in data or 'role_key' in data or 'key' in data):
            _store(data.get('role') or data.get('role_key') or data.get('key'), data.get('permissions') or [])
            return normalized
        for container_key in ('permission_templates', 'templates'):
            nested = data.get(container_key)
            if isinstance(nested, dict | list):
                return AdminPayloadHelpers._normalize_permission_template_payload(nested)
        for role_key, payload in data.items():
            if isinstance(payload, dict):
                permissions = payload.get('permissions') or payload.get('permission_codes') or []
            else:
                permissions = payload or []
            _store(role_key, permissions)
        return normalized

    @staticmethod
    def _normalize_permission_catalog_payload(data: Any) -> list[dict[str, str]]:
        rows = data if isinstance(data, list) else []
        normalized: list[dict[str, str]] = []
        for row in rows:
            item = row if isinstance(row, dict) else {}
            code = normalize_text(item.get('code') or item.get('permission') or item.get('key'))
            if not code:
                continue
            normalized.append({'code': code, 'label': normalize_text(item.get('label') or code), 'description': normalize_text(item.get('description') or item.get('hint') or code)})
        return normalized

    def _normalize_admin_dashboard_payload(self, data: dict[str, Any], *, source: str='admin_dashboard') -> dict[str, Any]:
        payload = data if isinstance(data, dict) else {}
        regions = [normalize_region_payload(row) for row in self._items_from_admin_payload(payload, 'regions')]
        areas = [normalize_area_payload(row) for row in self._items_from_admin_payload(payload, 'areas')]
        branches = [normalize_branch_payload(row) for row in self._items_from_admin_payload(payload, 'branches')]
        users = [normalize_user(row) for row in self._items_from_admin_payload(payload, 'users')]
        return {'regions': [row for row in regions if row.get('region_id')], 'areas': [row for row in areas if row.get('area_id')], 'branches': [row for row in branches if row.get('branch_id')], 'users': [row for row in users if row.get('username')], 'roles': list(self._payload_value(payload, 'roles', []) or []), 'allowed_role_keys': clean_string_list(self._payload_value(payload, 'allowed_role_keys', []) or []), 'permission_templates': self._normalize_permission_template_payload(self._payload_value(payload, 'permission_templates', {})), 'permission_catalog': self._normalize_permission_catalog_payload(self._payload_value(payload, 'permission_catalog', [])), 'capabilities': clean_string_list(self._payload_value(payload, 'capabilities', []) or []), 'source': source, 'read_only': False, 'contract': normalize_text(self._payload_value(payload, 'contract', '')), 'structure_mutation_contract_ready': parse_bool(self._payload_value(payload, 'structure_mutation_contract_ready', False), False)}
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS

class AdminDashboardMixin(object):

    def admin_structure(self) -> dict[str, Any]:
        data = self._safe_json(self._req('GET', '/admin/structure'))
        return self._normalize_admin_dashboard_payload(data, source='admin_structure')

    @staticmethod
    def _merge_admin_contracts(dashboard: dict[str, Any], structure: dict[str, Any]) -> dict[str, Any]:
        merged = dict(dashboard or {})
        for key in ('regions', 'areas', 'branches', 'users'):
            if structure.get(key):
                merged[key] = list(structure.get(key) or [])
        for key in ('roles', 'allowed_role_keys', 'permission_templates', 'permission_catalog', 'capabilities'):
            if not merged.get(key) and structure.get(key):
                merged[key] = structure.get(key)
        if structure.get('structure_mutation_contract_ready'):
            merged['structure_mutation_contract_ready'] = True
        merged['source'] = 'admin_dashboard+structure'
        return merged

    @staticmethod
    def _has_admin_rows(snapshot: dict[str, Any]) -> bool:
        return any((snapshot.get(key) for key in ('regions', 'areas', 'branches', 'users')))

    def admin_dashboard(self) -> dict[str, Any]:
        data = self._safe_json(self._req('GET', '/admin/dashboard'))
        dashboard = self._normalize_admin_dashboard_payload(data)
        try:
            structure = self.admin_structure()
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if int(getattr(exc, 'status_code', 0) or 0) == 404:
                return dashboard
            if self._has_admin_rows(dashboard):
                return dashboard
            raise
        if self._has_admin_rows(structure):
            return self._merge_admin_contracts(dashboard, structure)
        return dashboard

class AdminListsMixin(object):

    def admin_list_regions(self) -> list[dict[str, Any]]:
        try:
            data = self._safe_json(self._req('GET', '/admin/regions'))
            rows = self._items_from_admin_payload(data, 'regions')
            normalized = [normalize_region_payload(row) for row in rows]
            return [row for row in normalized if row.get('region_id')]
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if int(getattr(exc, 'status_code', 0) or 0) == 404:
                return list(self.meta_regions() or [])
            raise

    def admin_list_areas(self) -> list[dict[str, Any]]:
        try:
            data = self._safe_json(self._req('GET', '/admin/areas'))
            rows = self._items_from_admin_payload(data, 'areas')
            normalized = [normalize_area_payload(row) for row in rows]
            return [row for row in normalized if row.get('area_id')]
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if int(getattr(exc, 'status_code', 0) or 0) == 404:
                return list(self.meta_areas() or [])
            raise

    def admin_list_branches(self) -> list[dict[str, Any]]:
        try:
            data = self._safe_json(self._req('GET', '/admin/branches'))
            rows = self._items_from_admin_payload(data, 'branches')
            normalized = [normalize_branch_payload(row) for row in rows]
            return [row for row in normalized if row.get('branch_id')]
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if int(getattr(exc, 'status_code', 0) or 0) == 404:
                return list(self.meta_branches_full() or [])
            raise

    def admin_list_users(self) -> list[dict[str, Any]]:
        data = self._safe_json(self._req('GET', '/admin/users'))
        return [normalize_user(u) for u in data.get('items') or data.get('users') or []]

class AdminStructureMutationsMixin(object):

    def _admin_delete(self, resource: str, value: str, label: str) -> dict[str, Any]:
        cleaned = normalize_text(value)
        if not cleaned:
            raise RuntimeError(f'{label} is required')
        result = self._safe_json(self._req('DELETE', f'/admin/{resource}/{cleaned}'))
        self._invalidate_admin_sync_cache()
        return result

    @staticmethod
    def _require_text(value: Any, label: str) -> str:
        cleaned = normalize_text(value)
        if not cleaned:
            raise RuntimeError(f'{label} is required')
        return cleaned

    def _admin_post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_json(self._req('POST', endpoint, json=payload))
        self._invalidate_admin_sync_cache()
        return result

    def admin_delete_region(self, region_id: str) -> dict[str, Any]:
        return self._admin_delete('regions', region_id, 'Region id')

    def admin_delete_area(self, area_id: str) -> dict[str, Any]:
        return self._admin_delete('areas', area_id, 'Area id')

    def admin_delete_branch(self, branch_id: str) -> dict[str, Any]:
        return self._admin_delete('branches', branch_id, 'Branch id')

    def admin_upsert_region(self, region_id: str, name: str) -> dict[str, Any]:
        region_id = self._require_text(region_id, 'Region id')
        return self._admin_post_json('/admin/regions/upsert', {'region_id': region_id, 'name': normalize_text(name, region_id)})

    def admin_assign_region_manager(self, region_id: str, user_id: str) -> dict[str, Any]:
        region_id = self._require_text(region_id, 'Region id')
        return self._admin_post_json(f'/admin/regions/{region_id}/assign-manager', {'username': normalize_text(user_id), 'replace_scope': True})

    def admin_upsert_area(self, area_id: str, name: str, region_id: str | None=None) -> dict[str, Any]:
        area_id = self._require_text(area_id, 'Area id')
        payload = {'area_id': area_id, 'name': normalize_text(name, area_id), 'region_id': normalize_text(region_id), 'manager_username': '', 'temporary_manager': False}
        return self._admin_post_json('/admin/areas/upsert', payload)

    def admin_upsert_branch(self, branch_id: str, area_id: str, name: str | None=None, **extra: Any) -> dict[str, Any]:
        branch_id = self._require_text(branch_id, 'Branch id')
        area_id = self._require_text(area_id, 'Area id')
        payload: dict[str, Any] = {'branch_id': branch_id, 'area_id': area_id, 'name': normalize_text(name, branch_id), 'manager_username': normalize_text(extra.get('manager_username') or extra.get('branch_manager_id') or '')}
        return self._admin_post_json('/admin/branches/upsert', payload)

    def admin_transfer_branch(self, branch_id: str, target_area_id: str, **extra: Any) -> dict[str, Any]:
        branch_id = self._require_text(branch_id, 'Branch id')
        target_area_id = self._require_text(target_area_id, 'Target area id')
        payload: dict[str, Any] = {'target_area_id': target_area_id}
        name = normalize_text(extra.get('name') or '')
        if name:
            payload['name'] = name
        return self._admin_post_json(f'/admin/branches/{branch_id}/transfer', payload)

    def admin_assign_area_manager(self, area_id: str, username: str, temporary_manager: bool=False) -> dict[str, Any]:
        area_id = self._require_text(area_id, 'Area id')
        return self._admin_post_json(f'/admin/areas/{area_id}/assign-manager', {'username': normalize_text(username), 'temporary_manager': bool(temporary_manager), 'replace_scope': True})

    def admin_assign_branch_manager(self, branch_id: str, username: str | None) -> dict[str, Any]:
        branch_id = self._require_text(branch_id, 'Branch id')
        username = normalize_text(username) if username is not None else ''
        return self._admin_post_json(f'/admin/branches/{branch_id}/assign-manager', {'username': username, 'replace_scope': True})

class AdminUsersMixin(object):

    def admin_upsert_user(self, user: dict[str, Any]) -> dict[str, Any]:
        raw = dict(user or {})
        username = normalize_text(raw.get('username') or raw.get('user_id') or raw.get('uid'))
        role = normalize_text(raw.get('role') or 'store_user')
        if not username:
            raise RuntimeError('Username is required')
        scope_payload = self._user_scope_payload(raw)
        active_branch = normalize_text(raw.get('active_branch'))
        payload: dict[str, Any] = {'username': username, 'password': normalize_text(raw.get('password')), 'role': role, 'region_ids': scope_payload['region_ids'], 'area_ids': scope_payload['area_ids'], 'branch_ids': scope_payload['branch_ids'], 'active_branch': active_branch, 'is_active': parse_bool(raw.get('is_active'), True), 'must_change_password': parse_bool(raw.get('must_change_password'), False)}
        if not payload['password']:
            payload.pop('password', None)
        result = self._safe_json(self._req('POST', '/admin/users/upsert', json=payload))
        self._invalidate_admin_sync_cache()
        return result

    def admin_reset_password(self, username: str, temporary_password: str) -> dict[str, Any]:
        username = normalize_text(username)
        temporary_password = str(temporary_password or '').strip()
        if not username:
            raise RuntimeError('Username is required')
        if not temporary_password:
            raise RuntimeError('A temporary password is required')
        result = self._safe_json(self._req('POST', '/admin/users/reset_password', json={'username': username, 'password': temporary_password}))
        self._invalidate_admin_sync_cache()
        return result

    def admin_delete_user(self, username: str) -> dict[str, Any]:
        return self._admin_delete('users', username, 'Username')

    def admin_set_role_permissions(self, role_key: str, permissions: list[str]) -> dict[str, Any]:
        role_key = self._require_text(role_key, 'Role')
        clean_permissions = clean_string_list(permissions or [])
        result = self._safe_json(self._req('PUT', f'/admin/roles/{role_key}/permissions', json={'permissions': clean_permissions}))
        self._invalidate_admin_sync_cache()
        return result

    def change_own_password(self, old_password: str, new_password: str) -> dict[str, Any]:
        if not normalize_text(new_password):
            raise RuntimeError('New password is required')
        return self._safe_json(self._req('POST', '/auth/change-password', json={'old_password': str(old_password or ''), 'new_password': str(new_password)}))

class RemoteApiAdminMixin(AdminUsersMixin, AdminStructureMutationsMixin, AdminListsMixin, AdminDashboardMixin, AdminPayloadHelpers):
    """Compose the server administration API surface from focused mixins."""
