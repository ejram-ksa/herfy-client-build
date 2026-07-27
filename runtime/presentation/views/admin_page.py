from __future__ import annotations

import logging
from typing import Any
from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.application.services.admin import AdminService
from runtime.bootstrap.qt.workers import WorkerRegistry, client_thread_pool
from runtime.presentation.widgets import apply_popup_contract, center_dialog_over_parent
from runtime.presentation.views.admin_sections import (
    AdminHierarchyMixin,
    AdminPagesMixin,
    AdminStateMixin,
)

logger = logging.getLogger(__name__)


class AdminDashboardDialog(
    AdminStateMixin, AdminPagesMixin, AdminHierarchyMixin, QDialog
):
    """Administrative console with a stable service contract."""

    def __init__(self, cloud_service: Any, parent=None, *, embedded: bool = False):
        super().__init__(parent)
        self.setObjectName("AdminDashboardDialog")
        self.setWindowTitle(_("Control Panel"))
        self.cloud_service = cloud_service
        self.app_state = getattr(parent, "app_state", None)
        self.admin_service = AdminService(cloud_service, app_state=self.app_state)
        self._pool = client_thread_pool()
        self._worker_registry = WorkerRegistry(self._pool)
        self._closed = False
        self._snapshot: dict[str, Any] = {}
        self._current_route = "hierarchy"
        self._selected_hierarchy: dict[str, Any] = {}
        self._embedded = bool(embedded)
        self._build_ui()
        self._apply_dialog_contract()
        QTimer.singleShot(0, self.refresh_all_async)

    def _apply_dialog_contract(self) -> None:
        if self._embedded:
            self.setMinimumSize(0, 0)
            return
        try:
            apply_popup_contract(
                self,
                object_name="AdminDashboardDialog",
                modal=False,
                size_grip=True,
                width_ratio=0.78,
                height_ratio=0.76,
                min_width=900,
                min_height=520,
                max_width=1440,
                max_height=960,
                padding=32,
                constrain_to_parent=False,
            )
            QTimer.singleShot(0, self._stabilize_screen_geometry)
        except UI_OPERATION_EXCEPTIONS:
            self.resize(960, 600)

    def _active_available_geometry(self):
        app = QApplication.instance()
        if app is None:
            return None
        screen = None
        try:
            handle = self.windowHandle()
            screen = handle.screen() if handle is not None else None
        except UI_OPERATION_EXCEPTIONS:
            screen = None
        if screen is None:
            try:
                center = self.frameGeometry().center()
                screen = app.screenAt(center) if hasattr(app, "screenAt") else None
            except UI_OPERATION_EXCEPTIONS:
                screen = None
        if screen is None:
            screen = app.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _stabilize_screen_geometry(self) -> None:
        if self._embedded or not self.isVisible():
            return
        try:
            available = self._active_available_geometry()
            if available is None or self.isMaximized() or self.isFullScreen():
                return
            frame = self.frameGeometry()
            client = self.geometry()
            frame_extra_width = max(0, frame.width() - client.width())
            frame_extra_height = max(0, frame.height() - client.height())
            max_client_width = max(640, available.width() - frame_extra_width - 16)
            max_client_height = max(420, available.height() - frame_extra_height - 16)
            target_width = min(max(900, self.width()), max_client_width)
            target_height = min(max(520, self.height()), max_client_height)
            if self.width() != target_width or self.height() != target_height:
                self.resize(target_width, target_height)
            center_dialog_over_parent(self)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Admin dashboard screen fit failed", exc_info=True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._embedded:
            return
        try:
            handle = self.windowHandle()
            if handle is not None and not bool(
                getattr(self, "_screen_change_connected", False)
            ):
                handle.screenChanged.connect(
                    lambda _screen: QTimer.singleShot(
                        0, self._stabilize_screen_geometry
                    )
                )
                self._screen_change_connected = True
        except UI_OPERATION_EXCEPTIONS:
            self._screen_change_connected = False
        QTimer.singleShot(0, self._stabilize_screen_geometry)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        screen_change_event = getattr(QEvent, "ScreenChangeInternal", None)
        if screen_change_event is not None and event.type() == screen_change_event:
            QTimer.singleShot(0, self._stabilize_screen_geometry)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SetNoConstraint)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)
        header = QFrame(self)
        header.setObjectName("AdminHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 14, 16, 14)
        h.setSpacing(12)
        badge = QLabel("⚙")
        badge.setObjectName("AdminHeaderBadge")
        badge.setAlignment(Qt.AlignCenter)
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        self.title_label = QLabel(_("Control Panel"))
        self.title_label.setObjectName("AdminTitle")
        self.subtitle_label = QLabel(
            _("Server-controlled management for users, branches, and permissions.")
        )
        self.subtitle_label.setObjectName("AdminSubtitle")
        self.subtitle_label.setWordWrap(True)
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        self.status_label = QLabel(_("Connecting to server..."))
        self.status_label.setObjectName("AdminStatusPill")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.refresh_button = QPushButton(_("Refresh"))
        self.refresh_button.setObjectName("AdminRefreshButton")
        self.refresh_button.clicked.connect(self.refresh_all_async)
        h.addWidget(badge)
        h.addLayout(title_box, 1)
        h.addWidget(self.status_label)
        h.addWidget(self.refresh_button)
        root.addWidget(header)
        self.body_scroll = QScrollArea(self)
        self.body_scroll.setObjectName("AdminBodyScroll")
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        self.body_scroll.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.body_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.body_scroll.setMinimumSize(0, 0)
        self.body_host = QWidget(self.body_scroll)
        self.body_host.setObjectName("AdminBodyViewport")
        body = QHBoxLayout(self.body_host)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        self.nav_frame = QFrame(self.body_host)
        self.nav_frame.setObjectName("AdminNav")
        nav = QVBoxLayout(self.nav_frame)
        nav.setContentsMargins(10, 10, 10, 10)
        nav.setSpacing(8)
        self.nav_buttons: dict[str, QPushButton] = {}
        for route, label in (
            ("hierarchy", _("Hierarchy")),
            ("overview", _("Overview")),
            ("users", _("Users")),
            ("structure", _("Structure")),
            ("permissions", _("Permissions")),
        ):
            btn = QPushButton(label)
            btn.setObjectName("AdminNavButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, r=route: self._show_route(r))
            self.nav_buttons[route] = btn
            nav.addWidget(btn)
        nav.addStretch(1)
        self.stack = QStackedWidget(self)
        self.stack.setObjectName("AdminContentStack")
        self.pages: dict[str, QWidget] = {
            "hierarchy": self._build_hierarchy_page(),
            "overview": self._build_overview_page(),
            "users": self._build_users_page(),
            "structure": self._build_structure_page(),
            "permissions": self._build_permissions_page(),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        body.addWidget(self.nav_frame)
        body.addWidget(self.stack, 1)
        self.body_scroll.setWidget(self.body_host)
        root.addWidget(self.body_scroll, 1)
        self._show_route("hierarchy")


__all__ = ["AdminDashboardDialog"]
