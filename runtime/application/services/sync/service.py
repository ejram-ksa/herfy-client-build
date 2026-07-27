from __future__ import annotations
from runtime.domain.tracking_rows import deduplicate_tracking_records
import logging
from dataclasses import dataclass
logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class CloudReconnectFlowDecision:
    should_invalidate_cache: bool
    should_refresh_usage: bool
    should_emit_data_refresh: bool

class CloudReconnectFlowService:

    @staticmethod
    def evaluate(*, online: bool, previous_online: bool, session_active: bool, login_hydrate_pending: bool=False) -> CloudReconnectFlowDecision:
        reconnect = bool(online) and (not bool(previous_online)) and bool(session_active)
        hydrate_in_progress = bool(login_hydrate_pending)
        return CloudReconnectFlowDecision(should_invalidate_cache=reconnect, should_refresh_usage=reconnect and (not hydrate_in_progress), should_emit_data_refresh=reconnect and (not hydrate_in_progress))
import hashlib
import posixpath
import time
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote
from runtime.shared.settings.config import DEFAULT_SERVER_BASE_URL, runtime_cache_path
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.application.ports import api_fetch_json, api_request, fetch_client_bootstrap, get_server_base_url
from runtime.shared.files import read_json_dict, sha256_file, write_bytes_atomic, write_json_dict
_BOOTSTRAP_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_BOOTSTRAP_CACHE_LOCK = threading.RLock()
_BOOTSTRAP_CACHE_TTL_SECONDS = 12.0

def _fetch_cached_bootstrap(base_url: str, client_version: str) -> dict[str, Any]:
    key = (str(base_url or '').rstrip('/'), str(client_version or '').strip())
    now = time.monotonic()
    with _BOOTSTRAP_CACHE_LOCK:
        cached = _BOOTSTRAP_CACHE.get(key)
        if cached is not None:
            ts, payload = cached
            if now - float(ts) <= _BOOTSTRAP_CACHE_TTL_SECONDS and isinstance(payload, dict):
                return dict(payload)
    payload = fetch_client_bootstrap(key[1], base_url=key[0])
    if isinstance(payload, dict) and payload:
        with _BOOTSTRAP_CACHE_LOCK:
            _BOOTSTRAP_CACHE[key] = (time.monotonic(), dict(payload))
    return dict(payload or {})

def current_api_base_url() -> str:
    try:
        return str(get_server_base_url(DEFAULT_SERVER_BASE_URL) or DEFAULT_SERVER_BASE_URL).strip()
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug('Falling back to default API base URL', exc_info=True)
        return DEFAULT_SERVER_BASE_URL

def _safe_remote_asset_name(name: str) -> str:
    raw = str(name or '').replace('\\', '/').strip()
    normalized = posixpath.normpath(raw)
    if not raw or normalized in {'', '.'} or normalized.startswith(('../', '/')) or (':' in normalized):
        return ''
    parts = [part for part in normalized.split('/') if part and part != '.']
    if not parts or any((part == '..' for part in parts)):
        return ''
    return '/'.join(parts)

def should_refresh_resource(*, target_version: str, current_version: str, force_refresh: bool=False) -> bool:
    if force_refresh:
        return True
    target = str(target_version or '').strip()
    current = str(current_version or '').strip()
    if not target:
        return True
    return target != current

def _safe_unlink(path: Path, *, log_message: str) -> None:
    try:
        if path.exists():
            path.unlink()
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.exception(log_message)

class RemoteManifestService:

    def __init__(self, base_url: str | None=None):
        try:
            resolved_base_url = base_url or get_server_base_url(DEFAULT_SERVER_BASE_URL)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('Using default API base URL for remote manifest service', exc_info=True)
            resolved_base_url = DEFAULT_SERVER_BASE_URL
        self.base_url = str(resolved_base_url or DEFAULT_SERVER_BASE_URL).rstrip('/')

    def _json_get(self, path: str) -> dict[str, Any]:
        return api_fetch_json(path, base_url=self.base_url)

    def fetch_client_bootstrap(self, client_version: str) -> dict[str, Any]:
        return _fetch_cached_bootstrap(self.base_url, client_version)

    def _fetch_manifest_path(self, path: str) -> dict[str, Any]:
        return self._json_get(path)

    def fetch_ui_manifest(self) -> dict[str, Any]:
        return self._fetch_manifest_path('/client-ui/manifest')

    def fetch_assets_index(self) -> dict[str, Any]:
        return self._fetch_manifest_path('/client-ui/assets/index')

    def download_public_file(self, path: str) -> bytes:
        response = api_request('GET', path, base_url=self.base_url, timeout=30)
        try:
            return response.content
        finally:
            response.close()

    @staticmethod
    def version_state_path() -> Path:
        return Path(runtime_cache_path('remote_state/version_state.json'))

    @classmethod
    def load_cached_version_state(cls) -> dict[str, Any]:
        return read_json_dict(cls.version_state_path())

    @classmethod
    def save_cached_version_state(cls, data: dict[str, Any]) -> None:
        write_json_dict(cls.version_state_path(), data, ensure_ascii=False)

class RemoteAssetService:

    def __init__(self, base_url: str | None=None):
        self.manifest = RemoteManifestService(base_url)
        self.asset_root = Path(runtime_cache_path('ui_cache/assets'))
        self.asset_root.mkdir(parents=True, exist_ok=True)

    def sync_assets(self) -> int:
        ui_manifest = self.manifest.fetch_ui_manifest()
        local_state = self.manifest.load_cached_version_state()
        target_version = str(ui_manifest.get('assets_version') or '')
        force_refresh = parse_bool(ui_manifest.get('force_refresh'), False)
        if not should_refresh_resource(target_version=target_version, current_version=str(local_state.get('assets_version') or ''), force_refresh=force_refresh):
            return 0
        index = self.manifest.fetch_assets_index()
        downloaded = 0
        asset_items = index.get('items') if isinstance(index.get('items'), list) else []
        if not asset_items and isinstance(index.get('files'), list):
            asset_items = [{'name': str(name).strip(), 'sha256': ''} for name in index.get('files', []) if str(name).strip()]
        for item in asset_items:
            name = _safe_remote_asset_name(str(item.get('name') or item.get('file_name') or ''))
            if not name:
                continue
            expected = str(item.get('sha256') or '').strip().lower()
            local_path = self.asset_root.joinpath(*name.split('/'))
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if local_path.exists() and expected:
                try:
                    if sha256_file(local_path).lower() == expected:
                        continue
                except SERVICE_OPERATION_EXCEPTIONS:
                    logger.debug('Failed to hash existing UI asset before refresh: %s', local_path, exc_info=True)
            payload = self.manifest.download_public_file(f"/client-ui/assets/file/{quote(name, safe='/')}")
            if expected:
                if len(expected) != 64 or any((character not in '0123456789abcdef' for character in expected)):
                    raise RuntimeError(f'Invalid asset SHA256 for {name}')
                actual = hashlib.sha256(payload).hexdigest()
                if actual != expected:
                    raise RuntimeError(f'Downloaded asset checksum mismatch for {name}')
            write_bytes_atomic(local_path, payload)
            downloaded += 1
        local_state['assets_version'] = target_version
        local_state['ui_manifest_version'] = str(ui_manifest.get('version') or '')
        self.manifest.save_cached_version_state(local_state)
        return downloaded

def profile_to_cloud_user_payload(profile) -> dict[str, Any]:
    if profile is None:
        return {}
    if hasattr(profile, 'to_cloud_user_payload'):
        return profile.to_cloud_user_payload()
    ctx = getattr(profile, 'permission_context', None)
    scope = getattr(ctx, 'scope', None)
    return {'username': getattr(profile, 'username', ''), 'role': getattr(profile, 'role', ''), 'active_branch': getattr(profile, 'active_branch', ''), 'uid': getattr(profile, 'uid', ''), 'permissions': list(getattr(ctx, 'permissions', []) or []), 'scope': {'regions': list(getattr(scope, 'regions', []) or []), 'areas': list(getattr(scope, 'areas', []) or []), 'branches': list(getattr(scope, 'branches', []) or []), 'all_regions': bool(getattr(scope, 'all_regions', False)), 'all_areas': bool(getattr(scope, 'all_areas', False)), 'all_branches': bool(getattr(scope, 'all_branches', False))}, 'area_id': getattr(profile, 'area_id', ''), 'area_manager_id': getattr(profile, 'area_manager_id', ''), 'assigned_branch_ids': list(getattr(profile, 'assigned_branch_ids', []) or []), 'must_change_password': bool(getattr(profile, 'must_change_password', False)), 'is_active': bool(getattr(profile, 'is_active', True)), 'temporary_manager': bool(getattr(profile, 'temporary_manager', False)), 'permission_source': str(getattr(ctx, 'authority_source', '') or ''), 'authority_revision': int(getattr(ctx, 'authority_revision', 0) or 0)}
from runtime.shared.booleans import parse_bool
from runtime.shared.objects import normalize_int

def apply_remote_catalog_snapshot(db_manager, snapshot: dict[str, Any] | None) -> dict[str, str]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    if not payload:
        return {}
    connection = db_manager.connection
    cursor = connection.cursor()
    normalized: dict[str, str] = {}
    for material_id, name in payload.items():
        material_text = str(material_id).strip()
        name_text = str(name).strip()
        if not material_text:
            continue
        cursor.execute('INSERT OR REPLACE INTO stored_products(material_number,name) VALUES(?,?)', (material_text, name_text))
        normalized[material_text] = name_text
    connection.commit()
    return normalized

def _change_entity_type(change: Any) -> str:
    if not isinstance(change, dict):
        return ''
    entity_type = str(change.get('entity_type') or change.get('type') or '').strip().lower()
    if entity_type:
        return entity_type
    payload = change.get('payload') if isinstance(change.get('payload'), dict) else change
    for key in ('material_number', 'expiry_date', 'production_date', 'quantity'):
        if key in payload:
            return 'tracking_item'
    for key in ('usage_product', 'uom', 'unit_of_measure'):
        if key in payload:
            return 'usage_product'
    return ''

def _tracking_changed(changes: list[Any], rows: list[dict[str, Any]]) -> bool:
    if rows:
        return True
    tracking_entities = {'tracking_item', 'tracked_product', 'tracking'}
    return any((_change_entity_type(change) in tracking_entities for change in changes))

def fetch_cloud_snapshot_payload(cloud_service, *, include_snapshot: bool=False) -> dict[str, Any]:
    result: dict[str, Any] = {'preloaded': None, 'online': False, 'rows': [], 'changes': [], 'has_changes': False, 'cursor': 0, 'delta_only': not bool(include_snapshot), 'baseline_loaded': False}
    if cloud_service is None:
        return result
    if not include_snapshot and hasattr(cloud_service, 'sync_pull_temporarily_disabled') and cloud_service.sync_pull_temporarily_disabled():
        result['online'] = True
        result['sync_unavailable'] = True
        return result
    pull_result = cloud_service.pull_now() or {}
    rows = list((pull_result or {}).get('rows') or [])
    changes = list((pull_result or {}).get('changes') or [])
    has_changes = parse_bool((pull_result or {}).get('has_changes'), False) or bool(changes or rows)
    result['rows'] = rows
    result['changes'] = changes
    result['has_changes'] = has_changes
    result['cursor'] = normalize_int((pull_result or {}).get('cursor'), 0)
    result['next_cursor'] = normalize_int((pull_result or {}).get('next_cursor'), result['cursor'])
    result['last_id'] = normalize_int((pull_result or {}).get('last_id'), result['cursor'])
    result['baseline_required'] = parse_bool((pull_result or {}).get('baseline_required'), False)
    result['truncated'] = parse_bool((pull_result or {}).get('truncated'), False)
    result['sync_unavailable'] = parse_bool((pull_result or {}).get('sync_unavailable'), False)
    result['online'] = True
    if include_snapshot or result['baseline_required']:
        try:
            allowed = []
            getter = getattr(cloud_service, 'allowed_branches', None)
            if callable(getter):
                allowed = [str(item).strip() for item in getter() or [] if str(item).strip()]
            if allowed:
                snapshot_rows = []
                for branch in allowed:
                    snapshot_rows.extend(cloud_service.snapshot_items(branch_filter=branch) or [])
                result['preloaded'] = deduplicate_tracking_records(snapshot_rows)
            else:
                result['preloaded'] = cloud_service.snapshot_items(branch_filter='all')
            result['baseline_loaded'] = True
        except SERVICE_OPERATION_EXCEPTIONS:
            result['preloaded'] = rows or None
            result['baseline_loaded'] = bool(rows)
    return result

def prepare_update_check(settings_store, *, force: bool, now_ts: int | None=None) -> tuple[object | None, str, bool]:
    store = settings_store
    current_ts = int(time.time()) if now_ts is None else int(now_ts)
    enabled = parse_bool(store.value('check_updates_on_startup', 'True'), True)
    if not force and (not enabled):
        return (store, '', False)
    last_value = store.value('updates/last_check', 0)
    last_check = int(last_value or 0)
    if not force and last_check and (current_ts - last_check < 12 * 3600):
        skipped = str(store.value('updates/skipped_version', '') or '')
        return (store, skipped, False)
    store.setValue('updates/last_check', current_ts)
    store.sync()
    skipped_version = str(store.value('updates/skipped_version', '') or '')
    return (store, skipped_version, True)
import sys
from collections.abc import Mapping
from runtime.shared.settings.config import source_root_dir
from runtime.services.windows import AutostartService, WindowsRunRegistryBackend

_AUTOSTART_VALUE_NAME = 'HerfyClient'


def _is_windows() -> bool:
    return sys.platform.startswith('win')


def _resolve_dev_python_executable() -> Path:
    executable = Path(sys.executable).resolve()
    if _is_windows():
        pythonw = executable.with_name('pythonw.exe')
        if pythonw.exists():
            return pythonw
    return executable


def _autostart_launch_spec() -> tuple[Path, tuple[str, ...]]:
    if getattr(sys, 'frozen', False):
        return (Path(sys.executable).resolve(), ('--background',))
    return (
        _resolve_dev_python_executable(),
        (str((source_root_dir() / 'main.py').resolve()), '--background'),
    )


def set_start_with_windows(enabled: bool) -> bool:
    if not _is_windows():
        return False
    try:
        executable, arguments = _autostart_launch_spec()
        service = AutostartService(
            _AUTOSTART_VALUE_NAME,
            executable,
            WindowsRunRegistryBackend(),
            arguments,
        )
        if enabled:
            service.enable()
        else:
            service.disable()
        return True
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.exception('Failed to update Windows startup registration')
        return False


def sync_startup_from_preferences(preferences: Mapping[str, bool]) -> bool:
    if not _is_windows():
        return False
    return set_start_with_windows(
        parse_bool(preferences.get('start_with_windows'), False)
    )
from collections.abc import Iterable
from runtime.domain.access import PermissionContext

def normalize_shell_scope(permission_context: PermissionContext | None, allowed_branches: Iterable[str] | None) -> tuple[PermissionContext, list[str]]:
    context = permission_context if isinstance(permission_context, PermissionContext) else PermissionContext()
    branches = [str(branch).strip() for branch in allowed_branches or [] if str(branch).strip()]
    return (context, branches)

def _read_bool_setting(db_manager: Any, key: str, default: bool=False) -> bool:
    if db_manager is None:
        return bool(default)
    try:
        value = db_manager.get_setting(key, 'True' if default else 'False')
        return parse_bool(value, default)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.exception('Failed to read startup setting: %s', key)
        return bool(default)

def normalize_startup_preferences(db_manager: Any, *, persist: bool=False) -> dict[str, bool]:
    start_with_windows = _read_bool_setting(db_manager, 'start_with_windows', False)
    tray_hint = _read_bool_setting(db_manager, 'tray_show_message_on_minimize', False)
    normalized = {'enable_tray_background': True, 'start_with_windows': start_with_windows, 'tray_show_message_on_minimize': tray_hint}
    if persist and db_manager is not None:
        try:
            for key, value in normalized.items():
                db_manager.set_setting(key, 'True' if value else 'False')
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception('Failed to persist normalized startup preferences')
    return normalized

def sync_startup_from_settings(db_manager: Any) -> bool:
    if db_manager is None:
        return False
    try:
        preferences = normalize_startup_preferences(db_manager, persist=True)
        return sync_startup_from_preferences(preferences)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.exception('Failed to sync startup settings')
        return False

def apply_startup_preferences(db_manager: Any) -> bool:
    return sync_startup_from_settings(db_manager)
from runtime.shared.settings.config import _
from runtime.application.services.translations import is_rtl, normalize_language_code

class StartupRuntimeSnapshot:

    def __init__(self, startup_config: dict | None=None, upgrade_plan: dict | None=None, integrity: dict | None=None, server_time: str='') -> None:
        self.startup_config = dict(startup_config or {})
        self.upgrade_plan = dict(upgrade_plan or {})
        self.integrity = dict(integrity or {})
        self.server_time = str(server_time or '')

class ServerRuntimeService:

    def __init__(self, base_url: str | None=None):
        try:
            resolved_base_url = base_url or get_server_base_url(DEFAULT_SERVER_BASE_URL)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('Using default API base URL for server runtime service', exc_info=True)
            resolved_base_url = DEFAULT_SERVER_BASE_URL
        self.base_url = str(resolved_base_url or DEFAULT_SERVER_BASE_URL).rstrip('/')
        self.cache_file = Path(runtime_cache_path('remote_state/startup_runtime.json'))
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _snapshot_from_payload(payload: dict[str, Any] | None) -> StartupRuntimeSnapshot | None:
        data = dict(payload or {})
        if not data:
            return None
        return StartupRuntimeSnapshot(startup_config=dict(data.get('startup_config') or {}), upgrade_plan=dict(data.get('upgrade_plan') or {}), integrity=dict(data.get('integrity') or {}), server_time=str(data.get('server_time') or ''))

    def _save_cache(self, payload: dict[str, Any]) -> None:
        write_json_dict(self.cache_file, dict(payload or {}), ensure_ascii=False)

    def load_cached(self) -> StartupRuntimeSnapshot | None:
        try:
            if not self.cache_file.exists():
                return None
            return self._snapshot_from_payload(read_json_dict(self.cache_file))
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception('Failed to load cached startup runtime snapshot')
            return None

    def fetch_client_bootstrap(self, client_version: str) -> StartupRuntimeSnapshot:
        payload = _fetch_cached_bootstrap(self.base_url, client_version)
        if not payload:
            startup = api_fetch_json('/meta/startup-config', base_url=self.base_url)
            upgrade = api_fetch_json('/updates/upgrade-plan', base_url=self.base_url, params={'client_version': str(client_version or '').strip()})
            integrity = api_fetch_json('/updates/integrity', base_url=self.base_url)
            payload = {'startup_config': startup, 'upgrade_plan': upgrade, 'integrity': integrity, 'server_time': ''}
        self._save_cache(payload)
        snapshot = self._snapshot_from_payload(payload)
        return snapshot or StartupRuntimeSnapshot()

    def apply_startup_config(self, db_manager, snapshot: StartupRuntimeSnapshot | None) -> dict[str, Any]:
        snap = snapshot or self.load_cached()
        if snap is None:
            return {}
        config = dict(snap.startup_config or {})
        thresholds = dict(config.get('alert_thresholds') or {})
        client_runtime = dict(config.get('client_runtime') or {})
        banner = dict(config.get('startup_banner') or {})
        maintenance = dict(config.get('maintenance_mode') or {})
        pairs = {'remote_backend_version': str(config.get('backend_version') or ''), 'remote_api_version': str(config.get('api_version') or ''), 'remote_latest_client_version': str(config.get('latest_client_version') or ''), 'remote_min_supported_client_version': str(config.get('min_supported_client_version') or ''), 'remote_update_channel': str(config.get('update_channel') or ''), 'remote_update_platform': str(config.get('update_platform') or ''), 'remote_update_manifest_url': str(config.get('update_manifest_url') or ''), 'remote_login_message': str(client_runtime.get('login_message') or ''), 'remote_startup_banner': str(banner.get('message') or ''), 'remote_startup_banner_severity': str(banner.get('severity') or 'info'), 'remote_maintenance_enabled': 'True' if parse_bool(maintenance.get('enabled'), False) else 'False', 'remote_maintenance_message': str(maintenance.get('message') or ''), 'remote_force_logout_below_version': str(client_runtime.get('force_logout_below_version') or '')}
        if thresholds.get('warn_days') is not None:
            pairs['expiring_soon_threshold'] = str(normalize_int(thresholds.get('warn_days'), 7))
        if thresholds.get('critical_days') is not None:
            pairs['critical_threshold'] = str(normalize_int(thresholds.get('critical_days'), 2))
        for key, value in pairs.items():
            try:
                db_manager.set_setting(key, value)
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.exception('Failed to persist startup runtime setting: %s', key)
        return {'startup_config': config, 'upgrade_plan': dict(snap.upgrade_plan or {}), 'integrity': dict(snap.integrity or {}), 'server_time': snap.server_time}

    def fetch_and_apply(self, db_manager, client_version: str) -> dict[str, Any]:
        snapshot = self.fetch_client_bootstrap(client_version)
        return self.apply_startup_config(db_manager, snapshot)

@dataclass(frozen=True)
class RuntimeVisibleStateMessage:
    text: str
    timeout_ms: int = 0

class RuntimeVisibleStateService:

    @staticmethod
    def usage_sync_started(*, force_refresh: bool, include_pending: bool) -> RuntimeVisibleStateMessage:
        if force_refresh and include_pending:
            return RuntimeVisibleStateMessage(_('Synchronizing usage changes and refreshing food items...'), 0)
        if include_pending:
            return RuntimeVisibleStateMessage(_('Synchronizing pending usage changes...'), 0)
        if force_refresh:
            return RuntimeVisibleStateMessage(_('Refreshing usage catalog...'), 0)
        return RuntimeVisibleStateMessage('')

    @staticmethod
    def usage_sync_finished(result: dict | None) -> RuntimeVisibleStateMessage:
        payload = result if isinstance(result, dict) else {}
        refreshed = parse_bool(payload.get('refreshed'), False)
        synced = normalize_int(payload.get('synced'), 0)
        if refreshed and synced > 0:
            return RuntimeVisibleStateMessage(_('Usage changes synced and food items refreshed.'), 2800)
        if synced > 0:
            return RuntimeVisibleStateMessage(_('Usage changes synced.'), 2400)
        if refreshed:
            return RuntimeVisibleStateMessage(_('Consumption item catalog refreshed.'), 2400)
        return RuntimeVisibleStateMessage('')

    @staticmethod
    def update_check_started(*, interactive: bool) -> RuntimeVisibleStateMessage:
        if not interactive:
            return RuntimeVisibleStateMessage('')
        return RuntimeVisibleStateMessage(_('Checking for updates...'), 0)

    @staticmethod
    def update_checks_disabled() -> RuntimeVisibleStateMessage:
        return RuntimeVisibleStateMessage(_('Automatic update checks are disabled in Settings.'), 4000)
from runtime.domain.access import PermissionService

@dataclass(frozen=True)
class CloudConnectionViewState:
    online: bool
    status_text: str
    indicator_property: str
    tray_tooltip: str
    status_title: str
    status_message: str
    status_level: str
    should_refresh_on_connect: bool

class CloudConnectionPresenter:

    @staticmethod
    def build(*, online: bool, previous: bool, app_name: str='Herfy PTS') -> CloudConnectionViewState:
        is_online = bool(online)
        was_online = bool(previous)
        status_text = '● ' + (_('Online') if is_online else _('Offline'))
        if is_online:
            status_message = _('Connection restored.')
            status_level = 'ok'
        else:
            status_message = _('Offline Mode — changes will sync when connection returns.')
            status_level = 'warning'
        return CloudConnectionViewState(online=is_online, status_text=status_text, indicator_property='online' if is_online else 'offline', tray_tooltip=f'{app_name} - {status_text}', status_title=_('Connection'), status_message=status_message, status_level=status_level, should_refresh_on_connect=is_online and (not was_online))

@dataclass(frozen=True)
class ShellAccessState:
    has_session: bool
    has_branch_scope: bool
    can_open_home: bool
    can_open_tracking: bool
    can_open_usage: bool
    can_open_about: bool
    can_open_settings: bool
    can_open_admin: bool
    can_manage_stored_products: bool
    can_manage_usage_products: bool
    can_change_own_password: bool
    can_open_notifications: bool
    can_logout: bool
    can_exit: bool
    can_open_admin_dashboard: bool

class ShellAccessService:

    @staticmethod
    def build(*, permission_context: PermissionContext | None=None, has_session: bool=False, allowed_branches: Iterable[str] | None=None, api_client_available: bool=False) -> ShellAccessState:
        ctx, allowed = normalize_shell_scope(permission_context, allowed_branches)
        has_branch_scope = bool(PermissionService.can_view_all(permission_context=ctx) or allowed)
        can_manage_org = bool(PermissionService.can_manage_org(permission_context=ctx))
        return ShellAccessState(has_session=bool(has_session), has_branch_scope=has_branch_scope, can_open_home=True, can_open_tracking=bool(has_session and has_branch_scope), can_open_usage=bool(has_session and has_branch_scope), can_open_about=True, can_open_settings=bool(has_session), can_open_admin=bool(has_session and can_manage_org), can_manage_stored_products=bool(has_session and PermissionService.can_manage_catalog(permission_context=ctx)), can_manage_usage_products=bool(has_session and PermissionService.can_manage_usage(permission_context=ctx)), can_change_own_password=bool(has_session and PermissionService.can_change_own_password(permission_context=ctx)), can_open_notifications=bool(has_session), can_logout=bool(has_session), can_exit=True, can_open_admin_dashboard=bool(has_session and can_manage_org and api_client_available))

@dataclass(frozen=True)
class ShellUserScopeState:
    resolved_view_branch: str
    branch_text: str
    top_info: str
    greeting: str

class ShellUserScopePresenter:

    @staticmethod
    def build(*, permission_context: PermissionContext | None=None, username: str='', allowed_branches: Iterable[str] | None=None, language: str='ar', view_branch: str | None=None) -> ShellUserScopeState:
        ctx, allowed = normalize_shell_scope(permission_context, allowed_branches)
        lang = normalize_language_code(language)
        is_ar = is_rtl(lang)
        user_name = str(username or ctx.username or '').strip()
        resolved_view_branch = str(view_branch if view_branch is not None else ctx.active_branch or '').strip()
        if not resolved_view_branch or resolved_view_branch.lower() == 'all':
            resolved_view_branch = 'all'
        if resolved_view_branch == 'all':
            if PermissionService.can_view_all(permission_context=ctx):
                branch_text = _('All restaurant branches')
            elif len(allowed) > 1:
                branch_text = _('All my restaurant branches')
            else:
                branch_text = allowed[0] if allowed else _('All restaurant branches')
        else:
            branch_text = resolved_view_branch
        role_txt = PermissionService.role_label(permission_context=ctx, language='ar' if is_ar else 'en')
        is_single_branch_scope = PermissionService.is_single_branch_scope(permission_context=ctx)
        if is_single_branch_scope and branch_text:
            greeting = _('Welcome, branch {branch}').format(branch=branch_text)
        elif user_name and branch_text:
            greeting = _('Welcome {username} — branch: {branch}').format(username=user_name, branch=branch_text)
        else:
            greeting = ''
        parts = [part for part in (role_txt, user_name) if part]
        identity = ' '.join(parts).strip()
        compact_identity = role_txt or user_name
        if branch_text:
            top_info = f'{compact_identity} · {branch_text}'.strip(' ·')
        else:
            top_info = identity
        return ShellUserScopeState(resolved_view_branch=resolved_view_branch, branch_text=branch_text, top_info=top_info, greeting=greeting)
