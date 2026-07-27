from __future__ import annotations
import logging
from runtime.shared.settings.config import _
from runtime.shared.booleans import parse_bool
from runtime.application.services.notifications import NotificationsStateService
from runtime.presentation.dialogs.notifications_dialog import NotificationsDialog
from runtime.presentation.widgets import set_widget_enabled
from PyQt5.QtWidgets import QSystemTrayIcon
from runtime.shared.settings.config import APP_DISPLAY_NAME
from runtime.shared.signals import safe_disconnect
from runtime.presentation.widgets import tray_icon_or_fallback
from runtime.presentation.qt.system_tray_adapter import SystemTrayAdapter

logger = logging.getLogger(__name__)


class MainWindowNotificationsMixin:

    def _hide_notifications_panel(self):
        panel = getattr(self, "_notifications_dialog", None)
        if panel is not None:
            try:
                panel.hide_panel()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                try:
                    panel.hide()
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    logger.debug(
                        "MainWindowUiMixin._hide_notifications_panel fallback failed",
                        exc_info=True,
                    )

    def _refresh_notifications_ui(self, items=None) -> None:
        data = (
            list(getattr(self, "notifications_list", []) or [])
            if items is None
            else list(items or [])
        )
        try:
            if getattr(self, "notifications_service", None) is not None:
                self.notifications_service.update_badge()
            self._update_tray_badge()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._refresh_notifications_ui fallback failed",
                exc_info=True,
            )
        try:
            dialog = getattr(self, "_notifications_dialog", None)
            if dialog is not None:
                dialog.set_notifications(data)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._refresh_notifications_ui fallback failed",
                exc_info=True,
            )

    def _sync_notifications_panel_direction(self) -> None:
        try:
            panel = getattr(self, "_notifications_dialog", None)
            if panel is not None and hasattr(panel, "apply_language_layout"):
                panel.apply_language_layout()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._sync_notifications_panel_direction fallback failed",
                exc_info=True,
            )

    def _set_notifications_enabled(self, enabled: bool) -> None:
        set_widget_enabled(getattr(self, "btn_notifications", None), enabled)

    def on_show_notifications(self):
        try:
            if (
                not getattr(self, "btn_notifications", None)
                or not self.btn_notifications.isEnabled()
            ):
                return
            panel = getattr(self, "_notifications_dialog", None)
            if panel is None:
                panel = NotificationsDialog(self)
                panel.mark_all_requested.connect(self.mark_all_notifications_read)
                panel.clear_all_requested.connect(self.clear_notifications)
                panel.mark_one_requested.connect(self.mark_notification_read)
                self._notifications_dialog = panel
            self._sync_notifications_panel_direction()
            if panel.isVisible():
                panel.hide_panel()
                return
            panel.set_notifications(list(getattr(self, "notifications_list", []) or []))
            panel.show_near(getattr(self, "notif_wrap", self.btn_notifications))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.exception("Failed to show notifications panel")

    def mark_notification_read(self, index: int):
        try:
            idx = int(index)
            items = list(getattr(self, "notifications_list", []) or [])
            if idx < 0 or idx >= len(items):
                return
            updated, changed = NotificationsStateService.mark_one_read(items, idx)
            if changed:
                self.notifications_list = updated
                self.unread_notifications = NotificationsStateService.unread_count(
                    updated
                )
            self._refresh_notifications_ui()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.exception("Failed to mark a notification as read")

    def mark_all_notifications_read(self):
        try:
            items = list(getattr(self, "notifications_list", []) or [])
            updated, changed = NotificationsStateService.mark_all_read(items)
            if changed:
                self.notifications_list = updated
                self.unread_notifications = NotificationsStateService.unread_count(
                    updated
                )
            self._refresh_notifications_ui()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.exception("Failed to mark notifications as read")

    def clear_notifications(self):
        try:
            self.notifications_list = NotificationsStateService.clear()
            self.unread_notifications = 0
            self._refresh_notifications_ui([])
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.exception("Failed to clear notifications")


class MainWindowTrayMixin:

    def _should_keep_running_in_tray_on_close(self) -> bool:
        try:
            return parse_bool(
                self.db_manager.get_setting("enable_tray_background", "False"), False
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _is_tray_enabled(self) -> bool:
        try:
            tray_background = parse_bool(
                self.db_manager.get_setting("enable_tray_background", "False"), False
            )
            desktop_alerts = parse_bool(
                self.db_manager.get_setting("enable_desktop_notifications", "True"),
                True,
            )
            return bool(tray_background or desktop_alerts)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _destroy_tray_icon(self):
        adapter = getattr(self, "_tray_adapter", None)
        if adapter is not None:
            try:
                adapter.close()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug(
                    "MainWindowTrayMixin._destroy_tray_icon adapter cleanup failed",
                    exc_info=True,
                )
        self._tray_adapter = None
        self._tray_menu = None
        self.tray_icon = None

    def _ensure_tray_icon(self):
        if getattr(self, "tray_icon", None) is None:
            self.init_tray_icon()
        return getattr(self, "tray_icon", None)

    def _show_tray_icon(self) -> bool:
        try:
            tray = self._ensure_tray_icon()
            if tray is None:
                return False
            adapter = getattr(self, "_tray_adapter", None)
            if adapter is not None:
                adapter.show()
            else:
                tray.show()
                tray.setVisible(True)
            return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("MainWindowUiMixin._show_tray_icon failed", exc_info=True)
            return False

    def _minimize_to_tray(self, *, show_message: bool = True) -> bool:
        tray = self._ensure_tray_icon()
        if tray is None:
            return False
        try:
            adapter = getattr(self, "_tray_adapter", None)
            if adapter is not None:
                adapter.show()
            else:
                tray.show()
                tray.setVisible(True)
            self.hide()
            self._apply_monitor_schedule(restart=bool(self.app_state.session))
            if show_message and parse_bool(
                self.db_manager.get_setting("tray_show_message_on_minimize", "False"),
                False,
            ):
                tray.showMessage(
                    APP_DISPLAY_NAME,
                    _("App is running in background."),
                    QSystemTrayIcon.Information,
                    2500,
                )
            return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("MainWindowUiMixin._minimize_to_tray failed", exc_info=True)
            return False

    def init_tray_icon(self):
        self._destroy_tray_icon()
        if not self._is_tray_enabled():
            return
        try:
            adapter = SystemTrayAdapter(
                parent=self,
                base_icon=tray_icon_or_fallback(self),
                tooltip=APP_DISPLAY_NAME,
                open_window=self._restore_from_tray,
                logout=getattr(self, "logout"),
                exit_application=getattr(self, "close_app_completely", self.close),
                activated=self.on_tray_icon_activated,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.warning("System tray is not available on this environment")
            return

        self._tray_adapter = adapter
        self.tray_icon = adapter.tray_icon
        self._tray_menu = adapter.menu
        self._update_tray_badge()
        try:
            adapter.hide()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowTrayMixin.init_tray_icon hide failed",
                exc_info=True,
            )

    def _update_tray_badge(self) -> None:
        adapter = getattr(self, "_tray_adapter", None)
        if adapter is None:
            return
        unread_count = int(getattr(self, "unread_notifications", 0) or 0)
        update_available = bool(
            getattr(self, "update_available", False)
            or getattr(self, "_update_available", False)
            or getattr(self, "_pending_update_available", False)
        )
        try:
            adapter.set_badge(
                unread_count=unread_count,
                update_available=update_available,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowTrayMixin._update_tray_badge failed",
                exc_info=True,
            )

    def set_tray_update_available(self, available: bool) -> None:
        self._pending_update_available = bool(available)
        self._update_tray_badge()

    def refresh_tray_icon(self):
        try:
            self.init_tray_icon()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.exception("refresh_tray_icon failed")

    def _bring_to_front(self, *, show_if_hidden: bool = False) -> None:
        try:
            if self.isMinimized():
                self.showNormal()
            elif show_if_hidden and (not self.isVisible()):
                self.show()
            if show_if_hidden and (not self.isVisible()):
                self.setVisible(True)
            self.raise_()
            self.activateWindow()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._bring_to_front fallback failed", exc_info=True
            )

    def _restore_from_tray(self):
        self._bring_to_front(show_if_hidden=True)
        try:
            if getattr(self, "tray_icon", None) is not None:
                self.tray_icon.hide()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._restore_from_tray fallback failed", exc_info=True
            )
        try:
            self._apply_monitor_schedule(restart=bool(self.app_state.session))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "MainWindowUiMixin._restore_from_tray fallback failed", exc_info=True
            )

    def on_tray_icon_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._restore_from_tray()
