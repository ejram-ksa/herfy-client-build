from __future__ import annotations
from runtime.application.services.tracking_runtime import tracking_baseline

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

import logging
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.presentation.views.login_page import LoginPage
from runtime.presentation.widgets import widget_alive
from runtime.services.lifecycle import close_runtime_client

logger = logging.getLogger(__name__)


class SessionAuthControllerMixin:

    def _ensure_login_page(self):
        page = getattr(self, "login_page", None)
        try:
            if page is not None and widget_alive(page):
                is_ready = getattr(page, "is_runtime_ready", None)
                if callable(is_ready) and (not bool(is_ready())):
                    page = None
                else:
                    if (
                        getattr(self, "content_stack", None) is not None
                        and self.content_stack.indexOf(page) < 0
                    ):
                        self.content_stack.insertWidget(0, page)
                    return page
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "MainWindowSessionMixin._ensure_login_page fallback failed",
                exc_info=True,
            )
        try:
            page = LoginPage(self)
            self.login_page = page
            if getattr(self, "content_stack", None) is not None:
                self.content_stack.insertWidget(0, page)
            return page
        except UI_OPERATION_EXCEPTIONS:
            logger.exception("Failed to recreate login page")
            return None

    def logout(self):
        self._mark_runtime_scope_changed()
        self._begin_ui_transition(
            _("Signing out..."), lock_navigation=True, keep_exit=True
        )
        try:
            try:
                close_runtime_client(getattr(self.app_state, "api_client", None))
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin.logout API client cleanup failed",
                    exc_info=True,
                )
            self._clear_persistent_session_safely()
            try:
                if getattr(self, "db_manager", None) is not None and hasattr(
                    self.db_manager, "clear_session_scoped_local_data"
                ):
                    self.db_manager.clear_session_scoped_local_data(clear_catalog=True)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug("Manual logout scoped data cleanup failed", exc_info=True)
            for tname in (
                "check_interval_timer",
                "daily_timer",
                "token_refresh_timer",
                "sync_timer",
                "_realtime_fallback_timer",
            ):
                t = getattr(self, tname, None)
                if t:
                    try:
                        t.stop()
                    except UI_OPERATION_EXCEPTIONS:
                        logger.debug(
                            "MainWindowSessionMixin.logout fallback failed",
                            exc_info=True,
                        )
            try:
                tracking_baseline.reset()
                if getattr(self, "notifications_service", None) is not None:
                    self.notifications_service.reset_runtime_state(clear_history=True)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin.logout fallback failed", exc_info=True
                )
            try:
                self._hide_notifications_panel()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin.logout fallback failed", exc_info=True
                )
            try:
                self._set_cloud_state(False, show_status_feedback=False)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin.logout fallback failed", exc_info=True
                )
            self._post_contract_update_check_pending = False
            self._login_hydrate_pending = False
            self._update_check_running = False
            try:
                if getattr(self, "app_state", None) is not None:
                    self.app_state.reset_identity()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin.logout fallback failed", exc_info=True
                )
            try:
                self.db_manager.set_cloud_context(None, None)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin.logout fallback failed", exc_info=True
                )
            try:
                track_page = getattr(self, "track_page", None)
                if track_page is not None:
                    track_page.reset_after_logout()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin.logout fallback failed", exc_info=True
                )
            try:
                self.update_user_scope_ui(view_branch="")
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin.logout fallback failed", exc_info=True
                )
            try:
                page = self._ensure_login_page()
                if page is not None:
                    page.prepare_for_logout()
                    page.refresh_remote_notice()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin.logout fallback failed", exc_info=True
                )
            self._apply_logged_out_shell(reset_sidebar=True)
            self._safe_apply_cached_startup_contract()
        finally:
            self._end_ui_transition(restore_shell=False)
            self._safe_show_login()

    def show_login(self):
        page = self._ensure_login_page()
        try:
            self.top_bar.setVisible(True)
            self._set_top_bar_session_actions_visible(False)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "MainWindowSessionMixin.show_login fallback failed", exc_info=True
            )
        try:
            if (
                page is not None
                and getattr(self, "content_stack", None) is not None
                and widget_alive(self.content_stack)
            ):
                self.content_stack.setCurrentWidget(page)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "MainWindowSessionMixin.show_login fallback failed", exc_info=True
            )
        try:
            if page is not None:
                page.prepare_for_logout()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "MainWindowSessionMixin.show_login fallback failed", exc_info=True
            )
        try:
            if page is not None:
                page.restore_cached_input(clear_password=True)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "MainWindowSessionMixin.show_login fallback failed", exc_info=True
            )
        self._bring_to_front(show_if_hidden=True)


import time
from PyQt5.QtCore import QSettings, QTimer
from runtime.shared.settings.config import settings_ini_path
from runtime.application.services.auth import AuthError, load_user_profile_from_session
from runtime.application.services.auth import refresh_session
from runtime.application.services.auth import build_restore_candidate
from runtime.services.session import classify_restore_failure
from runtime.application.services.updates import RuntimeUpdateFlowService
from runtime.application.services.updates import StartupContractService
from runtime.shared.settings.version import __version__ as APP_VERSION



class SessionRestoreControllerMixin:

    def _settings_store(self):
        return QSettings(settings_ini_path(), QSettings.IniFormat)

    def _save_persistent_session(self):
        try:
            remember_session = bool(getattr(self, "_remember_session", False))
            ctx = self.db_manager.perm_ctx()
            self.session_store.save(
                session=self.app_state.session,
                profile=self.app_state.current_user,
                remember=remember_session,
                permission_context=ctx,
                saved_at=int(time.time()),
            )
            try:
                s = self._settings_store()
                if remember_session:
                    s.setValue("session/remember", True)
                else:
                    s.remove("session/remember")
                s.sync()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin._save_persistent_session fallback failed",
                    exc_info=True,
                )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "MainWindowSessionMixin._save_persistent_session fallback failed",
                exc_info=True,
            )

    def _clear_persistent_session(self):
        try:
            self.session_store.clear()
        except (AttributeError, RuntimeError, TypeError, ValueError, OSError):
            logger.debug(
                "MainWindowSessionMixin._clear_persistent_session fallback failed",
                exc_info=True,
            )
        try:
            s = self._settings_store()
            for k in ("session/remember",):
                s.remove(k)
            s.sync()
        except (AttributeError, RuntimeError, TypeError, ValueError, OSError):
            logger.debug(
                "MainWindowSessionMixin._clear_persistent_session fallback failed",
                exc_info=True,
            )

    def try_restore_session_async(self):
        """Restore only after the server refreshes and authorizes the user."""
        if getattr(self, "_restore_session_running", False):
            return
        try:
            snapshot = self.session_store.load_snapshot()
        except (AttributeError, RuntimeError, TypeError, ValueError, OSError):
            snapshot = None
        candidate = build_restore_candidate(snapshot)
        if candidate is None:
            return
        self._restore_session_running = True
        try:
            self.login_page.set_transition_busy(True, _("Restoring session..."))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Session restore busy-state failed", exc_info=True)
        self._begin_ui_transition(
            _("Restoring session..."), lock_navigation=True, keep_exit=True
        )

        def _work(progress_callback=None):
            del progress_callback
            try:
                session = refresh_session(candidate.refresh_token, candidate.username)
                profile = load_user_profile_from_session(session, candidate.username)
                restored_user_id = str(
                    getattr(profile, "uid", "")
                    or getattr(session, "uid", "")
                    or ""
                ).strip()
                expected_user_id = str(candidate.user_id or "").strip()
                if (
                    expected_user_id
                    and restored_user_id
                    and expected_user_id.casefold() != restored_user_id.casefold()
                ):
                    return {
                        "clear": True,
                        "retryable": False,
                        "reason": "session_identity_mismatch",
                    }
                # Do not create a second temporary API client or block restore on
                # a full sync. ``on_login_success`` owns the real client and
                # schedules hydration through the de-duplicated worker registry.
                return {"session": session, "profile": profile}
            except Exception as exc:
                decision = classify_restore_failure(exc)
                logger.warning(
                    "Server-authoritative session restore failed reason=%s retryable=%s type=%s",
                    decision.reason,
                    decision.retryable,
                    type(exc).__name__,
                )
                return {
                    "clear": decision.clear_persistent_session,
                    "retryable": decision.retryable,
                    "reason": decision.reason,
                }

        runtime_scope_token = self._runtime_scope_token_value()

        def _guarded_restore_result(payload):
            if self._runtime_scope_is_current(runtime_scope_token):
                self._on_restore_session_result(payload)

        def _guarded_restore_done():
            self._restore_session_running = False
            if not self._runtime_scope_is_current(runtime_scope_token):
                return
            try:
                self.login_page.set_transition_busy(False, "")
                self.login_page.restore_cached_input(clear_password=True)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("Session restore finish failed", exc_info=True)
            self._end_ui_transition(restore_shell=True)

        self._start_logged_worker(
            _work,
            on_result=_guarded_restore_result,
            on_finished=_guarded_restore_done,
            warning_message="restore session failed",
            operation_key="restore_session",
        )

    def _on_restore_session_result(self, payload):
        payload = payload or {}
        try:
            if payload.get("clear"):
                self._clear_persistent_session()
                return
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowSessionMixin._on_restore_session_result fallback failed",
                exc_info=True,
            )
        session = payload.get("session")
        profile = payload.get("profile")
        if session and profile:
            self.on_login_success(session, profile, remember=True, _restored=True)

    def _apply_cached_startup_contract(self):
        service = getattr(self, "server_runtime_service", None)
        if service is None:
            logger.debug(
                "MainWindowSessionMixin._apply_cached_startup_contract skipped: server_runtime_service missing"
            )
            self._safe_refresh_remote_notice()
            return
        snapshot = None
        try:
            snapshot = service.load_cached()
        except (AttributeError, RuntimeError, TypeError, ValueError, OSError):
            snapshot = None
        try:
            service.apply_startup_config(self.db_manager, snapshot)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowSessionMixin._apply_cached_startup_contract fallback failed",
                exc_info=True,
            )
        self._safe_refresh_remote_notice()

    def refresh_startup_contract_async(self):
        if getattr(self, "_startup_contract_running", False):
            return
        self._startup_contract_running = True
        self._startup_contract_result_applied = False

        def _work(progress_callback=None):
            return self.server_runtime_service.fetch_and_apply(
                self.db_manager, APP_VERSION
            )

        def _result(payload):
            try:
                self._handle_startup_contract(payload or {})
                self._startup_contract_result_applied = True
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowSessionMixin.refresh_startup_contract_async._result fallback failed",
                    exc_info=True,
                )

        runtime_scope_token = self._runtime_scope_token_value()

        def _guarded_contract_result(payload):
            if not self._runtime_scope_is_current(runtime_scope_token):
                return
            _result(payload)

        def _guarded_contract_done():
            self._startup_contract_running = False
            if not self._runtime_scope_is_current(runtime_scope_token):
                return
            if not getattr(self, "_startup_contract_result_applied", False):
                self._apply_runtime_update_flow(
                    RuntimeUpdateFlowService.after_startup_contract(
                        session_active=self.app_state.session is not None,
                        pending_optional_login_check=bool(
                            getattr(self, "_post_contract_update_check_pending", False)
                        ),
                        force_logout=False,
                        mandatory_update_required=False,
                    )
                )
            self._safe_refresh_remote_notice()

        self._start_logged_worker(
            _work,
            on_result=_guarded_contract_result,
            on_finished=_guarded_contract_done,
            error_handler=lambda _msg: None,
            operation_key="startup_contract_refresh",
        )

    def _apply_runtime_update_flow(
        self, flow_decision, *, optional_delay_ms: int = 1500
    ) -> None:
        del optional_delay_ms
        if bool(getattr(flow_decision, "clear_pending_optional_check", False)):
            self._post_contract_update_check_pending = False
        if bool(getattr(flow_decision, "schedule_mandatory_check", False)):
            try:
                QTimer.singleShot(0, self._maybe_check_updates)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug(
                    "MainWindowSessionMixin._apply_runtime_update_flow fallback failed",
                    exc_info=True,
                )
            return
        if bool(getattr(flow_decision, "schedule_optional_check", False)):
            try:
                QTimer.singleShot(0, self._maybe_check_updates)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug(
                    "MainWindowSessionMixin._apply_runtime_update_flow fallback failed",
                    exc_info=True,
                )

    def _handle_startup_contract(self, payload: dict):
        payload = payload if isinstance(payload, dict) else {}
        startup = (
            payload.get("startup_config")
            if isinstance(payload.get("startup_config"), dict)
            else {}
        )
        upgrade = (
            payload.get("upgrade_plan")
            if isinstance(payload.get("upgrade_plan"), dict)
            else {}
        )
        ctx = self.db_manager.perm_ctx()
        decision = StartupContractService.evaluate(
            startup_config=startup,
            upgrade_plan=upgrade,
            session_active=self.app_state.session is not None,
            role=str(getattr(ctx, "role", "") or "").strip(),
            current_version=APP_VERSION,
        )
        update_flow = RuntimeUpdateFlowService.after_startup_contract(
            session_active=self.app_state.session is not None,
            pending_optional_login_check=bool(
                getattr(self, "_post_contract_update_check_pending", False)
            ),
            force_logout=decision.force_logout,
            mandatory_update_required=decision.schedule_update_check,
        )
        if decision.clear_cached_session:
            self._clear_persistent_session_safely()
        self._safe_refresh_remote_notice()
        if decision.show_banner_message:
            try:
                self._show_shell_status_message(decision.show_banner_message, 10000)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug(
                    "MainWindowSessionMixin._handle_startup_contract fallback failed",
                    exc_info=True,
                )
        self._apply_runtime_update_flow(update_flow)
        if decision.force_logout:
            try:
                self.logout()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug(
                    "MainWindowSessionMixin._handle_startup_contract fallback failed",
                    exc_info=True,
                )
            return
