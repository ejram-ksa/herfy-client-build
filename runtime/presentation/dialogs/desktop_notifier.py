from __future__ import annotations
import logging
from typing import Any
from PyQt5.QtWidgets import QSystemTrayIcon
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.settings.config import APP_DISPLAY_NAME
from runtime.presentation.dialogs.notification_toast import ProductExpiryToast
from runtime.presentation.widgets import app_icon
from runtime.bootstrap.runtime.single_instance import reveal_window

logger = logging.getLogger(__name__)


class DesktopNotifier:
    """Display branded desktop notifications with tray fallback."""

    def __init__(self, main_window: Any) -> None:
        self._main_window = main_window
        self._toast: ProductExpiryToast | None = None

    @staticmethod
    def _popup_title(title: str) -> str:
        clean = str(title or "").strip()
        return clean or APP_DISPLAY_NAME

    def show_card_notification(
        self, title: str, payload: dict | None, duration_s: int
    ) -> bool:
        try:
            if self._toast is None:
                self._toast = ProductExpiryToast(self._main_window)
            return self._toast.show_payload(
                title=self._popup_title(title),
                payload=dict(payload or {}),
                duration_s=duration_s,
            )
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception("Custom notification card failed")
            return False

    def show_tray_message(self, title: str, message: str, duration_s: int) -> bool:
        try:
            tray = getattr(self._main_window, "tray_icon", None)
            if tray is None and hasattr(self._main_window, "_show_tray_icon"):
                try:
                    self._main_window._show_tray_icon()
                except SERVICE_OPERATION_EXCEPTIONS:
                    logger.debug(
                        "Unable to create tray icon for notification", exc_info=True
                    )
                tray = getattr(self._main_window, "tray_icon", None)
            if tray is None:
                return False
            if not bool(getattr(tray, "_herfy_message_restore_connected", False)):
                try:
                    tray.messageClicked.connect(
                        lambda: reveal_window(self._main_window)
                    )
                    setattr(tray, "_herfy_message_restore_connected", True)
                except SERVICE_OPERATION_EXCEPTIONS:
                    logger.debug("Tray message restore binding failed", exc_info=True)
            try:
                if not QSystemTrayIcon.isSystemTrayAvailable():
                    logger.warning("Windows notification tray is not available")
                    return False
                if not tray.supportsMessages():
                    logger.warning("System tray message balloons are not supported")
                    return False
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug("Tray notification capability check failed", exc_info=True)
            icon = app_icon()
            if not icon.isNull():
                tray.setIcon(icon)
            if not tray.isVisible():
                tray.show()
                tray.setVisible(True)
            msecs = max(1800, int(duration_s) * 1000)
            try:
                if not icon.isNull():
                    tray.showMessage(self._popup_title(title), message, icon, msecs)
                else:
                    tray.showMessage(
                        self._popup_title(title), message, tray.Information, msecs
                    )
            except TypeError:
                tray.showMessage(
                    self._popup_title(title), message, tray.Information, msecs
                )
            return True
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception("Tray notification failed")
            return False

    def close(self) -> None:
        if self._toast is not None:
            self._toast.close_now()
            self._toast = None
