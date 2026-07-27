from __future__ import annotations

from typing import Callable

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QAction, QMenu, QSystemTrayIcon, QWidget


from runtime.presentation.qt.tray_contract import (
    EXIT_TEXT,
    LOGOUT_TEXT,
    OPEN_TEXT,
    TrayBadgeState,
)


class SystemTrayAdapter:
    """Single QSystemTrayIcon implementation for the desktop application."""

    OPEN_TEXT = OPEN_TEXT
    LOGOUT_TEXT = LOGOUT_TEXT
    EXIT_TEXT = EXIT_TEXT

    def __init__(
        self,
        *,
        parent: QWidget,
        base_icon: QIcon,
        tooltip: str,
        open_window: Callable[[], None],
        logout: Callable[[], None],
        exit_application: Callable[[], None],
        activated: Callable[[object], None] | None = None,
    ) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError("system tray is not available")

        self._base_icon = QIcon(base_icon)
        self._state = TrayBadgeState()
        self.tray_icon = QSystemTrayIcon(parent)
        self.tray_icon.setToolTip(str(tooltip))

        self.menu = QMenu(parent)
        self.open_action = QAction(self.OPEN_TEXT, parent)
        self.logout_action = QAction(self.LOGOUT_TEXT, parent)
        self.exit_action = QAction(self.EXIT_TEXT, parent)

        # Menu actions intentionally contain text only: no icons or custom formatting.
        self.open_action.triggered.connect(open_window)
        self.logout_action.triggered.connect(logout)
        self.exit_action.triggered.connect(exit_application)

        self.menu.addAction(self.open_action)
        self.menu.addAction(self.logout_action)
        self.menu.addAction(self.exit_action)
        self.tray_icon.setContextMenu(self.menu)

        if activated is not None:
            self.tray_icon.activated.connect(activated)

        self._apply_icon()

    @property
    def state(self) -> TrayBadgeState:
        return self._state

    def set_badge(self, *, unread_count: int = 0, update_available: bool = False) -> None:
        self._state = TrayBadgeState(
            unread_count=max(0, int(unread_count)),
            update_available=bool(update_available),
        )
        self._apply_icon()

    def show(self) -> None:
        self.tray_icon.show()
        self.tray_icon.setVisible(True)

    def hide(self) -> None:
        self.tray_icon.hide()
        self.tray_icon.setVisible(False)

    def close(self) -> None:
        try:
            self.tray_icon.hide()
            self.tray_icon.setContextMenu(None)
            self.menu.clear()
            self.menu.deleteLater()
            self.tray_icon.deleteLater()
        finally:
            self._state = TrayBadgeState()

    def _apply_icon(self) -> None:
        self.tray_icon.setIcon(self._render_icon(self._base_icon, self._state))

    @staticmethod
    def _render_icon(base_icon: QIcon, state: TrayBadgeState) -> QIcon:
        size = 64
        pixmap = base_icon.pixmap(size, size)
        if pixmap.isNull():
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)
        if not state.visible:
            return QIcon(pixmap)

        canvas = QPixmap(size, size)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.drawPixmap(0, 0, pixmap)

        diameter = 30 if len(state.text) <= 2 else 36
        center = QPoint(size - diameter // 2 - 2, diameter // 2 + 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#D32F2F"))
        painter.drawEllipse(center, diameter // 2, diameter // 2)

        font = QFont()
        font.setBold(True)
        font.setPixelSize(14 if len(state.text) <= 2 else 11)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        rect = (
            center.x() - diameter // 2,
            center.y() - diameter // 2,
            diameter,
            diameter,
        )
        painter.drawText(*rect, Qt.AlignCenter, state.text)
        painter.end()
        return QIcon(canvas)
