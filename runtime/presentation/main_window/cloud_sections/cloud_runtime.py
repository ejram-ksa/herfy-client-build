from __future__ import annotations
from runtime.application.services.tracking_runtime import tracking_baseline
import logging
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS, UI_OPERATION_EXCEPTIONS
logger = logging.getLogger(__name__)

class CloudPayloadResultControllerMixin:

    def _apply_cloud_payload_result(self, payload, *, event_reason: str, log_context: str) -> None:
        payload = self._apply_remote_delta_payload(payload or {})
        domains = self._domains_from_cloud_payload(payload)
        preloaded = payload.get('preloaded') if isinstance(payload, dict) else None
        self._apply_online_payload_state(payload)
        if not domains and (not preloaded):
            return
        applied_delta = isinstance(payload, dict) and any((isinstance(payload.get(key), dict) and payload[key].get('applied') for key in ('stored_catalog_delta', 'tracking_delta', 'usage_delta')))
        if not applied_delta:
            self._safe_invalidate_cloud_cache()
        if 'usage' in domains and (not self._usage_workspace_is_active()) and (not self._payload_has_usage_delta(payload)):
            self._schedule_usage_sync(force_refresh=False, include_pending=True, delay_ms=120)
        try:
            self._emit_app_state_data_changed(event_reason, preloaded=preloaded, domains=domains, payload=payload)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('%s app-state emission failed', log_context, exc_info=True)
        if 'tracking' in domains:
            try:
                self.check_expiry(preloaded=preloaded, allow_network=False)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('%s expiry refresh failed', log_context, exc_info=True)
from PyQt5.QtCore import QDateTime, QTimer

class CloudRealtimeControllerMixin:

    def _start_realtime_sync(self) -> None:
        service = self.app_state.api_client
        if service is None:
            return
        try:
            service.start_realtime(lambda _message: self.cloud_changed.emit(), on_state=self._on_realtime_transport_state)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('MainWindowCloudMixin._start_realtime_sync fallback failed', exc_info=True)
        self._stop_realtime_fallback_timer()

    def _on_realtime_transport_state(self, connected: bool) -> None:
        self._realtime_transport_connected = bool(connected)
        service = self.app_state.api_client
        try:
            events_available = bool(service.events_mode_available()) if service is not None else True
        except SERVICE_OPERATION_EXCEPTIONS:
            events_available = True
        if not bool(connected):
            if not events_available:
                logger.info('Realtime /events unavailable; keeping API state unchanged and using explicit delta reconciliation.')
            else:
                logger.debug('Realtime transport disconnected; API online state remains unchanged until a request confirms an outage.')
            return
        logger.debug('Realtime transport connected; waiting for data-change events.')

    def _stop_realtime_fallback_timer(self) -> None:
        timer = getattr(self, '_realtime_fallback_timer', None)
        if timer is not None:
            try:
                timer.stop()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('Realtime fallback timer stop failed', exc_info=True)

    def _ensure_realtime_fallback_timer(self):
        timer = getattr(self, '_realtime_fallback_timer', None)
        if timer is not None:
            return timer
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_realtime_fallback_tick)
        self._realtime_fallback_timer = timer
        self._realtime_fallback_running = False
        return timer

    def _on_realtime_fallback_tick(self):
        service = self.app_state.api_client
        if service is None:
            return
        if getattr(self, '_realtime_fallback_running', False):
            return
        self._realtime_fallback_running = True
        runtime_scope_token = self._runtime_scope_token_value()

        def _guarded_realtime_fallback_finished():
            self._realtime_fallback_running = False
            if not self._runtime_scope_is_current(runtime_scope_token):
                return
        self._start_cloud_snapshot_worker(on_result=self._on_realtime_fallback_result, on_finished=_guarded_realtime_fallback_finished, warning_message='change-driven server pull failed', runtime_scope_token=runtime_scope_token, include_snapshot=False)

    def _on_realtime_fallback_result(self, payload):
        self._apply_cloud_payload_result(payload, event_reason='change_driven_pull', log_context='CloudRealtimeControllerMixin._on_realtime_fallback_result')

    def _immediate_server_sync_enabled(self) -> bool:
        try:
            value = str(self.db_manager.get_setting('immediate_server_sync', 'True') or 'True').strip().lower()
            return value not in {'0', 'false', 'no', 'off'}
        except UI_OPERATION_EXCEPTIONS:
            return True

    def _schedule_change_driven_pull(self, domain_text: str, delay_ms: int=650) -> None:
        if self.app_state.api_client is None:
            return
        try:
            pending = getattr(self, '_change_driven_sync_pending_domains', None)
            if not isinstance(pending, set):
                pending = set()
                self._change_driven_sync_pending_domains = pending
            pending.add(str(domain_text or '').strip().lower())
            timer = getattr(self, '_change_driven_sync_timer', None)
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self._run_change_driven_pull)
                self._change_driven_sync_timer = timer
            now_ms = int(QDateTime.currentMSecsSinceEpoch())
            last_ms = int(getattr(self, '_change_driven_last_pull_ms', 0) or 0)
            min_gap_ms = 1400
            remaining_ms = max(0, min_gap_ms - (now_ms - last_ms)) if last_ms else 0
            timer.start(max(int(delay_ms), remaining_ms))
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('Change-driven server pull scheduling failed', exc_info=True)

    def _run_change_driven_pull(self) -> None:
        try:
            self._change_driven_last_pull_ms = int(QDateTime.currentMSecsSinceEpoch())
            self._change_driven_sync_pending_domains = set()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('Change-driven sync metadata update failed', exc_info=True)
        self._on_realtime_fallback_tick()

    def _on_runtime_item_mutation(self, domain: str, payload=None) -> None:
        if not self._immediate_server_sync_enabled():
            return
        if self.app_state.api_client is None:
            return
        domain_text = str(domain or '').strip().lower()
        if domain_text not in {'tracking', 'usage', 'admin'}:
            return
        try:
            self._safe_invalidate_cloud_cache()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('Immediate sync cache invalidation skipped', exc_info=True)
        if domain_text == 'usage':
            self._schedule_usage_sync(force_refresh=False, include_pending=True, delay_ms=350)
            return
        self._schedule_change_driven_pull(domain_text, delay_ms=650)
        if domain_text == 'tracking':
            try:
                QTimer.singleShot(700, lambda: self.check_expiry(allow_network=False))
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('Immediate expiry check scheduling failed', exc_info=True)
from runtime.shared.errors import STATE_OPERATION_EXCEPTIONS
from runtime.domain.user import AuthSession, UserProfile
from runtime.application.services.auth import load_user_profile_from_session
from runtime.application.services.auth import refresh_session
from runtime.application.services.sync import profile_to_cloud_user_payload
from runtime.services.lifecycle import close_runtime_client

class CloudSessionControllerMixin:

    def on_login_success(self, session: AuthSession, profile: UserProfile, remember: bool=False, _restored: bool=False):
        self._mark_runtime_scope_changed()
        self._token_refresh_running = False
        self.app_state.set_session(session)
        self.app_state.set_current_user(profile)
        self._remember_session = bool(remember)
        self._post_contract_update_check_pending = True
        self._login_hydrate_pending = True
        cloud_service = self.container.create_api_client(id_token=session.id_token, user=profile)
        previous_client = getattr(self.app_state, 'api_client', None)
        if previous_client is not None and previous_client is not cloud_service:
            try:
                close_runtime_client(previous_client)
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug('Previous API client cleanup failed', exc_info=True)
        self.app_state.set_api_client(cloud_service)
        self._update_cloud_service_identity(profile)
        self.db_manager.set_cloud_context(cloud_service, profile)
        self._prefetch_allowed_branches_async()
        self._start_realtime_sync()
        self._ensure_home_page()
        self._hydrate_login_state()
        self._schedule_login_followups()
        self._apply_logged_in_shell_state()
        self._configure_token_refresh(session)
        try:
            QTimer.singleShot(0, lambda: self.check_expiry(allow_network=False))
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('Deferred expiry check scheduling failed', exc_info=True)
        self._select_home_page()
        self._safe_save_persistent_session()

    def _hydrate_login_state(self) -> None:
        try:
            track_page = getattr(self, 'track_page', None)
            if track_page is not None:
                track_page.configure_branch_filter()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('MainWindowCloudMixin._hydrate_login_state branch filter setup failed', exc_info=True)
        self._safe_update_user_scope_ui()
        self._safe_refresh_startup_contract_async()
        self._set_top_bar_visible(True)

    def _prefetch_allowed_branches_async(self) -> None:
        """Hydrate all-branch scope without blocking the GUI thread.

        System/admin users may receive an all-branches permission context without
        an explicit branch list in the token.  Fetching /meta/branches directly
        during login used to block the main Qt event loop and could make Windows
        mark the app as "Not Responding" when the server or network was slow.
        """
        service = getattr(getattr(self, 'app_state', None), 'api_client', None)
        db_manager = getattr(self, 'db_manager', None)
        if service is None or db_manager is None:
            return
        try:
            ctx = db_manager.perm_ctx()
            explicit_branches = list(getattr(getattr(ctx, 'scope', None), 'branches', []) or [])
            if explicit_branches:
                db_manager.set_allowed_branches(explicit_branches)
                return
            if not bool(getattr(getattr(ctx, 'scope', None), 'all_branches', False)):
                return
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('Allowed branch prefetch eligibility check failed', exc_info=True)
            return
        runtime_scope_token = self._runtime_scope_token_value()

        def _work(progress_callback=None):
            del progress_callback
            return list(service.meta_branches() or [])

        def _on_result(branches):
            if not self._runtime_scope_is_current(runtime_scope_token):
                return
            cleaned = [str(branch).strip() for branch in branches or [] if str(branch).strip()]
            if not cleaned:
                return
            try:
                db_manager.set_allowed_branches(cleaned)
                self._safe_update_user_scope_ui()
                home_page = getattr(self, 'home_page', None)
                if home_page is not None:
                    home_page.refresh_dashboard(profile=getattr(self.app_state, 'current_user', None), permission_context=db_manager.perm_ctx())
                track_page = getattr(self, 'track_page', None)
                if track_page is not None:
                    track_page.configure_branch_filter()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('Allowed branch prefetch result apply failed', exc_info=True)
        self._start_logged_worker(_work, on_result=_on_result, warning_message='allowed branch prefetch failed', operation_key='allowed_branch_prefetch')

    def _schedule_login_followups(self) -> None:
        # The hydrate operation is already asynchronous and de-duplicated by its
        # operation key. Queue it for the next event-loop turn rather than using
        # a device-dependent fixed delay.
        QTimer.singleShot(0, self._initial_cloud_hydrate_async)

    def _apply_logged_in_shell_state(self) -> None:
        self._apply_logged_in_shell()
        self.apply_role_permissions()
        self._apply_monitor_schedule(restart=True)
        self.set_daily_timer()
        self._sync_notifications_panel_direction()

    def _configure_token_refresh(self, session: AuthSession) -> None:
        try:
            expires = int(getattr(session, 'expires_in', 3600))
        except (TypeError, ValueError):
            expires = 3600
        try:
            refresh_after = max(300, int(expires) - 600)
            self.token_refresh_timer.setInterval(refresh_after * 1000)
            self.token_refresh_timer.start()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('MainWindowCloudMixin._configure_token_refresh fallback failed', exc_info=True)

    def _profile_cloud_user_payload(self, profile: UserProfile | None=None) -> dict:
        try:
            return profile_to_cloud_user_payload(profile or self.app_state.current_user)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('MainWindowCloudMixin._profile_cloud_user_payload fallback failed', exc_info=True)
            return {}

    def _update_cloud_service_identity(self, profile: UserProfile | None=None):
        service = self.app_state.api_client
        if service is None:
            return
        try:
            service.user = self._profile_cloud_user_payload(profile)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('MainWindowCloudMixin._update_cloud_service_identity fallback failed', exc_info=True)

    def refresh_cloud_token(self):
        """Refresh the session token in a worker to keep the Qt UI responsive."""
        if getattr(self, '_token_refresh_running', False):
            return
        session = self.app_state.session
        if not session:
            return
        refresh_token_value = str(getattr(session, 'refresh_token', '') or '').strip()
        if not refresh_token_value:
            return
        username = str(getattr(self.app_state.current_user, 'username', '') or getattr(session, 'uid', '') or '').strip()
        self._token_refresh_running = True
        runtime_scope_token = self._runtime_scope_token_value()

        def _work(progress_callback=None):
            del progress_callback
            new_session = refresh_session(refresh_token_value, username)
            new_profile = load_user_profile_from_session(new_session, username)
            if not new_profile:
                return {}
            return {'session': new_session, 'profile': new_profile}

        def _on_result(payload):
            if not self._runtime_scope_is_current(runtime_scope_token):
                return
            data = payload if isinstance(payload, dict) else {}
            new_session = data.get('session')
            new_profile = data.get('profile')
            if not new_session or not new_profile:
                return
            self.app_state.set_session(new_session)
            self.app_state.set_current_user(new_profile)
            service = self.app_state.api_client
            if service is not None:
                try:
                    service.id_token = new_session.id_token
                    self._update_cloud_service_identity(new_profile)
                except STATE_OPERATION_EXCEPTIONS:
                    logger.debug('MainWindowCloudMixin.refresh_cloud_token service refresh failed', exc_info=True)
            try:
                self.db_manager.set_cloud_context(self.app_state.api_client, new_profile)
                self._prefetch_allowed_branches_async()
            except STATE_OPERATION_EXCEPTIONS:
                logger.debug('MainWindowCloudMixin.refresh_cloud_token db context refresh failed', exc_info=True)
            self._safe_save_persistent_session()

        def _on_finished():
            self._token_refresh_running = False
        self._start_logged_worker(_work, on_result=_on_result, on_finished=_on_finished, warning_message='token refresh failed', operation_key='token_refresh')
from runtime.shared.objects import call_if_callable, normalize_int
from runtime.shared.booleans import parse_bool
from runtime.application.services.sync import apply_remote_catalog_snapshot as reconcile_catalog_snapshot, fetch_cloud_snapshot_payload as load_cloud_change_payload

class CloudSnapshotControllerMixin:

    def _cloud_sync_cursor_value(self) -> int:
        try:
            return int(self.db_manager.get_setting('server_sync_cursor', '0') or 0)
        except (TypeError, ValueError, *SERVICE_OPERATION_EXCEPTIONS):
            return 0

    def _has_local_tracking_baseline(self) -> bool:
        checker = getattr(self.db_manager, 'fetch_cached_tracked_products', None)
        if not callable(checker):
            return False
        try:
            return bool(checker('all'))
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('Local tracking baseline check failed', exc_info=True)
            return False

    def _cloud_tracking_baseline_loaded(self) -> bool:
        try:
            value = str(self.db_manager.get_setting('cloud_tracking_baseline_loaded', '0') or '0')
        except SERVICE_OPERATION_EXCEPTIONS:
            return False
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}

    def _mark_cloud_tracking_baseline_loaded(self, payload) -> None:
        if not isinstance(payload, dict):
            return
        if not parse_bool(payload.get('baseline_loaded'), False):
            return
        try:
            self.db_manager.set_setting('cloud_tracking_baseline_loaded', '1')
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('Cloud tracking baseline flag persist skipped', exc_info=True)

    def _should_request_initial_tracking_snapshot(self) -> bool:
        if self._cloud_sync_cursor_value() <= 0:
            return True
        return not self._has_local_tracking_baseline()

    def _apply_remote_catalog_to_local(self, snapshot: dict | None=None):
        """Apply an already-fetched catalog snapshot without blocking the UI.

        This method used to call service.stored_snapshot() directly from result
        handlers.  That performs HTTP requests and can make Windows mark the
        application as "Not Responding" when the server is slow.  Network catalog
        refreshes must run in workers and pass their snapshot here.
        """
        if not isinstance(snapshot, dict) or not snapshot:
            return
        try:
            normalized = reconcile_catalog_snapshot(self.db_manager, snapshot)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug('MainWindowCloudMixin._apply_remote_catalog_to_local fallback failed', exc_info=True)
            return
        cache = getattr(self.db_manager, '_stored_name_cache', None)
        if isinstance(cache, dict):
            cache.update(normalized)

    def _load_cloud_change_payload(self, *, include_snapshot: bool=False):
        try:
            return load_cloud_change_payload(self.app_state.api_client, include_snapshot=bool(include_snapshot))
        except SERVICE_OPERATION_EXCEPTIONS:
            return {'preloaded': None, 'online': False, 'rows': [], 'changes': []}

    def _persist_cloud_sync_cursor(self, payload) -> bool:
        if not isinstance(payload, dict):
            return False
        cursor = normalize_int(payload.get('next_cursor') or payload.get('cursor'), 0)
        if cursor <= 0:
            return False
        try:
            self.db_manager.set_setting('server_sync_cursor', str(cursor))
            service = getattr(self.app_state, 'api_client', None)
            if service is not None and hasattr(service, 'set_sync_cursor'):
                service.set_sync_cursor(cursor)
            return True
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception('Cloud sync cursor persist failed')
            return False

    def _store_initial_tracking_baseline(self, payload) -> bool:
        data = payload if isinstance(payload, dict) else {}
        if not parse_bool(data.get('baseline_loaded'), False):
            return not parse_bool(data.get('baseline_required'), False)
        rows = data.get('preloaded')
        if not isinstance(rows, list):
            return False
        store = getattr(self.db_manager, 'replace_cached_cloud_tracking_products', None)
        if not callable(store):
            return False
        try:
            return bool(store(rows))
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception('Initial tracking baseline persistence failed')
            return False

    def _apply_remote_delta_payload(self, payload, *, commit_cursor: bool=True):
        data = payload if isinstance(payload, dict) else {}
        if parse_bool(data.get('delta_applied'), False):
            return data
        changes = data.get('changes') or []
        if not isinstance(changes, list):
            changes = []
        apply_failed = False
        if changes:
            try:
                if hasattr(self.db_manager, 'apply_remote_stored_product_changes'):
                    data['stored_catalog_delta'] = self.db_manager.apply_remote_stored_product_changes(changes)
            except SERVICE_OPERATION_EXCEPTIONS:
                apply_failed = True
                logger.exception('Stored catalog delta apply failed')
            try:
                if hasattr(self.db_manager, 'apply_remote_tracking_changes'):
                    data['tracking_delta'] = self.db_manager.apply_remote_tracking_changes(changes)
            except SERVICE_OPERATION_EXCEPTIONS:
                apply_failed = True
                logger.exception('Tracking delta apply failed')
            try:
                if hasattr(self.db_manager, 'apply_remote_usage_changes'):
                    data['usage_delta'] = self.db_manager.apply_remote_usage_changes(changes)
            except SERVICE_OPERATION_EXCEPTIONS:
                apply_failed = True
                logger.exception('Usage delta apply failed')
        data['delta_apply_failed'] = apply_failed
        data['delta_applied'] = True
        if commit_cursor and (not apply_failed):
            data['cursor_committed'] = self._persist_cloud_sync_cursor(data)
        else:
            data['cursor_committed'] = False
        return data

    def _payload_has_usage_delta(self, payload) -> bool:
        data = payload if isinstance(payload, dict) else {}
        delta = data.get('usage_delta') if isinstance(data.get('usage_delta'), dict) else {}
        return parse_bool(delta.get('applied'), False)

    def _start_cloud_snapshot_worker(self, *, on_result, on_finished=None, warning_message: str, runtime_scope_token: int | None=None, include_snapshot: bool=False, prepare_initial: bool=False):
        operation_key = 'cloud_snapshot:initial' if prepare_initial else 'cloud_snapshot:pull'
        registry = getattr(self, '_worker_registry', None)
        if registry is not None and hasattr(registry, 'has_active_key') and registry.has_active_key(operation_key):
            if not prepare_initial:
                self._cloud_snapshot_pull_pending = True
            if on_finished is not None:
                try:
                    QTimer.singleShot(0, on_finished)
                except UI_OPERATION_EXCEPTIONS:
                    logger.debug('Duplicate cloud snapshot finish scheduling failed', exc_info=True)
            return None
        guarded_result = on_result
        if runtime_scope_token is not None and on_result is not None:
            token = int(runtime_scope_token)

            def _guarded_result(payload, _on_result=on_result, _token=token):
                if self._runtime_scope_is_current(_token):
                    return _on_result(payload)
                return None
            guarded_result = _guarded_result

        def _work(progress_callback=None):
            del progress_callback
            payload = self._load_cloud_change_payload(include_snapshot=include_snapshot)
            if prepare_initial:
                data = payload if isinstance(payload, dict) else {}
                baseline_ok = self._store_initial_tracking_baseline(data)
                needs_baseline = parse_bool(data.get('baseline_required'), False)
                data['initial_baseline_persisted'] = baseline_ok
                data = self._apply_remote_delta_payload(data, commit_cursor=baseline_ok or not needs_baseline)
                if baseline_ok and (not data.get('delta_apply_failed')):
                    self._mark_cloud_tracking_baseline_loaded(data)
                data['initial_hydrate_prepared'] = True
                return data
            return self._apply_remote_delta_payload(payload)

        def _guarded_finished():
            if on_finished is not None:
                on_finished()
            if prepare_initial:
                return
            if bool(getattr(self, '_cloud_snapshot_pull_pending', False)):
                self._cloud_snapshot_pull_pending = False
                try:
                    QTimer.singleShot(250, self._on_cloud_changed)
                except UI_OPERATION_EXCEPTIONS:
                    logger.debug('Pending cloud snapshot replay scheduling failed', exc_info=True)
        return self._start_logged_worker(_work, on_result=guarded_result, on_finished=_guarded_finished, warning_message=warning_message, operation_key=operation_key)

    def _on_cloud_changed(self):
        if getattr(self, '_cloud_change_running', False):
            self._cloud_change_pending = True
            return
        self._cloud_change_running = True
        self._cloud_change_pending = False
        runtime_scope_token = self._runtime_scope_token_value()

        def _guarded_cloud_change_finished():
            self._cloud_change_running = False
            if not self._runtime_scope_is_current(runtime_scope_token):
                self._cloud_change_pending = False
                return
            if getattr(self, '_cloud_change_pending', False):
                self._cloud_change_pending = False
                QTimer.singleShot(250, self._on_cloud_changed)
        self._start_cloud_snapshot_worker(on_result=self._on_cloud_changed_result, on_finished=_guarded_cloud_change_finished, warning_message='cloud change refresh failed', runtime_scope_token=runtime_scope_token)

    def _emit_app_state_data_changed(self, reason: str, preloaded=None, *, domains: set[str] | None=None, payload=None) -> None:
        state = getattr(self, 'app_state', None)
        if state is None:
            return
        wanted = {str(item).strip().lower() for item in domains or {'tracking', 'usage', 'admin'} if str(item).strip()}
        base_payload = dict(payload or {}) if isinstance(payload, dict) else {}
        base_payload['reason'] = reason
        base_payload['preloaded'] = preloaded
        if 'tracking' in wanted:
            state.emit_data_changed('tracking', dict(base_payload))
        if 'usage' in wanted:
            state.emit_data_changed('usage', dict(base_payload))
        if 'admin' in wanted:
            state.emit_data_changed('admin', dict(base_payload))

    def _domains_from_cloud_payload(self, payload) -> set[str]:
        data = payload if isinstance(payload, dict) else {}
        changes = data.get('changes') or []
        if not isinstance(changes, list):
            changes = []
        if data.get('preloaded') is not None or data.get('rows'):
            domains = {'tracking'}
        else:
            domains = set()
        for change in changes:
            if not isinstance(change, dict):
                continue
            entity = str(change.get('entity_type') or change.get('type') or '').strip().lower()
            payload_obj = change.get('payload') if isinstance(change.get('payload'), dict) else change
            if entity in {'tracking_item', 'tracked_product', 'tracking', 'stored_product', 'catalog_product', 'product'}:
                domains.add('tracking')
            elif entity in {'usage', 'usage_product', 'usage_products', 'catalog_usage'}:
                domains.add('usage')
            elif entity in {'admin', 'org', 'region', 'area', 'branch', 'department', 'user', 'permission', 'permissions', 'role', 'scope'}:
                domains.add('admin')
            elif isinstance(payload_obj, dict):
                keys = {str(key).strip().lower() for key in payload_obj}
                if keys & {'material_number', 'material_code', 'expiry_date', 'production_date', 'quantity'}:
                    domains.add('tracking')
                elif keys & {'uom', 'unit_of_measure', 'usage_product'}:
                    domains.add('usage')
                elif keys & {'region_id', 'area_id', 'branch_id', 'username', 'permissions', 'role'}:
                    domains.add('admin')
        if not domains and parse_bool(data.get('has_changes'), False):
            return {'tracking', 'admin'}
        return domains

    def _usage_workspace_is_active(self) -> bool:
        page = getattr(self, 'usage_page', None)
        if page is None:
            return False
        checker = getattr(page, '_usage_workspace_has_active_input', None)
        if callable(checker):
            try:
                return bool(call_if_callable(checker, default=False))
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('Usage workspace active check failed', exc_info=True)
        return bool(str(getattr(page, '_receipts_path', '') or '').strip() or str(getattr(page, '_beginning_path', '') or '').strip() or getattr(getattr(page, 'model', None), 'rowCount', lambda: 0)() > 0)

    def _on_cloud_changed_result(self, payload):
        self._apply_cloud_payload_result(payload, event_reason='server_push', log_context='CloudSnapshotControllerMixin._on_cloud_changed_result')

    def _initial_cloud_hydrate_async(self):
        if self.app_state.api_client is None:
            return
        runtime_scope_token = self._runtime_scope_token_value()

        def _guarded_initial_hydrate_finished():
            if not self._runtime_scope_is_current(runtime_scope_token):
                return
            self._on_initial_cloud_hydrate_finished()
        self._start_cloud_snapshot_worker(on_result=self._on_initial_cloud_hydrate_result, on_finished=_guarded_initial_hydrate_finished, warning_message='initial cloud hydrate failed', runtime_scope_token=runtime_scope_token, include_snapshot=self._should_request_initial_tracking_snapshot(), prepare_initial=True)

    def _on_initial_cloud_hydrate_result(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        if not parse_bool(payload.get('initial_hydrate_prepared'), False):
            baseline_ok = self._store_initial_tracking_baseline(payload)
            needs_baseline = parse_bool(payload.get('baseline_required'), False)
            payload = self._apply_remote_delta_payload(payload, commit_cursor=baseline_ok or not needs_baseline)
            if baseline_ok and (not payload.get('delta_apply_failed')):
                self._mark_cloud_tracking_baseline_loaded(payload)
        self._apply_online_payload_state(payload, show_status_feedback=False)
        preloaded = payload.get('preloaded')
        if preloaded is not None:
            tracking_baseline.publish(preloaded, source='initial_hydrate')
        self._emit_app_state_data_changed('initial_hydrate', preloaded=preloaded, domains={'tracking'}, payload=payload)

    def _on_initial_cloud_hydrate_finished(self):
        self._login_hydrate_pending = False
        # Usage synchronization depends on the initial cloud hydration finishing.
        # Queue it immediately instead of guessing a device/network-dependent delay.
        self._schedule_usage_sync(
            force_refresh=True,
            include_pending=True,
            delay_ms=0,
        )
from runtime.application.services.sync import CloudConnectionPresenter
from runtime.application.services.sync import CloudReconnectFlowService
from runtime.application.services.sync import RuntimeVisibleStateService
from runtime.presentation.main_window.widgets import show_runtime_notice

class CloudStatusControllerMixin:

    def _set_cloud_state(self, online: bool, *, show_status_feedback: bool=True) -> None:
        try:
            state_was_known = bool(getattr(self, '_cloud_state_known', False))
            previous = bool(getattr(self, '_cloud_online', False))
            view_state = CloudConnectionPresenter.build(online=bool(online), previous=previous)
            state_changed = (not state_was_known) or view_state.online != previous
            self._cloud_online = view_state.online
            self._cloud_state_known = True
            if getattr(self, 'app_state', None) is not None:
                self.app_state.set_connection_state(view_state.online, view_state.status_text)
            if getattr(self, 'net_indicator', None) is not None:
                self.net_indicator.setText(view_state.status_text)
                self.net_indicator.setProperty('net', view_state.indicator_property)
                try:
                    self.net_indicator.style().unpolish(self.net_indicator)
                    self.net_indicator.style().polish(self.net_indicator)
                except UI_OPERATION_EXCEPTIONS:
                    logger.debug('MainWindowCloudMixin._set_cloud_state style refresh failed', exc_info=True)
            tray_icon = getattr(self, 'tray_icon', None)
            if tray_icon is not None:
                try:
                    tray_icon.setToolTip(view_state.tray_tooltip)
                except UI_OPERATION_EXCEPTIONS:
                    logger.debug('MainWindowCloudMixin._set_cloud_state tray tooltip refresh failed', exc_info=True)
            if not state_changed:
                return
            reconnect_flow = CloudReconnectFlowService.evaluate(online=view_state.online, previous_online=previous, session_active=bool(getattr(self.app_state, 'session', None)), login_hydrate_pending=bool(getattr(self, '_login_hydrate_pending', False)))
            if reconnect_flow.should_invalidate_cache:
                self._safe_invalidate_cloud_cache()
            if reconnect_flow.should_refresh_usage and (not self._usage_workspace_is_active()):
                self._schedule_usage_sync(force_refresh=False, include_pending=True, delay_ms=120)
            if reconnect_flow.should_emit_data_refresh:
                try:
                    self._emit_app_state_data_changed('reconnected')
                except SERVICE_OPERATION_EXCEPTIONS:
                    logger.debug('MainWindowCloudMixin._set_cloud_state app-state reconnect emission failed', exc_info=True)
            try:
                self._show_runtime_status_message(view_state.status_message, 4000)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('MainWindowCloudMixin._set_cloud_state shell status fallback failed', exc_info=True)
            self._show_connection_status(should_show=bool(show_status_feedback), title=view_state.status_title, message=view_state.status_message, level=view_state.status_level)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('MainWindowCloudMixin._set_cloud_state fallback failed', exc_info=True)

    def _show_connection_status(self, *, should_show: bool, title: str, message: str, level: str) -> None:
        if not should_show:
            return
        try:
            now_ms = int(QDateTime.currentMSecsSinceEpoch())
            status_key = f'{level}:{message}'
            last_key = str(getattr(self, '_last_connection_status_key', '') or '')
            last_ms = int(getattr(self, '_last_connection_status_ms', 0) or 0)
            if status_key == last_key and last_ms and (now_ms - last_ms < 60000):
                return
            self._last_connection_status_key = status_key
            self._last_connection_status_ms = now_ms
            if hasattr(self, '_show_runtime_status_message'):
                self._show_runtime_status_message(str(message or title or ''), 4000)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('MainWindowCloudMixin._show_connection_status failed', exc_info=True)

    def _schedule_usage_sync(self, *, force_refresh: bool=False, include_pending: bool=True, delay_ms: int=120):
        timer = getattr(self, '_usage_sync_request_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._sync_usage_products_async(force_refresh=bool(getattr(self, '_usage_sync_force_refresh', False)), include_pending=bool(getattr(self, '_usage_sync_include_pending', True))))
            self._usage_sync_request_timer = timer
        self._usage_sync_force_refresh = bool(getattr(self, '_usage_sync_force_refresh', False) or force_refresh)
        self._usage_sync_include_pending = bool(getattr(self, '_usage_sync_include_pending', False) or include_pending)
        timer.start(max(0, int(delay_ms)))

    def _sync_usage_products_async(self, *, force_refresh: bool=False, include_pending: bool=True):
        if getattr(self, '_usage_sync_running', False):
            self._usage_sync_pending = self._usage_sync_pending or bool(force_refresh or include_pending)
            return
        if self.db_manager.app_state.api_client is None:
            return
        self._usage_sync_running = True
        self._usage_sync_pending = False
        self._usage_sync_force_refresh = False
        self._usage_sync_include_pending = True
        self._last_usage_sync_result = None
        start_message = RuntimeVisibleStateService.usage_sync_started(force_refresh=bool(force_refresh), include_pending=bool(include_pending))
        show_runtime_notice(self, start_message, logger_=logger, context='usage synchronization')

        def _work(progress_callback=None):
            result = {'refreshed': False, 'synced': 0}
            if include_pending:
                try:
                    result.update(self.db_manager.sync_pending_usage_changes() or {})
                except SERVICE_OPERATION_EXCEPTIONS:
                    logger.debug('MainWindowCloudMixin._sync_usage_products_async pending sync failed', exc_info=True)
            if force_refresh:
                try:
                    rows = self.db_manager.refresh_usage_products_from_server(force_refresh=True)
                    result['refreshed'] = True
                    result['count'] = len(rows or [])
                except SERVICE_OPERATION_EXCEPTIONS:
                    logger.debug('MainWindowCloudMixin._sync_usage_products_async server refresh failed', exc_info=True)
            return result
        self._start_logged_worker(_work, on_result=self._on_usage_sync_result, on_finished=self._on_usage_sync_finished, warning_message='usage products sync', operation_key='usage_products_sync')

    def _on_usage_sync_result(self, payload):
        self._last_usage_sync_result = payload if isinstance(payload, dict) else {}

    def _on_usage_sync_finished(self):
        self._usage_sync_running = False
        finish_message = RuntimeVisibleStateService.usage_sync_finished(getattr(self, '_last_usage_sync_result', None))
        if finish_message.text:
            try:
                self._show_runtime_status_message(finish_message.text, finish_message.timeout_ms)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('MainWindowCloudMixin._on_usage_sync_finished status fallback failed', exc_info=True)
        if getattr(self, '_usage_sync_pending', False):
            pending_force = bool(getattr(self, '_usage_sync_force_refresh', False))
            pending_include = bool(getattr(self, '_usage_sync_include_pending', True))
            self._usage_sync_pending = False
            QTimer.singleShot(200, lambda: self._sync_usage_products_async(force_refresh=pending_force, include_pending=pending_include))
from runtime.shared.settings.config import _
from PyQt5.QtWidgets import QApplication
from runtime.shared.settings.version import __version__ as APP_VERSION
from runtime.application.services.sync import prepare_update_check as resolve_update_check_state
from runtime.application.services.updates import PatchUpdateService
from runtime.application.services.updates import fetch_preferred_update, normalize_update_payload
from runtime.presentation.updates.update_flow import OnlineUpdateService, prompt_installer_update_action, prompt_patch_update_action
from runtime.presentation.widgets import show_info_message

class MainWindowUpdatesMixin:

    def _resolve_update_check_state(self, force: bool=False):
        settings_store = None
        try:
            settings_store = self._settings_store()
            return resolve_update_check_state(settings_store, force=force)
        except SERVICE_OPERATION_EXCEPTIONS:
            return (settings_store, '', False)

    def _prompt_patch_update(self, info) -> None:
        notes = str(getattr(info, 'notes', '') or '').strip()
        action = prompt_patch_update_action(self, info, title=_('Remote update available'), details=_('A partial remote update is available') + f' ({info.target_version}).', informative_text=notes or _('Do you want to apply the update now?'), primary_text=_('Apply Update'), secondary_text=_('Later'))
        if action == 'primary':
            OnlineUpdateService(APP_VERSION).download_and_apply(self, info)

    def _save_skipped_update_version(self, settings_store, version: str) -> None:
        if settings_store is None or not str(version or '').strip():
            return
        settings_store.setValue('updates/skipped_version', version)
        settings_store.sync()

    def _quit_for_required_update(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()
            return
        raise SystemExit(0)

    def _update_menu_badge_text(self, base_text: str, *, available: bool, mandatory: bool=False) -> str:
        if mandatory:
            return f'{base_text}  1'
        if available:
            return f'{base_text}  1'
        return base_text

    def _prompt_installer_update(self, info, settings_store=None) -> None:
        notes = str(getattr(info, 'notes', '') or '').strip()
        mandatory = bool(getattr(info, 'mandatory', False))
        action = prompt_installer_update_action(self, info, title=_('Required update') if mandatory else _('Update available'), details=_('A newer version is available') + f' ({info.latest}).', informative_text=notes or (_('This update is required. Please update now to continue.') if mandatory else _('Do you want to update now?')), primary_text=_('Update Now'), secondary_text=_('Exit') if mandatory else _('Later'), tertiary_text=None if mandatory else _('Skip Version'), mandatory=mandatory)
        if action == 'primary' and getattr(info, 'url', ''):
            OnlineUpdateService(APP_VERSION).download_installer_and_run(self, info)
            return
        if mandatory:
            self._quit_for_required_update()
            return
        if action == 'tertiary':
            self._save_skipped_update_version(settings_store, getattr(info, 'latest', ''))

    def _maybe_check_updates(self, *, force: bool=False, interactive: bool=False):
        if getattr(self, '_update_check_running', False):
            return
        self._update_check_running = True
        settings_store, skipped_version, should_check = self._resolve_update_check_state(force=force)
        if not should_check:
            self._update_check_running = False
            if interactive:
                disabled_message = RuntimeVisibleStateService.update_checks_disabled()
                try:
                    self._show_runtime_status_message(disabled_message.text, disabled_message.timeout_ms)
                except UI_OPERATION_EXCEPTIONS:
                    logger.debug('MainWindowUpdatesMixin._maybe_check_updates status fallback failed', exc_info=True)
                show_info_message(self, _('Updates'), _('Automatic update checks are disabled in Settings.'))
            return
        start_message = RuntimeVisibleStateService.update_check_started(interactive=bool(interactive))
        show_runtime_notice(self, start_message, logger_=logger, context='update check')
        runtime_scope_token = self._runtime_scope_token_value()

        def _guarded_update_result(payload):
            if not self._runtime_scope_is_current(runtime_scope_token):
                return
            self._on_update_check_result(payload, settings_store, interactive=interactive)

        def _guarded_update_finished():
            self._update_check_running = False

        def _update_work(progress_callback=None):
            del progress_callback
            return fetch_preferred_update(current_version=APP_VERSION, skipped_version=skipped_version, patch_fetcher=lambda current_version: PatchUpdateService(current_version).fetch(), installer_fetcher=lambda current_version, version_to_skip: self.container.update_manager_factory(current_version).fetch(skipped_version=version_to_skip))
        self._start_logged_worker(_update_work, on_result=_guarded_update_result, on_finished=_guarded_update_finished, warning_message='Update check failed', operation_key='update_check')

    def _set_update_action_badge(self, *, available: bool, mandatory: bool=False) -> None:
        set_tray_update = getattr(self, 'set_tray_update_available', None)
        if callable(set_tray_update):
            set_tray_update(bool(available))
        base_text = _('Check for Updates')
        badge_text = self._update_menu_badge_text(base_text, available=available, mandatory=mandatory)
        action = getattr(self, 'act_check_updates', None)
        if action is not None:
            action.setText(badge_text)
            if mandatory:
                action.setToolTip(_('Required update available'))
            elif available:
                action.setToolTip(_('Update available'))
            else:
                action.setToolTip(base_text)
        menu_button = getattr(self, 'btn_menu_file', None)
        if menu_button is not None:
            try:
                file_text = _('File')
                menu_button.setText(self._update_menu_badge_text(file_text, available=available, mandatory=mandatory))
                if mandatory:
                    menu_button.setToolTip(_('File menu — required update available'))
                elif available:
                    menu_button.setToolTip(_('File menu — update available'))
                else:
                    menu_button.setToolTip(file_text)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('Update badge menu-button update failed', exc_info=True)

    def check_for_updates_now(self):
        self._maybe_check_updates(force=True, interactive=True)

    def _on_update_check_result(self, payload, settings_store=None, *, interactive: bool=False):
        try:
            kind, info = normalize_update_payload(payload)
            if not getattr(info, 'available', False):
                self._set_update_action_badge(available=False)
                if interactive:
                    OnlineUpdateService(APP_VERSION).show_no_update_popup(self, APP_VERSION)
                return
            self._set_update_action_badge(available=True, mandatory=bool(getattr(info, 'mandatory', False)))
            if kind == 'patch':
                self._prompt_patch_update(info)
                return
            self._prompt_installer_update(info, settings_store=settings_store)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception('Update dialog failed')

class MainWindowCloudMixin(CloudSessionControllerMixin, CloudPayloadResultControllerMixin, CloudRealtimeControllerMixin, CloudSnapshotControllerMixin, CloudStatusControllerMixin):
    """Composition surface for cloud-related presentation controllers."""
__all__ = ['CloudPayloadResultControllerMixin', 'CloudRealtimeControllerMixin', 'CloudSessionControllerMixin', 'CloudSnapshotControllerMixin', 'CloudStatusControllerMixin', 'MainWindowCloudMixin', 'MainWindowUpdatesMixin']
