from __future__ import annotations
import logging
import threading
from typing import Any
import requests
from runtime.shared.booleans import parse_bool
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.infrastructure.network.cache_api import _user_to_dict
from runtime.infrastructure.network.http import create_configured_session, current_http_timeout, current_requests_verify, get_server_base_url, request_with_retry, resolve_api_url, redact_url_for_log
from runtime.infrastructure.network.realtime import CallbackBridge
logger = logging.getLogger(__name__)

class CloudTrackingService:

    def __init__(self, id_token: str | None=None, user: Any=None, base_url: str | None=None):
        super().__init__()
        self.base_url = get_server_base_url() if not str(base_url or '').strip() else str(base_url).rstrip('/')
        self.id_token = id_token
        self.user = _user_to_dict(user)
        self._session_lock = threading.RLock()
        self._thread_local = threading.local()
        self._sessions: list[requests.Session] = []
        self._realtime_lock = threading.RLock()
        self._stored_cache: dict[str, str] = {}
        self._items_cache: list[dict[str, Any]] = []
        self._cursor: int = 0
        self._rt_stop = threading.Event()
        self._rt_thread: threading.Thread | None = None
        self._items_truncated: bool = False
        self._events_unavailable: bool = False
        self._callback_bridge = CallbackBridge()

    def _headers(self) -> dict[str, str]:
        h = {'Content-Type': 'application/json'}
        if self.id_token:
            h['Authorization'] = f'Bearer {self.id_token}'
        return h

    def _new_session(self) -> requests.Session:
        return create_configured_session()

    def _thread_session(self) -> requests.Session:
        session = getattr(self._thread_local, 'session', None)
        if session is not None:
            return session
        session = self._new_session()
        setattr(self._thread_local, 'session', session)
        with self._session_lock:
            self._sessions.append(session)
        return session

    def _request_with_session(self, method: str, url: str, **kwargs) -> requests.Response:
        return request_with_retry(method, url, session=self._thread_session(), timeout=current_http_timeout(), verify=current_requests_verify(), **kwargs)

    def _realtime_get(self, session: requests.Session, url: str, **kwargs):
        return session.get(url, timeout=current_http_timeout(), verify=current_requests_verify(), allow_redirects=False, **kwargs)

    def _resolve_request_url(self, path: str) -> str:
        return resolve_api_url(path, base_url=self.base_url)

    def _req(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self._resolve_request_url(path)
        kwargs.setdefault('headers', self._headers())
        logger.info('Tracking API: %s %s -> %s', method, path, redact_url_for_log(url))
        try:
            response = self._request_with_session(method, url, **kwargs)
            logger.info('Tracking API response: %s', response.status_code)
            return response
        except SERVICE_OPERATION_EXCEPTIONS as e:
            status_code = int(getattr(e, 'status_code', 0) or 0)
            if str(path).strip() == '/sync/pull' and status_code in {404, 405, 501}:
                logger.info('Optional sync endpoint unavailable: %s (%s)', path, status_code)
            else:
                logger.error('Tracking API error: %s %s - %s', method, path, e)
            raise

    def _reset_realtime_worker(self) -> None:
        self.stop_realtime()
        with self._realtime_lock:
            self._rt_stop = threading.Event()
            self._rt_thread = None

    def _start_realtime_worker(self, target) -> None:
        with self._realtime_lock:
            self._rt_thread = threading.Thread(target=target, daemon=True)
            self._rt_thread.start()

    def stop_realtime(self) -> None:
        return None

    def close(self) -> None:
        self.stop_realtime()
        with self._session_lock:
            sessions = list(getattr(self, '_sessions', []) or [])
            self._sessions.clear()
        for session in sessions:
            try:
                session.close()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug('Session close failed', exc_info=True)
import time
from runtime.application.dto import normalize_stored_product, normalize_usage_product
from runtime.shared.settings.config import get_cache_ttl
from runtime.shared.objects import safe_get
from runtime.shared.strings import normalize_text

class RemoteTrackingCatalogMixin:

    def _catalog_cache_ttl(self) -> float:
        return float(get_cache_ttl().catalog)

    def list_stored_products(self) -> list[dict[str, Any]]:
        if not self._server_has_any_permission('catalog.view', 'catalog.read', 'tracking.catalog.view', 'admin.products.read'):
            return []

        def _load():
            data = self._request_json_optional('/catalog/products')
            items = data.get('items') or data.get('products') or []
            rows = self._normalize_rows(items, normalize_stored_product, 'material_number')
            if rows:
                return rows
            data = self._request_json_optional('/admin/products')
            items = data.get('stored_products') or data.get('items') or []
            rows = self._normalize_rows(items, normalize_stored_product, 'material_number')
            if rows:
                return rows
            data = self._request_json_optional('/tracking/stored-products')
            items = data.get('items') or []
            return self._normalize_rows(items, normalize_stored_product, 'material_number')
        return list(self._cached('catalog_products', self._catalog_cache_ttl(), _load))

    def _default_branch_id(self) -> str:
        active = normalize_text(safe_get(self.user, 'active_branch'))
        if active and self._server_can_access_branch(active):
            return active
        branches = self._known_scope_branches()
        if branches:
            return normalize_text(branches[0])
        return ''

    def list_usage_products(self, *, force_refresh: bool=False, branch_id: str | None=None) -> list[dict[str, Any]]:
        if not self._server_has_any_permission('usage.view', 'usage.read', 'admin.products.read'):
            return []
        resolved_branch = normalize_text(branch_id or self._default_branch_id())
        if resolved_branch and (not self._server_can_access_branch(resolved_branch)):
            return []
        cache_key = f"usage_products:{resolved_branch or 'all'}"

        def _load():
            params = {'branch_id': resolved_branch} if resolved_branch else None
            data = self._request_json_optional('/catalog/usage-products', params=params)
            items = data.get('items') or data.get('usage_products') or []
            rows = self._normalize_rows(items, normalize_usage_product, 'material')
            if rows:
                return rows
            if resolved_branch:
                data = self._request_json_optional('/catalog/usage-products')
                items = data.get('items') or data.get('usage_products') or []
                rows = self._normalize_rows(items, normalize_usage_product, 'material')
                if rows:
                    return rows
            data = self._request_json_optional('/admin/products')
            items = data.get('usage_products') or []
            rows = self._normalize_rows(items, normalize_usage_product, 'material')
            if rows:
                return rows
            data = self._request_json_optional('/tracking/usage-products', params=params)
            items = data.get('items') or data.get('usage_products') or []
            deduped: dict[str, dict[str, Any]] = {}
            for row in self._normalize_rows(items, normalize_usage_product, 'material'):
                key = normalize_text(row.get('material')).lower()
                if key and key not in deduped:
                    deduped[key] = row
            return list(deduped.values())
        if force_refresh:
            self._invalidate_prefix('usage_products')
            value = list(_load())
            with self._request_lock:
                self._memo[cache_key] = (time.monotonic(), value)
            return list(value)
        return list(self._cached(cache_key, self._catalog_cache_ttl(), _load))

    def upsert_usage_product(self, material: str, name: str, unit: str='', active: bool=True) -> dict[str, Any]:
        if not self._server_has_any_permission('usage.manage', 'admin.products.manage'):
            raise PermissionError('Server permission required: usage.manage')
        material = normalize_text(material)
        if not material:
            raise RuntimeError('Material is required')
        payload = {'material': material, 'material_number': material, 'material_code': material, 'material_name': normalize_text(name, material), 'name': normalize_text(name, material), 'unit': normalize_text(unit), 'uom': normalize_text(unit), 'active': bool(active)}
        result = self._safe_json(self._req('POST', '/admin/usage-products/upsert', json=payload))
        self._invalidate_prefix('usage_products')
        return result

    def delete_usage_product_remote(self, material: str) -> dict[str, Any]:
        if not self._server_has_any_permission('usage.manage', 'admin.products.manage'):
            raise PermissionError('Server permission required: usage.manage')
        material = normalize_text(material)
        if not material:
            raise RuntimeError('Material is required')
        result = self._safe_json(self._req('DELETE', f'/admin/usage-products/{material}'))
        self._invalidate_prefix('usage_products')
        return result

    def stored_snapshot(self) -> dict[str, str]:
        rows = self.list_stored_products()
        self._stored_cache = {normalize_text(row.get('material_number')): normalize_text(row.get('name')) for row in rows if normalize_text(row.get('material_number'))}
        return dict(self._stored_cache)

    def upsert_stored_product(self, material_number: str, name: str) -> dict[str, Any]:
        if not self._server_has_any_permission('catalog.manage', 'admin.products.manage'):
            raise PermissionError('Server permission required: catalog.manage')
        self._require_server_permission('sync.push')
        material_number = normalize_text(material_number)
        if not material_number:
            raise RuntimeError('Material number is required')
        payload = {'material_id': material_number, 'material_number': material_number, 'name': normalize_text(name, material_number)}
        result = self._safe_json(self._req('POST', '/sync/push', json={'changes': [{'entity_type': 'stored_product', 'entity_key': material_number, 'branch_id': None, 'op': 'upsert', 'payload': payload}]}))
        self._stored_cache[material_number] = payload.get('name', material_number)
        self._invalidate_prefix('catalog_')
        return result

    def delete_stored_product_remote(self, material_number: str) -> dict[str, Any]:
        if not self._server_has_any_permission('catalog.manage', 'admin.products.manage'):
            raise PermissionError('Server permission required: catalog.manage')
        self._require_server_permission('sync.push')
        material_number = normalize_text(material_number)
        if not material_number:
            raise RuntimeError('Material number is required')
        result = self._safe_json(self._req('POST', '/sync/push', json={'changes': [{'entity_type': 'stored_product', 'entity_key': material_number, 'branch_id': None, 'op': 'delete', 'payload': {}}]}))
        self._stored_cache.pop(material_number, None)
        self._invalidate_prefix('catalog_')
        return result

    def refresh_stored_snapshot(self) -> dict[str, str]:
        self._invalidate_prefix('catalog_')
        return self.stored_snapshot()

    def _refresh_stored_snapshot_safely(self) -> None:
        try:
            self.refresh_stored_snapshot()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('Failed to refresh stored product cache from server', exc_info=True)
from runtime.application.dto import normalize_alert
from runtime.application.dto import normalize_tracking_item
from runtime.shared.objects import normalize_int
from runtime.domain.remote_ids import normalize_remote_id

class RemoteTrackingItemsMixin:

    def add_item(self, *, branch: str | None=None, branch_id: str | None=None, branch_code: str | None=None, material_number: str | None=None, material_code: str | None=None, material_name: str | None=None, name: str | None=None, quantity: int | str=0, production_date: str | None=None, expiry_date: str | None=None, **_ignored: Any) -> dict[str, Any]:
        self._require_server_permission('tracking.create')
        resolved_branch = normalize_text(branch or branch_code or branch_id or self._default_branch_id())
        if not resolved_branch or resolved_branch.lower() == 'all':
            raise RuntimeError('A writable branch is required')
        if not self._server_can_access_branch(resolved_branch):
            raise PermissionError('Branch outside server-authorized scope')
        material = normalize_text(material_number or material_code)
        if not material:
            raise RuntimeError('Material number is required')
        resolved_name = normalize_text(material_name or name or material)
        payload = {'branch_code': resolved_branch, 'branch_id': resolved_branch, 'material_code': material, 'material_number': material, 'material_name': resolved_name, 'name': resolved_name, 'quantity': normalize_int(quantity), 'production_date': normalize_text(production_date), 'expiry_date': normalize_text(expiry_date)}
        data = self._safe_json(self._req('POST', '/tracking/items', json=payload))
        item = data.get('item') if isinstance(data.get('item'), dict) else dict(payload)
        doc_id = normalize_text(data.get('doc_id') or data.get('id') or item.get('doc_id') or item.get('id'))
        if doc_id:
            item['doc_id'] = doc_id
            item.setdefault('id', doc_id)
        item.setdefault('branch', resolved_branch)
        item.setdefault('branch_id', resolved_branch)
        item.setdefault('material_number', material)
        item.setdefault('material_code', material)
        item.setdefault('material_name', resolved_name)
        item.setdefault('name', resolved_name)
        item.setdefault('quantity', normalize_int(quantity))
        item.setdefault('production_date', normalize_text(production_date))
        item.setdefault('expiry_date', normalize_text(expiry_date))
        self.invalidate_tracking_cache(resolved_branch)
        return item

    def update_item(self, *, branch: str | None=None, branch_id: str | None=None, branch_code: str | None=None, doc_id: str | None=None, item_id: str | None=None, id: str | None=None, material_number: str | None=None, material_code: str | None=None, quantity: int | str=0, production_date: str | None=None, expiry_date: str | None=None, **_ignored: Any) -> dict[str, Any]:
        self._require_server_permission('tracking.update')
        resolved_branch = normalize_text(branch or branch_code or branch_id)
        if resolved_branch and (not self._server_can_access_branch(resolved_branch)):
            raise PermissionError('Branch outside server-authorized scope')
        resolved_id = normalize_remote_id({'id': doc_id or item_id or id}) or normalize_text(doc_id or item_id or id)
        if not resolved_id:
            raise RuntimeError('Item id is required')
        payload = {'branch_code': resolved_branch, 'branch_id': resolved_branch, 'material_code': normalize_text(material_code or material_number), 'material_number': normalize_text(material_number or material_code), 'quantity': normalize_int(quantity), 'production_date': normalize_text(production_date), 'expiry_date': normalize_text(expiry_date)}
        try:
            data = self._safe_json(self._req('PUT', f'/tracking/items/{resolved_id}', json=payload))
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if int(getattr(exc, 'status_code', 0) or 0) != 404:
                raise
            self._require_server_permission('sync.push')
            data = self._safe_json(self._req('POST', '/sync/push', json={'changes': [{'entity_type': 'tracking_item', 'entity_key': resolved_id, 'branch_id': resolved_branch or None, 'op': 'upsert', 'payload': dict(payload, id=resolved_id, doc_id=resolved_id)}]}))
        self.invalidate_tracking_cache(resolved_branch)
        item = data.get('item') if isinstance(data.get('item'), dict) else dict(payload)
        item.setdefault('doc_id', resolved_id)
        item.setdefault('id', resolved_id)
        return item

    def delete_item(self, *, branch: str | None=None, branch_id: str | None=None, branch_code: str | None=None, doc_id: str | None=None, item_id: str | None=None, id: str | None=None, **_ignored: Any) -> dict[str, Any]:
        self._require_server_permission('tracking.delete')
        resolved_branch = normalize_text(branch or branch_code or branch_id)
        if resolved_branch and (not self._server_can_access_branch(resolved_branch)):
            raise PermissionError('Branch outside server-authorized scope')
        resolved_id = normalize_remote_id({'id': doc_id or item_id or id}) or normalize_text(doc_id or item_id or id)
        if not resolved_id:
            raise RuntimeError('Item id is required')
        try:
            result = self._safe_json(self._req('DELETE', f'/tracking/items/{resolved_id}'))
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if int(getattr(exc, 'status_code', 0) or 0) != 404:
                raise
            self._require_server_permission('sync.push')
            result = self._safe_json(self._req('POST', '/sync/push', json={'changes': [{'entity_type': 'tracking_item', 'entity_key': resolved_id, 'branch_id': resolved_branch or None, 'op': 'delete', 'payload': {'id': resolved_id, 'doc_id': resolved_id}}]}))
        self.invalidate_tracking_cache(resolved_branch)
        return result if isinstance(result, dict) else {'ok': True, 'deleted': True}

    def list_items(self, branch_id: str | None=None, *, branch_filter: str | None=None) -> list[dict[str, Any]]:
        if not self._server_has_any_permission('tracking.view', 'tracking.read'):
            return []
        branch = normalize_text(branch_filter if branch_filter is not None else branch_id)
        if branch and (not self._server_can_access_branch(branch)):
            return []
        cache_key = f'items:{branch.lower()}' if branch else 'items:all'

        def _load():
            params = {'branch_code': branch} if branch else None
            try:
                data = self._safe_json(self._req('GET', '/tracking/items', params=params))
            except SERVICE_OPERATION_EXCEPTIONS as exc:
                if int(getattr(exc, 'status_code', 0) or 0) == 404 and branch:
                    data = self._safe_json(self._req('GET', '/tracking/items', params={'branch_id': branch}))
                else:
                    raise
            rows = data.get('items') or data.get('rows') or []
            try:
                stored_names = self.stored_snapshot()
            except SERVICE_OPERATION_EXCEPTIONS:
                stored_names = {}
            normalized = [normalize_tracking_item(item, stored_name=normalize_text(stored_names.get(normalize_text(item.get('material_number') or item.get('material_id') or item.get('material_code') or item.get('code'))))) for item in rows if isinstance(item, dict)]
            if branch:
                branch_key = branch.lower()
                normalized = [row for row in normalized if normalize_text(row.get('branch') or row.get('branch_id')).lower() == branch_key]
            self._items_truncated = parse_bool(data.get('truncated'), False)
            return normalized
        return list(self._cached(cache_key, self._metadata_cache_ttl(), _load))

    def snapshot_items(self, branch_id: str | None=None, *, branch_filter: str | None=None) -> list[dict[str, Any]]:
        requested = normalize_text(branch_filter if branch_filter is not None else branch_id)
        if self._server_scope_all_branches():
            return self.list_items(branch_filter=requested or None)
        allowed = self._server_scope_branch_ids()
        if requested:
            allowed_keys = {branch.casefold() for branch in allowed}
            if requested.casefold() not in allowed_keys:
                logger.warning('Rejected out-of-scope tracking snapshot branch: %s', requested)
                return []
            return self.list_items(branch_filter=requested)
        if not allowed:
            logger.warning('Tracking snapshot skipped because the authenticated scope has no branches')
            return []
        from runtime.domain.tracking_rows import deduplicate_tracking_records
        rows: list[dict[str, Any]] = []
        for branch in allowed:
            rows.extend(self.list_items(branch_filter=branch))
        return deduplicate_tracking_records(rows)

    def delete_item_remote(self, item_id: str, branch_id: str | None=None) -> dict[str, Any]:
        self._require_server_permission('tracking.delete')
        branch = self._require_branch(branch_id)
        if not self._server_can_access_branch(branch):
            raise PermissionError('Branch outside server-authorized scope')
        item_id = normalize_remote_id({'id': item_id}) or normalize_text(item_id)
        if not item_id:
            raise RuntimeError('Item id is required')
        result = self._safe_json(self._req('POST', '/tracking/delete', json={'id': item_id, 'branch_id': branch}))
        self.invalidate_tracking_cache(branch)
        return result

    def list_alerts(self) -> list[dict[str, Any]]:
        if not self._server_has_any_permission('tracking.view', 'tracking.read'):
            return []

        def _load():
            data = self._safe_json(self._req('GET', '/alerts/items'))
            rows = data.get('items') or data.get('alerts') or []
            return [normalize_alert(item) for item in rows if isinstance(item, dict)]
        return list(self._cached('alerts', self._metadata_cache_ttl(), _load))

    def mark_alert_seen(self, alert_id: str) -> dict[str, Any]:
        alert_id = normalize_remote_id({'id': alert_id}) or normalize_text(alert_id)
        if not alert_id:
            raise RuntimeError('Alert id is required')
        result = self._safe_json(self._req('POST', f'/tracking/alerts/{alert_id}/seen'))
        self._invalidate_prefix('alerts')
        return result if isinstance(result, dict) else {'ok': True, 'id': alert_id}

    def list_branch_items(self, branch_id: str) -> list[dict[str, Any]]:
        branch = self._require_branch(branch_id)
        return self.list_items(branch)
from runtime.application.dto import normalize_area_payload, normalize_branch_payload, normalize_region_payload
from runtime.shared.objects import clean_string_list

class RemoteTrackingMetadataMixin:

    def _server_authority_valid(self) -> bool:
        source = normalize_text(safe_get(self.user, 'permission_source'))
        scope = safe_get(self.user, 'scope')
        permissions = safe_get(self.user, 'permissions')
        return source == 'postgresql.role_permissions' and isinstance(scope, dict) and isinstance(permissions, (list, tuple, set))

    def _server_permissions(self) -> set[str]:
        if not self._server_authority_valid():
            return set()
        return {normalize_text(value).lower() for value in safe_get(self.user, 'permissions') or [] if normalize_text(value)}

    def _server_has_permission(self, permission: str) -> bool:
        code = normalize_text(permission).lower()
        permissions = self._server_permissions()
        return bool(code and ('*' in permissions or code in permissions))

    def _server_has_any_permission(self, *permissions: str) -> bool:
        return any((self._server_has_permission(code) for code in permissions))

    def _require_server_permission(self, permission: str) -> None:
        if not self._server_has_permission(permission):
            raise PermissionError(f'Server permission required: {permission}')

    def _server_can_access_branch(self, branch: str | None) -> bool:
        value = normalize_text(branch)
        if not value or not self._server_authority_valid():
            return False
        if self._server_scope_all_branches():
            return True
        return value.casefold() in {item.casefold() for item in self._known_scope_branches()}

    def _metadata_cache_ttl(self) -> float:
        return float(get_cache_ttl().metadata)

    @staticmethod
    def _normalize_rows(items: list[Any], normalizer, id_key: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in items:
            row = normalizer(item)
            if row.get(id_key):
                rows.append(row)
        return rows

    def _request_json_optional(self, path: str, *, params: dict[str, Any] | None=None) -> dict[str, Any]:
        try:
            return self._safe_json(self._req('GET', path, params=params))
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if int(getattr(exc, 'status_code', 0) or 0) == 404:
                return {}
            raise

    def _server_scope_all_branches(self) -> bool:
        """Read all-branch scope only from authenticated server authority."""
        if not self._server_authority_valid():
            return False
        scope = safe_get(self.user, 'scope') or {}
        try:
            return parse_bool(safe_get(scope, 'all_branches'), False)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.warning('Unable to read all-branch scope; restricted scope is enforced', exc_info=True)
            return False

    def _server_scope_branch_ids(self) -> list[str]:
        """Return restricted branches; empty scope never grants global access."""
        if self._server_scope_all_branches():
            return []
        return self._known_scope_branches()

    def _known_scope_branches(self) -> list[str]:
        if not self._server_authority_valid():
            return []
        scope = safe_get(self.user, 'scope') or {}
        return clean_string_list(safe_get(scope, 'branches') or [])

    def _org_tree(self) -> list[dict[str, Any]]:

        def _load():
            data = self._request_json_optional('/org/tree')
            regions = data.get('regions') or data.get('tree') or []
            return list(regions) if isinstance(regions, list) else []
        return list(self._cached('org_tree', self._metadata_cache_ttl(), _load))

    def _tree_regions(self) -> list[dict[str, Any]]:
        regions = []
        for item in self._org_tree():
            if not isinstance(item, dict):
                continue
            name = normalize_text(item.get('name') or item.get('region_id') or item.get('code'))
            if not name:
                continue
            regions.append({'region_id': name, 'code': name, 'name': name, 'is_active': True})
        return self._normalize_rows(regions, normalize_region_payload, 'region_id')

    def _tree_areas(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for region in self._org_tree():
            if not isinstance(region, dict):
                continue
            region_name = normalize_text(region.get('name') or region.get('region_id') or region.get('code'))
            for area in region.get('areas') or []:
                if not isinstance(area, dict):
                    continue
                area_name = normalize_text(area.get('name') or area.get('area_id') or area.get('code'))
                if not area_name:
                    continue
                rows.append({'area_id': area_name, 'code': area_name, 'name': area_name, 'region_id': region_name, 'is_active': True})
        return self._normalize_rows(rows, normalize_area_payload, 'area_id')

    def _tree_branches(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for region in self._org_tree():
            if not isinstance(region, dict):
                continue
            region_name = normalize_text(region.get('name') or region.get('region_id') or region.get('code'))
            for area in region.get('areas') or []:
                if not isinstance(area, dict):
                    continue
                area_name = normalize_text(area.get('name') or area.get('area_id') or area.get('code'))
                for branch in area.get('branches') or []:
                    if not isinstance(branch, dict):
                        continue
                    code = normalize_text(branch.get('code') or branch.get('branch_id') or branch.get('id'))
                    if not code:
                        continue
                    rows.append({'branch_id': code, 'code': code, 'name': normalize_text(branch.get('name') or code), 'region_id': region_name, 'area_id': area_name, 'is_active': parse_bool(branch.get('is_active'), True)})
        return self._normalize_rows(rows, normalize_branch_payload, 'branch_id')

    def _server_scope_flag(self, key: str) -> bool:
        if not self._server_authority_valid():
            return False
        scope = safe_get(self.user, 'scope') or {}
        try:
            return parse_bool(safe_get(scope, key), False)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.warning('Unable to read server scope flag %s', key, exc_info=True)
            return False

    def meta_branches(self) -> list[str]:

        def _load():
            data = self._request_json_optional('/meta/branches')
            items = data.get('items') or data.get('branches') or []
            branches = self._normalize_rows(items, normalize_branch_payload, 'branch_id')
            if branches:
                return [row.get('branch_id', '') for row in branches]
            if self._server_scope_all_branches():
                return [row.get('branch_id', '') for row in self._tree_branches()]
            return self._known_scope_branches()
        return list(self._cached('meta_branches', self._metadata_cache_ttl(), _load))

    def meta_branches_full(self) -> list[dict[str, Any]]:

        def _load():
            data = self._request_json_optional('/meta/branches')
            items = data.get('items') or data.get('branches') or []
            rows = self._normalize_rows(items, normalize_branch_payload, 'branch_id')
            if rows:
                return rows
            if self._server_scope_all_branches():
                return self._tree_branches()
            return [normalize_branch_payload({'branch_id': branch, 'code': branch, 'name': branch}) for branch in self._known_scope_branches()]
        return list(self._cached('meta_branches_full', self._metadata_cache_ttl(), _load))

    def _meta_scope_rows(self, *, endpoint: str, payload_key: str, normalizer, id_key: str, fallback_loader, all_scope_key: str) -> list[dict[str, Any]]:
        data = self._request_json_optional(endpoint)
        items = data.get('items') or data.get(payload_key) or []
        rows = self._normalize_rows(items, normalizer, id_key)
        if rows:
            return rows
        if self._server_scope_flag(all_scope_key):
            return fallback_loader()
        return []

    def _cached_meta_scope(self, *, cache_key: str, endpoint: str, payload_key: str, normalizer, id_key: str, fallback_loader, all_scope_key: str) -> list[dict[str, Any]]:

        def _load():
            return self._meta_scope_rows(endpoint=endpoint, payload_key=payload_key, normalizer=normalizer, id_key=id_key, fallback_loader=fallback_loader, all_scope_key=all_scope_key)
        return list(self._cached(cache_key, self._metadata_cache_ttl(), _load))

    def meta_regions(self) -> list[dict[str, Any]]:
        return self._cached_meta_scope(cache_key='meta_regions', endpoint='/meta/regions', payload_key='regions', normalizer=normalize_region_payload, id_key='region_id', fallback_loader=self._tree_regions, all_scope_key='all_regions')

    def meta_areas(self) -> list[dict[str, Any]]:
        return self._cached_meta_scope(cache_key='meta_areas', endpoint='/meta/areas', payload_key='areas', normalizer=normalize_area_payload, id_key='area_id', fallback_loader=self._tree_areas, all_scope_key='all_areas')
from runtime.application.dto import change_operation, change_payload

class RemoteTrackingSyncMixin:

    def _sync_cursor_from_payload(self, data: dict[str, Any]) -> int:
        for key in ('cursor', 'next_cursor', 'last_cursor', 'last_id', 'event_id', 'version'):
            value = normalize_int(data.get(key))
            if value > 0:
                return value
        return 0

    def sync_pull_temporarily_disabled(self) -> bool:
        disabled_until = float(getattr(self, '_sync_pull_disabled_until', 0.0) or 0.0)
        return bool(disabled_until and time.monotonic() < disabled_until)

    def pull_sync_changes(self, branch_id: str | None=None, *, cursor: int | None=None, branch_ids: list[str] | None=None) -> dict[str, Any]:
        if not self._server_has_permission('sync.pull'):
            return {'changes': [], 'cursor': int(getattr(self, '_cursor', 0) or 0), 'permission_denied': True}
        disabled_until = float(getattr(self, '_sync_pull_disabled_until', 0.0) or 0.0)
        if disabled_until and time.monotonic() < disabled_until:
            return {'changes': [], 'cursor': int(getattr(self, '_cursor', 0) or 0), 'sync_unavailable': True}
        params: dict[str, Any] = {}
        branches = clean_string_list(branch_ids or [])
        if branch_id:
            params['branch_id'] = normalize_text(branch_id)
        elif branches:
            params['branch_ids'] = ','.join(branches)
        if cursor is not None:
            params['cursor'] = normalize_int(cursor)
        try:
            data = self._safe_json(self._req('GET', '/sync/pull', params=params or None, optional_statuses={404, 405, 501}))
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            status_code = int(getattr(exc, 'status_code', 0) or 0)
            if status_code in {404, 405, 501}:
                self._sync_pull_disabled_until = time.monotonic() + 300.0
                if not bool(getattr(self, '_sync_pull_unavailable_logged', False)):
                    logger.info('/sync/pull is unavailable on this server; delta sync is disabled for 5 minutes.')
                    self._sync_pull_unavailable_logged = True
                return {'changes': [], 'cursor': int(getattr(self, '_cursor', 0) or 0), 'sync_unavailable': True}
            raise
        if not isinstance(data, dict):
            return {}
        self._sync_pull_unavailable_logged = False
        self._sync_pull_disabled_until = 0.0
        return data

    def pull_now(self, branch_id: str | None=None) -> dict[str, Any]:
        branch = normalize_text(branch_id)
        if branch:
            if not self._server_scope_all_branches():
                allowed = {value.casefold() for value in self._server_scope_branch_ids()}
                if branch.casefold() not in allowed:
                    logger.warning('Rejected out-of-scope tracking sync branch: %s', branch)
                    return {'rows': [], 'items': [], 'changes': [], 'cursor': int(getattr(self, '_cursor', 0) or 0), 'has_changes': False, 'scope_unavailable': True}
            scoped_branch_ids = None
        elif self._server_scope_all_branches():
            scoped_branch_ids = []
        else:
            scoped_branch_ids = self._server_scope_branch_ids()
            if not scoped_branch_ids:
                logger.warning('Tracking sync skipped because the authenticated scope has no branches')
                return {'rows': [], 'items': [], 'changes': [], 'cursor': int(getattr(self, '_cursor', 0) or 0), 'has_changes': False, 'scope_unavailable': True}
        with self._pull_lock:
            data = self.pull_sync_changes(branch_id=branch or None, cursor=self._cursor, branch_ids=scoped_branch_ids)
        raw_changes = data.get('changes')
        raw_items = data.get('items') if isinstance(data.get('items'), list) else []
        raw_rows = data.get('rows') if isinstance(data.get('rows'), list) else []
        changes = raw_changes if isinstance(raw_changes, list) else raw_items or raw_rows or []
        if not isinstance(changes, list):
            changes = []
        rows: list[dict[str, Any]] = []
        for item in changes:
            if not isinstance(item, dict):
                continue
            entity_type = normalize_text(item.get('entity_type') or item.get('type')).lower()
            payload = change_payload(item)
            if entity_type and entity_type not in {'tracking_item', 'tracked_product', 'tracking'}:
                continue
            if change_operation(item) == 'delete':
                continue
            normalized = normalize_tracking_item(payload)
            if normalized.get('doc_id') or normalized.get('id'):
                rows.append(normalized)
        if changes:
            self.invalidate_tracking_cache(branch_id)
            for prefix in ('alerts', 'catalog_', 'meta_', 'admin_', 'org_tree', 'usage_products'):
                try:
                    self._invalidate_prefix(prefix)
                except SERVICE_OPERATION_EXCEPTIONS:
                    logger.debug('Sync cache invalidation skipped for %s', prefix, exc_info=True)
        received_cursor = normalize_int(data.get('next_cursor') or data.get('cursor') or data.get('last_id'))
        candidate_cursor = max(int(getattr(self, '_cursor', 0) or 0), received_cursor)
        return {'rows': rows, 'items': raw_items, 'changes': changes, 'cursor': candidate_cursor, 'next_cursor': candidate_cursor, 'last_id': normalize_int(data.get('last_id') or candidate_cursor), 'has_changes': parse_bool(data.get('has_changes'), False) or bool(changes or rows or raw_items), 'baseline_required': parse_bool(data.get('baseline_required'), False), 'truncated': parse_bool(data.get('truncated'), False), 'sync_unavailable': parse_bool(data.get('sync_unavailable'), False)}

    def push_sync_changes(self, changes: list[dict[str, Any]]) -> dict[str, Any]:
        self._require_server_permission('sync.push')
        pending = [item for item in list(changes or []) if isinstance(item, dict)]
        if not pending:
            return {'ok': True, 'status': 'ok', 'results': [], 'changes': []}
        combined_results: list[dict[str, Any]] = []
        server_time = ''
        overall_status = 'ok'
        for offset in range(0, len(pending), 250):
            batch = pending[offset:offset + 250]
            data = self._safe_json(self._req('POST', '/sync/push', json={'changes': batch}))
            if not isinstance(data, dict):
                raise RuntimeError('Sync push returned an invalid server response.')
            batch_results = data.get('results') or data.get('changes') or []
            if isinstance(batch_results, list):
                combined_results.extend((item for item in batch_results if isinstance(item, dict)))
            if str(data.get('status') or 'ok').lower() != 'ok':
                overall_status = str(data.get('status') or 'error')
            server_time = str(data.get('server_time') or server_time)
            next_cursor = self._sync_cursor_from_payload(data)
            if next_cursor > 0:
                self._cursor = max(self._cursor, next_cursor)
        if combined_results:
            self.invalidate_tracking_cache()
        return {'ok': overall_status == 'ok', 'status': overall_status, 'results': combined_results, 'changes': combined_results, 'server_time': server_time}

    def set_sync_cursor(self, cursor: int | str | None) -> None:
        self._cursor = max(0, normalize_int(cursor))

    def sync_cursor(self) -> int:
        return max(0, int(getattr(self, '_cursor', 0) or 0))

    def get_items_since(self, cursor: int=0, *, branch_ids: list[str] | None=None) -> tuple[list[dict[str, Any]], int]:
        cursor_value = max(0, int(cursor or 0))
        branches = clean_string_list(branch_ids or [])
        data = self.pull_sync_changes(cursor=cursor_value, branch_ids=branches)
        rows = data.get('rows') or data.get('items') or data.get('changes') or []
        items: list[dict[str, Any]] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            if str(item.get('entity_type') or '').strip() != 'tracking_item':
                continue
            payload = item.get('payload') if isinstance(item.get('payload'), dict) else item
            items.append(normalize_tracking_item(payload))
        next_cursor = normalize_int(data.get('cursor'))
        self._cursor = max(self._cursor, next_cursor)
        return (items, next_cursor)

class RemoteApiTrackingMixin(RemoteTrackingMetadataMixin, RemoteTrackingCatalogMixin, RemoteTrackingItemsMixin, RemoteTrackingSyncMixin):
    """Composition surface for tracking-related remote API responsibilities."""
