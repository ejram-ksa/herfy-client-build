from __future__ import annotations
import logging
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from runtime.shared.settings.config import _
from runtime.application.services.sync import ShellAccessService

logger = logging.getLogger(__name__)


class MainWindowAccessNavigationMixin:

    def _shell_access_state(self):
        return ShellAccessService.build(
            permission_context=self.db_manager.perm_ctx(),
            has_session=bool(self.app_state.session),
            allowed_branches=self.db_manager.allowed_branches(),
            api_client_available=bool(self.app_state.api_client),
        )

    def _set_sidebar_locked(
        self, locked: bool, *, allow_exit: bool = True, reset_checks: bool = False
    ):
        buttons = list(getattr(self, "sidebar_buttons", []) or [])
        if not buttons:
            return
        for btn in buttons:
            try:
                is_exit = bool(btn.property("isExitButton"))
                btn.setEnabled(not locked or (allow_exit and is_exit))
                if reset_checks and (
                    locked or bool(btn.property("pageButton")) or (not is_exit)
                ):
                    btn.setChecked(False)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug(
                    "MainWindowUiMixin._set_sidebar_locked fallback failed",
                    exc_info=True,
                )

    def _set_menu_logged_out_state(self):
        for act_name in (
            "act_manage",
            "act_manage_usage",
            "act_org_mgmt",
            "act_settings",
            "act_logout",
            "act_change_pw",
        ):
            act = getattr(self, act_name, None)
            if act is not None:
                try:
                    act.setEnabled(False)
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    logger.debug(
                        "MainWindowUiMixin._set_menu_logged_out_state fallback failed",
                        exc_info=True,
                    )
        if getattr(self, "act_exit", None) is not None:
            try:
                self.act_exit.setEnabled(True)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug(
                    "MainWindowUiMixin._set_menu_logged_out_state fallback failed",
                    exc_info=True,
                )

    def _refresh_navigation_permissions(self):
        page_buttons = list(getattr(self, "sidebar_page_buttons", []) or [])
        access_state = self._shell_access_state()
        route_permissions = {
            "home": access_state.can_open_home,
            "tracking": access_state.can_open_tracking,
            "usage": access_state.can_open_usage,
            "admin": access_state.can_open_admin,
            "about": access_state.can_open_about,
        }
        try:
            for button in page_buttons:
                route_name = str(button.property("routeName") or "").strip().lower()
                if route_name in route_permissions:
                    button.setEnabled(bool(route_permissions[route_name]))
            if getattr(self, "btn_settings_sidebar", None) is not None:
                self.btn_settings_sidebar.setEnabled(access_state.can_open_settings)
            if getattr(self, "btn_org_sidebar", None) is not None:
                self.btn_org_sidebar.setEnabled(access_state.can_open_admin)
            if getattr(self, "btn_exit_sidebar", None) is not None:
                self.btn_exit_sidebar.setEnabled(access_state.can_exit)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._refresh_navigation_permissions fallback failed",
                exc_info=True,
            )
        try:
            self.btn_notifications.setEnabled(access_state.can_open_notifications)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._refresh_navigation_permissions fallback failed",
                exc_info=True,
            )

    def _apply_logged_out_shell(self, *, reset_sidebar: bool = False):
        try:
            self._set_sidebar_locked(True, allow_exit=True, reset_checks=reset_sidebar)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._apply_logged_out_shell fallback failed",
                exc_info=True,
            )
        try:
            self._set_menu_logged_out_state()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._apply_logged_out_shell fallback failed",
                exc_info=True,
            )
        try:
            self.lbl_user_info.setText("")
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._apply_logged_out_shell fallback failed",
                exc_info=True,
            )
        self._set_notifications_enabled(False)
        try:
            self.lbl_notif_count.hide()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._apply_logged_out_shell fallback failed",
                exc_info=True,
            )
        self._safe_show_login()

    def _apply_logged_in_shell(self):
        try:
            self._set_top_bar_session_actions_visible(True)
            self._set_sidebar_locked(False, allow_exit=True, reset_checks=False)
            self._refresh_navigation_permissions()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._apply_logged_in_shell fallback failed",
                exc_info=True,
            )

    def _begin_ui_transition(
        self, message: str = "", *, lock_navigation: bool = True, keep_exit: bool = True
    ):
        self._ui_transition_depth = (
            max(0, int(getattr(self, "_ui_transition_depth", 0))) + 1
        )
        self._ui_transition_message = str(message or "").strip()
        try:
            if lock_navigation:
                self._set_sidebar_locked(True, allow_exit=keep_exit, reset_checks=False)
                for act_name in (
                    "act_manage",
                    "act_manage_usage",
                    "act_org_mgmt",
                    "act_settings",
                    "act_logout",
                    "act_change_pw",
                ):
                    act = getattr(self, act_name, None)
                    if act is not None:
                        act.setEnabled(False)
                if getattr(self, "act_exit", None) is not None:
                    self.act_exit.setEnabled(bool(keep_exit))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._begin_ui_transition fallback failed", exc_info=True
            )
        self._set_notifications_enabled(False)
        try:
            self._show_shell_status_message(self._ui_transition_message or _("Working"))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._begin_ui_transition fallback failed", exc_info=True
            )
        try:
            if getattr(self, "transition_progress", None) is not None:
                self.transition_progress.show()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._begin_ui_transition fallback failed", exc_info=True
            )
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._begin_ui_transition fallback failed", exc_info=True
            )

    def _end_ui_transition(self, *, restore_shell: bool = False):
        depth = max(0, int(getattr(self, "_ui_transition_depth", 0)) - 1)
        self._ui_transition_depth = depth
        if depth > 0:
            return
        self._ui_transition_message = ""
        try:
            QApplication.restoreOverrideCursor()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._end_ui_transition fallback failed", exc_info=True
            )
        try:
            self._clear_shell_status_message()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._end_ui_transition fallback failed", exc_info=True
            )
        try:
            if getattr(self, "transition_progress", None) is not None:
                self.transition_progress.hide()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._end_ui_transition fallback failed", exc_info=True
            )
        if restore_shell:
            try:
                if self.app_state.session:
                    self._set_top_bar_visible(True)
                    self._apply_logged_in_shell()
                    self.apply_role_permissions()
                else:
                    self._apply_logged_out_shell(reset_sidebar=False)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug(
                    "MainWindowUiMixin._end_ui_transition fallback failed",
                    exc_info=True,
                )

    def apply_role_permissions(self):
        self._refresh_navigation_permissions()
        access_state = self._shell_access_state()
        if getattr(self, "act_settings", None):
            self.act_settings.setEnabled(access_state.can_open_settings)
        if getattr(self, "act_manage", None):
            self.act_manage.setEnabled(access_state.can_manage_stored_products)
        if getattr(self, "act_manage_usage", None):
            self.act_manage_usage.setEnabled(access_state.can_manage_usage_products)
        if getattr(self, "act_change_pw", None):
            self.act_change_pw.setEnabled(access_state.can_change_own_password)
        if getattr(self, "act_org_mgmt", None):
            self.act_org_mgmt.setEnabled(access_state.can_open_admin)
        if getattr(self, "act_logout", None):
            self.act_logout.setEnabled(access_state.can_logout)
        if getattr(self, "act_exit", None):
            self.act_exit.setEnabled(access_state.can_exit)
