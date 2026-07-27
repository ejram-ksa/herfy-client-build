from __future__ import annotations

import logging
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.shared.feedback import normalize_feedback_severity
from runtime.shared.settings.messages import canonical_error_message, user_error_message
from runtime.application.services.auth import LoginRemoteNoticeService
from runtime.application.services.auth import load_user_profile_from_session
from runtime.application.services.auth import AuthError, sign_in_with_identifier_password
from runtime.presentation.widgets import apply_notice_style
from runtime.presentation.widgets import widget_alive
from runtime.presentation.widgets import refresh_widget_style

logger = logging.getLogger(__name__)


class LoginControllerMixin:

    def _close_login_workers(self, *_args) -> None:
        registry = getattr(self, "_worker_registry", None)
        if registry is not None:
            try:
                close = getattr(registry, "close", None)
                if callable(close):
                    close()
                else:
                    registry.cancel_all()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug("Login worker registry close failed", exc_info=True)

    def is_runtime_ready(self) -> bool:
        widgets = (
            getattr(self, "btn_login", None),
            getattr(self, "ed_user", None),
            getattr(self, "ed_pass", None),
            getattr(self, "chk_remember", None),
            getattr(self, "progress", None),
            getattr(self, "lbl_status", None),
        )
        return all((widget_alive(widget) for widget in widgets))

    def set_remote_notice(self, text: str = "", *, severity: str = "info"):
        if not widget_alive(getattr(self, "lbl_remote_notice", None)):
            return
        message = str(text or "").strip()
        if not message:
            self.lbl_remote_notice.hide()
            self.lbl_remote_notice.clear()
            self.lbl_remote_notice.setProperty("notice", False)
            self.lbl_remote_notice.setProperty("noticeSeverity", "neutral")
            refresh_widget_style(self.lbl_remote_notice)
            return
        notice_severity = (
            "neutral"
            if str(severity or "").strip().lower() == "neutral"
            else normalize_feedback_severity(severity)
        )
        self.lbl_remote_notice.setText(message)
        apply_notice_style(
            self.lbl_remote_notice, severity=notice_severity, radius=8, padding=8
        )
        self.lbl_remote_notice.show()

    def refresh_remote_notice(self):
        if not self.is_runtime_ready():
            return
        db = getattr(self.main_window, "db_manager", None)
        if db is None:
            self.set_remote_notice("")
            return
        try:
            decision = LoginRemoteNoticeService.evaluate(
                {
                    "remote_maintenance_enabled": db.get_setting(
                        "remote_maintenance_enabled", "False"
                    ),
                    "remote_maintenance_message": db.get_setting(
                        "remote_maintenance_message", ""
                    ),
                    "remote_login_message": db.get_setting("remote_login_message", ""),
                    "remote_startup_banner": db.get_setting(
                        "remote_startup_banner", ""
                    ),
                    "remote_startup_banner_severity": db.get_setting(
                        "remote_startup_banner_severity", "info"
                    ),
                }
            )
        except UI_OPERATION_EXCEPTIONS:
            decision = LoginRemoteNoticeService.evaluate(None)
        self.set_remote_notice(decision.message, severity=decision.severity)

    def _schedule_login_draft_save(self, *_args):
        if not self.is_runtime_ready():
            return
        try:
            self._draft_save_timer.start()
        except UI_OPERATION_EXCEPTIONS:
            self._flush_login_draft()

    def _flush_login_draft(self):
        if not self.is_runtime_ready():
            return
        try:
            self._session_store.save_login_form_state(
                username=self.ed_user.text().strip(),
                remember=bool(self.chk_remember.isChecked()),
            )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("LoginPage._flush_login_draft fallback failed", exc_info=True)

    def restore_cached_input(self, *, clear_password: bool = False):
        if not self.is_runtime_ready():
            return
        try:
            state = self._session_store.load_login_form_state()
        except UI_OPERATION_EXCEPTIONS:
            state = None
        username = str(getattr(state, "username", "") or "").strip()
        if username and (not self.ed_user.text().strip()):
            self.ed_user.setText(username)
        try:
            self.chk_remember.setChecked(bool(getattr(state, "remember", False)))
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "LoginPage.restore_cached_input fallback failed", exc_info=True
            )
        if clear_password:
            self.ed_pass.clear()
        if self.ed_user.text().strip():
            self.ed_pass.setFocus()
        else:
            self.ed_user.setFocus()

    def prepare_for_logout(self):
        if not self.is_runtime_ready():
            return
        self._login_token = int(getattr(self, "_login_token", 0) or 0) + 1
        registry = getattr(self, "_worker_registry", None)
        if registry is not None:
            registry.cancel_all()
        self._set_busy(False, "")
        self.lbl_status.clear()
        self.restore_cached_input(clear_password=True)
        self.refresh_remote_notice()

    def set_transition_busy(self, busy: bool, text: str = ""):
        self._set_busy(busy, text)

    def _set_busy(self, busy: bool, text: str = ""):
        if not self.is_runtime_ready():
            return
        self.btn_login.setEnabled(not busy)
        self.ed_user.setEnabled(not busy)
        self.ed_pass.setEnabled(not busy)
        self.chk_remember.setEnabled(not busy)
        self.progress.setVisible(bool(busy))
        self.lbl_status.setText(text)

    def do_login(self):
        if not self.is_runtime_ready():
            return
        if self._login_worker is not None:
            return
        u = self.ed_user.text().strip()
        p = self.ed_pass.text()
        if not u or not p:
            self.lbl_status.setText(canonical_error_message("missing_credentials"))
            return
        self._flush_login_draft()
        try:
            marker = getattr(self.main_window, "_mark_runtime_scope_changed", None)
            if callable(marker):
                marker()
            setattr(self.main_window, "_restore_session_running", False)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "LoginPage.do_login restore cancellation failed", exc_info=True
            )
        self._set_busy(True, _("Signing in..."))

        def _work(progress_callback=None):
            sess = sign_in_with_identifier_password(u, p)
            prof = load_user_profile_from_session(sess, sess.uid)
            if not prof:
                raise AuthError(canonical_error_message("profile_missing"))
            return (sess, prof)

        self._login_token = int(getattr(self, "_login_token", 0) or 0) + 1
        login_token = self._login_token

        def _is_current_login() -> bool:
            return login_token == int(getattr(self, "_login_token", -1) or -1)

        worker = self._worker_registry.start(
            _work,
            on_result=self._on_login_result,
            on_error=self._on_login_error,
            on_finished=self._on_login_finished,
            operation_key="login:submit",
            scope_checker=_is_current_login,
            log_exceptions=False,
        )
        self._login_worker = worker
        if worker is None:
            self._on_login_finished()

    def _on_login_finished(self):
        self._login_worker = None
        try:
            if hasattr(self.main_window, "_end_ui_transition"):
                self.main_window._end_ui_transition()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("LoginPage._on_login_finished fallback failed", exc_info=True)

    def _on_login_result(self, result):
        try:
            sess, prof = result
        except UI_OPERATION_EXCEPTIONS:
            self._on_login_error(canonical_error_message("invalid_response"))
            return
        self._flush_login_draft()
        self.main_window.on_login_success(
            sess, prof, remember=bool(self.chk_remember.isChecked())
        )

    def _on_login_error(self, error):
        if isinstance(error, tuple) and len(error) >= 2:
            message = str(error[1])
        else:
            message = str(error)
        self._set_busy(False, "")
        self.lbl_status.setText(user_error_message(message, context="login"))
        self.ed_pass.selectAll()
        self.ed_pass.setFocus()
