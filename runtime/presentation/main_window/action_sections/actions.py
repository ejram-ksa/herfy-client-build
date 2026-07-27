from __future__ import annotations
import logging
from contextlib import suppress
from PyQt5.QtCore import QTimer
from runtime.shared.settings.config import _
from PyQt5.QtWidgets import QInputDialog
from runtime.presentation.widgets import DialogFeedbackMixin
from runtime.bootstrap.qt.workers import WorkerRegistry, client_thread_pool
from runtime.presentation.widgets import set_widget_visible
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.services.lifecycle import close_runtime_client

logger = logging.getLogger(__name__)

class MainWindowActionSupportMixin(DialogFeedbackMixin):

    def _run_ui_fallback(self, action, label: str) -> None:
        try:
            action()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('MainWindowUiMixin.%s fallback failed', label, exc_info=True)

    def _show_inline_status(self, title: str | None=None, message: str | None=None, *, level: str='info', timeout_ms: int=5000) -> None:
        """Show user feedback in the shell status area without a floating popup.

        This is used for routine client feedback such as permissions, missing
        cloud context, failed background actions, and successful maintenance
        operations.  Destructive confirmations still use explicit dialogs.
        """
        parts = [str(part or '').strip() for part in (title, message)]
        text = ' — '.join((part for part in parts if part))
        if not text:
            return
        try:
            if hasattr(self, '_show_runtime_status_message'):
                self._show_runtime_status_message(text, int(timeout_ms or 0))
                return
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('Inline shell status message failed', exc_info=True)
        log_fn = logger.warning if str(level).lower() in {'warning', 'error'} else logger.info
        log_fn('%s', text)

    def _show_inline_error(self, title: str | None, message: str | None) -> None:
        """Show an error in the shell status area without a modal popup."""
        self._show_inline_status(title, message, level='error', timeout_ms=7000)

    def _show_inline_warning(self, title: str | None, message: str | None) -> None:
        """Show a warning in the shell status area without a modal popup."""
        self._show_inline_status(title, message, level='warning', timeout_ms=6500)

    def _show_inline_info(self, title: str | None, message: str | None) -> None:
        """Show an informational message in the shell status area without a modal popup."""
        self._show_inline_status(title, message, level='info', timeout_ms=5000)

    def _track_active_worker(self, worker) -> None:
        """Track a live worker so logout/session changes can cancel it cooperatively."""
        try:
            workers = getattr(self, '_active_workers', None)
            if not isinstance(workers, set):
                workers = set()
                self._active_workers = workers
            workers.add(worker)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('Active worker tracking failed', exc_info=True)

    def _untrack_active_worker(self, worker) -> None:
        """Remove a worker from the live-worker registry."""
        try:
            workers = getattr(self, '_active_workers', None)
            if isinstance(workers, set):
                workers.discard(worker)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('Active worker untracking failed', exc_info=True)

    def _reset_async_running_flags(self) -> None:
        for flag_name in ('_restore_session_running', '_startup_contract_running', '_update_check_running', '_cloud_change_running', '_cloud_snapshot_pull_pending', '_usage_sync_running', '_token_refresh_running', '_realtime_fallback_running', '_expiry_running'):
            with suppress(UI_OPERATION_EXCEPTIONS):
                setattr(self, flag_name, False)

    def _cancel_active_workers(self, reason: str='runtime_scope_changed') -> None:
        """Request cooperative cancellation for shell workers from the old scope."""
        self._reset_async_running_flags()
        registry = getattr(self, '_worker_registry', None)
        if registry is not None and hasattr(registry, 'cancel_all'):
            try:
                registry.cancel_all()
                return
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('Worker registry cancellation failed during %s', reason, exc_info=True)
        workers = list(getattr(self, '_active_workers', set()) or [])
        try:
            active_keys = getattr(self, '_active_worker_keys', None)
            if isinstance(active_keys, set):
                active_keys.clear()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('Worker key cleanup failed during %s', reason, exc_info=True)
        for worker in workers:
            try:
                cancel = getattr(worker, 'cancel', None)
                if callable(cancel):
                    cancel()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('Worker cancellation failed during %s', reason, exc_info=True)

    def _clear_persistent_session_safely(self) -> None:
        self._run_ui_fallback(self._clear_persistent_session, '_clear_persistent_session_safely')

    def _apply_online_payload_state(self, payload: dict | None, *, show_status_feedback: bool=True) -> None:
        try:
            data = payload if isinstance(payload, dict) else {}
            if data.get('online'):
                catalog_snapshot = data.get('stored_catalog_snapshot') or data.get('stored_catalog') or data.get('catalog_snapshot')
                if isinstance(catalog_snapshot, dict) and catalog_snapshot:
                    self._apply_remote_catalog_to_local(catalog_snapshot)
                self._set_cloud_state(True, show_status_feedback=bool(show_status_feedback))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('MainWindowUiMixin._apply_online_payload_state fallback failed', exc_info=True)

    def _safe_apply_cached_startup_contract(self) -> None:
        self._run_ui_fallback(self._apply_cached_startup_contract, '_safe_apply_cached_startup_contract')

    def _safe_refresh_remote_notice(self) -> None:
        self._run_ui_fallback(self.login_page.refresh_remote_notice, '_safe_refresh_remote_notice')

    def _safe_save_persistent_session(self) -> None:
        self._run_ui_fallback(self._save_persistent_session, '_safe_save_persistent_session')

    def _safe_show_login(self) -> None:
        self._run_ui_fallback(self.show_login, '_safe_show_login')

    def _safe_accept_event(self, event) -> None:
        try:
            event.accept()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('MainWindowUiMixin._safe_accept_event fallback failed', exc_info=True)

    def _safe_update_user_scope_ui(self) -> None:
        self._run_ui_fallback(self.update_user_scope_ui, '_safe_update_user_scope_ui')

    def _safe_refresh_startup_contract_async(self) -> None:
        self._run_ui_fallback(self.refresh_startup_contract_async, '_safe_refresh_startup_contract_async')

    def _require_session_for_action(self) -> bool:
        if self.app_state.session:
            return True
        self._show_inline_info(_('Info'), _('Sign in required.'))
        return False

    def _select_home_page(self) -> None:
        self._set_active_sidebar_route('home')
        self.show_home()

    def _safe_stop_timer(self, timer) -> None:
        try:
            if timer is not None:
                timer.stop()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('MainWindowUiMixin._safe_stop_timer fallback failed', exc_info=True)

    def _set_top_bar_visible(self, visible: bool) -> None:
        set_widget_visible(getattr(self, 'top_bar', None), visible)

    def _set_top_bar_session_actions_visible(self, visible: bool) -> None:
        """Show logged-in top-bar actions without adding hidden update/help controls."""
        for name in ('command_bar', 'lbl_user_info'):
            set_widget_visible(getattr(self, name, None), visible)

    def _safe_invalidate_cloud_cache(self) -> None:
        self._run_ui_fallback(self.db_manager.invalidate_cloud_cache, '_safe_invalidate_cloud_cache')

    def _configure_db_feedback(self) -> None:
        try:
            self.db_manager.set_ui_feedback_handlers(error=lambda title, message, critical=False: self._show_inline_error(title, message) if critical else self._show_inline_warning(title, message), info=self._show_inline_info, confirm=self._show_question_message)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.exception('Failed to configure database feedback handlers')

    def _start_worker(self, work, *, on_result=None, on_error=None, on_finished=None, suppress_worker_traceback: bool=False, operation_key: str | None=None):
        key = str(operation_key or '').strip()
        registry = getattr(self, '_worker_registry', None)
        if registry is None:
            registry = WorkerRegistry(getattr(self, '_pool', None) or client_thread_pool())
            self._worker_registry = registry
        try:
            runtime_scope_token = int(self._runtime_scope_token_value())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            runtime_scope_token = None

        def _scope_is_current() -> bool:
            if runtime_scope_token is None:
                return True
            try:
                return bool(self._runtime_scope_is_current(runtime_scope_token))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return False
        return registry.start(work, on_result=on_result, on_error=on_error, on_finished=on_finished, operation_key=key, scope_checker=_scope_is_current, log_exceptions=not suppress_worker_traceback)

    def _start_logged_worker(self, work, *, on_result=None, on_finished=None, warning_message: str | None=None, error_handler=None, operation_key: str | None=None):
        if error_handler is None and warning_message:

            def _default_error_handler(message: str, prefix: str=warning_message):
                logger.warning('%s: %s', prefix, message)
            error_handler = _default_error_handler
        return self._start_worker(work, on_result=on_result, on_error=error_handler, on_finished=on_finished, suppress_worker_traceback=bool(error_handler or warning_message), operation_key=operation_key)

    def _exec_modal_dialog(self, dialog, *, reload_tracked: bool=False) -> int:
        result = dialog.exec_()
        if reload_tracked:
            QTimer.singleShot(350, lambda: self.load_tracked_products(show_busy=False) if getattr(getattr(self, 'app_state', None), 'session', None) else None)
        self._sync_notifications_panel_direction()
        return result

    def _open_dialog(self, dialog_factory, *args, reload_tracked: bool=False, **kwargs) -> int:
        dialog = dialog_factory(*args, **kwargs)
        return self._exec_modal_dialog(dialog, reload_tracked=reload_tracked)

    def _cloud_service_available(self, *, warning: bool=False) -> bool:
        if self.app_state.api_client is not None:
            return True
        if warning:
            self._show_inline_warning(_('Error'), _('Cloud service is not configured.'))
        else:
            self._show_inline_info(_('Info'), _('Cloud service is not configured.'))
        return False

    def _show_not_allowed(self, *, title: str='Info', warning: bool=False) -> None:
        if warning:
            self._show_inline_warning(_(title), _('Not allowed'))
        else:
            self._show_inline_info(_(title), _('Not allowed'))

    def _require_cloud_action(self, *, warning: bool=False) -> bool:
        return self._cloud_service_available(warning=warning)

    def _can_change_own_password(self) -> bool:
        try:
            return bool(self._shell_access_state().can_change_own_password)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _prompt_password_value(self, title: str, label: str) -> str | None:
        value, ok = QInputDialog.getText(self, _(title), _(label))
        if not ok:
            return None
        return str(value or '')

    def _admin_dashboard_dialog_class(self):
        from runtime.presentation.views.admin_page import AdminDashboardDialog
        return AdminDashboardDialog
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from runtime.shared.settings.messages import canonical_error_message, user_error_message
from PyQt5.QtWidgets import QDialog
from runtime.shared.settings.config import load_translations
from runtime.application.services.auth import change_own_password
from runtime.application.services.sync import sync_startup_from_settings
from runtime.application.services.translations import is_rtl, normalize_language_code
from runtime.presentation.dialogs.password import ChangePasswordDialog
from runtime.presentation.dialogs.manage_catalog_products import ManageStoredProductsDialog
from runtime.presentation.dialogs.usage_products import ManageUsageProductsDialog
from runtime.presentation.views.settings_page import SettingsDialog

class MainWindowDialogActionsMixin:

    def open_settings(self):
        dialog = None
        try:
            if not self._require_session_for_action():
                return
            self._hide_notifications_panel()
            dialog = SettingsDialog(self.db_manager, self)
            self._settings_dialog = dialog
            dialog.setModal(True)
            dialog.setLayoutDirection(self.layoutDirection())
            result = self._exec_modal_dialog(dialog)
            if result == QDialog.Accepted:
                alert_settings_changed = bool(getattr(dialog, 'alert_settings_changed', True))
                self.rebuild_ui()
                self.apply_role_permissions()
                self.update_user_scope_ui()
                self.refresh_tray_icon()
                if alert_settings_changed:
                    try:
                        self.db_manager.clear_alert_states()
                    except UI_OPERATION_EXCEPTIONS:
                        logger.debug('Failed to clear alert throttle state', exc_info=True)
                    try:
                        if getattr(self, 'notifications_service', None) is not None:
                            self.notifications_service.reset_runtime_state(clear_history=False)
                    except UI_OPERATION_EXCEPTIONS:
                        logger.debug('Failed to reset notification runtime state', exc_info=True)
                    try:
                        self.check_expiry(allow_network=True)
                    except UI_OPERATION_EXCEPTIONS:
                        logger.debug('Failed to run expiry check after settings save', exc_info=True)
        except UI_OPERATION_EXCEPTIONS:
            logger.exception('open_settings failed')
            try:
                self._show_runtime_status_message(canonical_error_message('settings_open_failed'), 6000)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('open_settings status message fallback failed', exc_info=True)
        finally:
            try:
                if dialog is not None:
                    dialog.deleteLater()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('MainWindowDialogActionsMixin.open_settings cleanup failed', exc_info=True)
            self._settings_dialog = None

    def rebuild_ui(self):
        c_lang = normalize_language_code(self.db_manager.get_setting('language', 'en'))
        load_translations(c_lang)
        direction = Qt.RightToLeft if is_rtl(c_lang) else Qt.LeftToRight
        self.setLayoutDirection(direction)
        app = QApplication.instance()
        if app is not None:
            app.setLayoutDirection(direction)
        self.menuBar().clear()
        self.init_menu_bar()
        if self._content_pages_ready():
            self._rebuild_content_pages(preserve_index=True)
        elif self.app_state.session:
            self._ensure_home_page()
        self._safe_update_user_scope_ui()
        self._apply_monitor_schedule(restart=bool(self.app_state.session))
        try:
            sync_startup_from_settings(self.db_manager)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('MainWindowDialogActionsMixin.rebuild_ui startup sync failed', exc_info=True)
        QTimer.singleShot(350, lambda: self.load_tracked_products(show_busy=False) if getattr(getattr(self, 'app_state', None), 'session', None) else None)
        self._sync_notifications_panel_direction()

    def manage_stored(self):
        self._open_dialog(ManageStoredProductsDialog, self.db_manager, self, reload_tracked=True)

    def manage_usage_products(self):
        self._open_dialog(ManageUsageProductsDialog, self.db_manager, self)

    def open_admin_dashboard(self):
        try:
            self._hide_notifications_panel()
            access_state = self._shell_access_state()
            if not access_state.can_open_admin:
                self._show_not_allowed()
                return
            if not access_state.can_open_admin_dashboard:
                self._require_cloud_action(warning=True)
                return
            dialog = getattr(self, '_admin_dashboard_dialog', None)
            if dialog is None:
                dialog = self._admin_dashboard_dialog_class()(self.app_state.api_client, self, embedded=False)
                dialog.setAttribute(Qt.WA_DeleteOnClose, True)
                dialog.destroyed.connect(self._on_admin_dashboard_closed)
                self._admin_dashboard_dialog = dialog
            else:
                dialog.refresh_all_async(busy_text=_('● Refreshing administration from server...'), success_text=_('Administration synchronized'))
            self._set_active_sidebar_route(None)
            dialog.setWindowModality(Qt.NonModal)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except UI_OPERATION_EXCEPTIONS:
            logger.exception('open_admin_dashboard failed')
            self._show_inline_warning(_('Error'), canonical_error_message('admin_open_failed'))

    def _on_admin_dashboard_closed(self, *_args) -> None:
        self._admin_dashboard_dialog = None

    def open_change_password(self):
        dialog = None
        try:
            if not self._require_cloud_action():
                return
            if not self._can_change_own_password():
                self._show_not_allowed(title='Permission', warning=True)
                return
            dialog = ChangePasswordDialog(self)
            result = self._exec_modal_dialog(dialog)
            if result != QDialog.Accepted:
                dialog.deleteLater()
                return
            old_password, new_password = dialog.values()
            dialog.set_busy(True, _('Changing password...'))

            def _work(progress_callback=None):
                return change_own_password(self.app_state.api_client, old_password, new_password)

            def _done(_result):
                try:
                    dialog.set_busy(False, '')
                    dialog.accept()
                except UI_OPERATION_EXCEPTIONS:
                    logger.debug('open_change_password dialog finalize failed', exc_info=True)
                self._show_inline_info(_('Success'), _('Password changed successfully.'))

            def _err(message):
                error_message = str(message or _('Failed to change password.'))
                try:
                    dialog.set_busy(False, error_message)
                except UI_OPERATION_EXCEPTIONS:
                    logger.debug('open_change_password dialog error state failed', exc_info=True)
                self._show_inline_warning(_('Error'), error_message)
            self._start_logged_worker(_work, on_result=_done, warning_message='change password failed', error_handler=_err)
        except UI_OPERATION_EXCEPTIONS as exc:
            logger.exception('open_change_password failed')
            self._show_inline_warning(_('Error'), user_error_message(exc, context='password'))
            try:
                if dialog is not None:
                    dialog.set_busy(False, '')
            except UI_OPERATION_EXCEPTIONS:
                logger.debug('open_change_password cleanup failed', exc_info=True)
from PyQt5.QtCore import QThreadPool
from runtime.shared.objects import call_if_callable
from runtime.presentation.layout.shell import save_normal_window_geometry

class AppLifecycleControllerMixin:

    def closeEvent(self, event):
        save_normal_window_geometry(self)
        if getattr(self, '_closing_completely', False):
            self._safe_accept_event(event)
            return
        spontaneous = False
        try:
            spontaneous = bool(event.spontaneous())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            spontaneous = False
        keep_in_tray = False
        try:
            keep_in_tray = bool(self._should_keep_running_in_tray_on_close())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            keep_in_tray = False
        if keep_in_tray and spontaneous:
            event.ignore()
            if self._minimize_to_tray(show_message=True):
                return
        self.close_app_completely()
        self._safe_accept_event(event)

    def _stop_known_runtime_timers(self) -> None:
        for timer_name in ('check_interval_timer', 'daily_timer', 'token_refresh_timer', 'sync_timer', '_realtime_fallback_timer', '_change_driven_sync_timer', '_usage_sync_request_timer', '_responsive_layout_timer', '_shell_status_clear_timer'):
            self._safe_stop_timer(getattr(self, timer_name, None))

    def _stop_child_timers(self) -> None:
        try:
            for timer in list(self.findChildren(QTimer)):
                self._safe_stop_timer(timer)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Runtime child-timer shutdown failed', exc_info=True)

    def _drain_runtime_thread_pool(self, timeout_ms: int=2500) -> bool:
        try:
            pool = getattr(self, '_pool', None) or QThreadPool.globalInstance()
            if pool is None:
                return True
            pool.clear()
            wait_for_done = getattr(pool, 'waitForDone', None)
            if callable(wait_for_done):
                return bool(wait_for_done(max(0, int(timeout_ms))))
            return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Thread-pool drain failed', exc_info=True)
            return False

    def _shutdown_runtime_resources(self, *, from_about_to_quit: bool=False) -> None:
        if getattr(self, '_shutdown_resources_done', False):
            if from_about_to_quit:
                self._drain_runtime_thread_pool(timeout_ms=500)
            return
        self._shutdown_resources_done = True
        self._closing_completely = True
        try:
            self._cancel_active_workers('application_shutdown')
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Active worker cancellation during shutdown failed', exc_info=True)
        self._stop_known_runtime_timers()
        self._stop_child_timers()
        try:
            if getattr(self, 'sync_manager', None) is not None:
                shutdown = getattr(self.sync_manager, 'shutdown', None)
                if callable(shutdown):
                    shutdown()
                else:
                    self.sync_manager.cancel('cloud_changed')
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Sync manager shutdown failed', exc_info=True)
        drained = self._drain_runtime_thread_pool(timeout_ms=2500)
        if not drained:
            logger.warning('Background work did not finish before the bounded shutdown deadline')
        try:
            update_service = getattr(self, '_startup_update_service', None)
            close_update_service = getattr(update_service, 'close', None)
            if callable(close_update_service):
                call_if_callable(close_update_service)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Startup update-service shutdown failed', exc_info=True)
        try:
            notifications = getattr(self, 'notifications_service', None)
            close_notifications = getattr(notifications, 'close', None)
            if callable(close_notifications):
                call_if_callable(close_notifications)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Notification shutdown failed', exc_info=True)
        try:
            api_client = getattr(getattr(self, 'app_state', None), 'api_client', None)
            close_runtime_client(api_client)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('API client shutdown failed', exc_info=True)
        try:
            self._destroy_tray_icon()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Tray cleanup during shutdown failed', exc_info=True)
        try:
            self.db_manager.close()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Database close during shutdown failed', exc_info=True)
        self._drain_runtime_thread_pool(timeout_ms=250)

    def close_app_completely(self):
        try:
            save_normal_window_geometry(self)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Window geometry save during shutdown failed', exc_info=True)
        if getattr(self, '_closing_completely', False):
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(0, app.quit)
            return
        self._closing_completely = True
        self._shutdown_runtime_resources(from_about_to_quit=False)
        try:
            self.hide()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('Window hide during shutdown failed', exc_info=True)
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)
from PyQt5.QtWidgets import QAction, QMenu
from runtime.presentation.widgets import set_menu_action_icon

class MainWindowMenuBuilderMixin:

    def _safe_connect(self, signal, handler_name: str) -> bool:
        try:
            handler = getattr(self, handler_name, None)
            if callable(handler):
                signal.connect(handler)
                return True
            logger.error('Missing handler: %s', handler_name)
        except UI_OPERATION_EXCEPTIONS as exc:
            logger.error('Failed to connect handler %s: %s', handler_name, exc)
        return False

    def init_menu_bar(self):
        menu_bar = self.menuBar()
        menu_bar.clear()
        try:
            menu_bar.setNativeMenuBar(False)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('MainWindowMenuBuilderMixin.init_menu_bar native menu fallback failed', exc_info=True)
        file_m = menu_bar.addMenu(_('Main'))
        tools_m = menu_bar.addMenu(_('Administration and catalogs'))
        self.act_refresh = None
        self.act_check_updates = QAction(_('Check for Updates'), self)
        set_menu_action_icon(self.act_check_updates, 'refresh.png')
        self._safe_connect(self.act_check_updates.triggered, 'check_for_updates_now')
        file_m.addAction(self.act_check_updates)
        file_m.addSeparator()
        self.act_notifications = QAction(_('Notifications'), self)
        set_menu_action_icon(self.act_notifications, 'bell.png')
        self._safe_connect(self.act_notifications.triggered, 'on_show_notifications')
        file_m.addAction(self.act_notifications)
        file_m.addSeparator()
        self.act_settings = QAction(_('Settings'), self)
        set_menu_action_icon(self.act_settings, 'settings.png')
        self._safe_connect(self.act_settings.triggered, 'open_settings')
        file_m.addAction(self.act_settings)
        self.act_exit = QAction(_('Exit'), self)
        set_menu_action_icon(self.act_exit, 'exit.png')
        self._safe_connect(self.act_exit.triggered, 'close_app_completely')
        file_m.addAction(self.act_exit)
        self.act_manage = QAction(_('Manage food item catalog'), self)
        set_menu_action_icon(self.act_manage, 'products.png')
        self._safe_connect(self.act_manage.triggered, 'manage_stored')
        tools_m.addAction(self.act_manage)
        self.act_manage_usage = QAction(_('Manage consumption item catalog'), self)
        set_menu_action_icon(self.act_manage_usage, 'usage.png')
        self._safe_connect(self.act_manage_usage.triggered, 'manage_usage_products')
        tools_m.addAction(self.act_manage_usage)
        self.act_change_pw = QAction(_('Change Account Password'), self)
        set_menu_action_icon(self.act_change_pw, 'settings.png')
        self._safe_connect(self.act_change_pw.triggered, 'open_change_password')
        tools_m.addAction(self.act_change_pw)
        self.act_logout = QAction(_('Logout'), self)
        set_menu_action_icon(self.act_logout, 'exit.png')
        self._safe_connect(self.act_logout.triggered, 'logout')
        file_m.addAction(self.act_logout)
        self.act_org_mgmt = QAction(_('Operations Administration'), self)
        set_menu_action_icon(self.act_org_mgmt, 'admin.png')
        self._safe_connect(self.act_org_mgmt.triggered, 'open_admin_dashboard')
        tools_m.addAction(self.act_org_mgmt)
        tools_m.addSeparator()
        self.act_about = QAction(_('About'), self)
        set_menu_action_icon(self.act_about, 'about.png')
        self._safe_connect(self.act_about.triggered, 'show_about')
        tools_m.addSeparator()
        tools_m.addAction(self.act_about)
        self._bind_top_bar_menus(file_m, tools_m)

    def _bind_top_bar_menus(self, file_menu, tools_menu) -> None:
        try:
            primary = getattr(self, 'btn_menu_file', None)
            tools_button = getattr(self, 'btn_menu_tools', None)
            if primary is not None and tools_button is None:
                combined = QMenu(self)
                for menu in (file_menu, tools_menu):
                    if menu is None:
                        continue
                    if combined.actions():
                        combined.addSeparator()
                    for action in menu.actions():
                        combined.addAction(action)
                self._combined_top_menu = combined
                primary.setMenu(combined)
            else:
                for button, menu in ((primary, file_menu), (tools_button, tools_menu)):
                    if button is not None and menu is not None:
                        button.setMenu(menu)
            self.menuBar().setVisible(False)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug('MainWindowMenuBuilderMixin._bind_top_bar_menus failed', exc_info=True)
from PyQt5.QtWidgets import QPushButton, QWidget
from runtime.application.services.sync import ShellUserScopePresenter
from runtime.presentation.layout.shell import apply_responsive_shell_metrics

class MainWindowRouteNavigationMixin:

    def handle_sidebar_click(self, btn: QPushButton, func):
        if getattr(self, '_ui_transition_depth', 0) > 0 or not btn.isEnabled():
            return
        is_page_button = bool(btn.property('pageButton'))
        for b_ in getattr(self, 'sidebar_page_buttons', []) or []:
            b_.setChecked(False)
        if is_page_button:
            btn.setChecked(True)
        else:
            btn.setChecked(False)
        func()

    def _set_active_sidebar_route(self, route_name: str | None) -> None:
        wanted = str(route_name or '').strip().lower()
        for button in getattr(self, 'sidebar_page_buttons', []) or []:
            try:
                current = str(button.property('routeName') or '').strip().lower()
                button.setChecked(bool(wanted and current == wanted))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug('MainWindowRouteNavigationMixin._set_active_sidebar_route failed', exc_info=True)

    def _show_page(self, page: QWidget, *, refresh_callback=None) -> None:
        self._set_top_bar_visible(True)
        if callable(refresh_callback):
            try:
                refresh_callback()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug('MainWindowUiMixin._show_page fallback failed', exc_info=True)
        self.content_stack.setCurrentWidget(page)
        apply_responsive_shell_metrics(self)

    def show_home(self):
        self._ensure_home_page()
        if getattr(self, 'home_page', None) is None:
            return
        self._set_active_sidebar_route('home')
        self._show_page(self.home_page, refresh_callback=lambda: self.home_page.refresh_dashboard(profile=self.app_state.current_user, permission_context=self.db_manager.perm_ctx()))

    def _on_home_navigation_requested(self, target: str):
        tgt = str(target or '').strip().lower()
        if tgt == 'tracking':
            self.show_track()
            return
        if tgt == 'usage':
            self.show_usage()
            return
        if tgt in {'admin', 'org'}:
            self.open_admin_dashboard()
            return

    def _show_authorized_route(self, route: str, page, allowed: bool) -> None:
        if not allowed:
            self._show_not_allowed(title='Permission', warning=False)
            return
        if page is None:
            return
        self._set_active_sidebar_route(route)
        self._show_page(page)

    def show_track(self):
        self._ensure_track_page()
        self._show_authorized_route('tracking', getattr(self, 'track_page', None), self._shell_access_state().can_open_tracking)

    def show_usage(self):
        self._ensure_usage_page()
        self._show_authorized_route('usage', getattr(self, 'usage_page', None), self._shell_access_state().can_open_usage)

    def show_about(self):
        self._ensure_about_page()
        if getattr(self, 'about_page', None) is None:
            return
        self._set_active_sidebar_route('about')
        self._show_page(self.about_page)

    def refresh_current_view(self):
        try:
            current = self.content_stack.currentWidget()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return
        try:
            if current is getattr(self, 'home_page', None):
                self.show_home()
                return
            if current is getattr(self, 'track_page', None):
                self.track_page.load_tracked_products(show_busy=False)
                return
            if current is getattr(self, 'usage_page', None):
                if hasattr(self.usage_page, 'compute'):
                    self.usage_page.compute()
                return
            if current is getattr(self, 'about_page', None):
                self.show_about()
                return
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('MainWindowRouteNavigationMixin.refresh_current_view failed', exc_info=True)

    def on_branch_context_changed(self, branch: str):
        try:
            self.update_user_scope_ui(view_branch=branch)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('MainWindowUiMixin.on_branch_context_changed fallback failed', exc_info=True)

    def update_user_scope_ui(self, view_branch: str | None=None):
        lang = normalize_language_code(str(self.db_manager.get_setting('language', 'ar') or 'ar'))
        prof = self.app_state.current_user
        ctx = self.db_manager.perm_ctx()
        scope_state = ShellUserScopePresenter.build(permission_context=ctx, username=str(getattr(prof, 'username', '') or '').strip(), allowed_branches=self.db_manager.allowed_branches(), language=lang, view_branch=str(view_branch if view_branch is not None else self.db_manager.get_active_branch() or ctx.active_branch or '').strip())
        try:
            if hasattr(self, 'home_page') and self.home_page is not None:
                self.home_page.refresh_dashboard(profile=prof, permission_context=ctx, view_branch=scope_state.resolved_view_branch)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('MainWindowUiMixin.update_user_scope_ui fallback failed', exc_info=True)
        try:
            if hasattr(self, 'lbl_user_info') and self.lbl_user_info is not None:
                full_text = str(scope_state.top_info or '').strip()
                branch_text = str(scope_state.branch_text or '').strip()
                user_text = str(getattr(prof, 'username', '') or '').strip()
                compact_text = ' · '.join((part for part in (user_text, branch_text) if part)).strip()
                if not compact_text:
                    compact_text = full_text.replace('System Administrator', 'Admin')
                if len(compact_text) > 26:
                    compact_text = compact_text[:25].rstrip() + '…'
                self.lbl_user_info.setToolTip(full_text)
                self.lbl_user_info.setText(compact_text)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug('MainWindowUiMixin.update_user_scope_ui fallback failed', exc_info=True)
__all__ = ['AppLifecycleControllerMixin', 'MainWindowActionSupportMixin', 'MainWindowDialogActionsMixin', 'MainWindowMenuBuilderMixin', 'MainWindowRouteNavigationMixin']
