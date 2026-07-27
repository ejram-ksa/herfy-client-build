from __future__ import annotations
from typing import Any
from PyQt5.QtCore import QPropertyAnimation, Qt, QTimer
from PyQt5.QtGui import QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.presentation.notifications import build_expiry_toast_view_model
from runtime.shared.settings.config import _, resource_path
from runtime.shared.settings.version import APP_VERSION
from runtime.presentation.layout import helpers as _layout_rules


class ProductExpiryToast(QWidget):
    """Custom Windows-style reminder card for product expiry notifications."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(None)
        self._main_window = parent
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self._fade_animation: QPropertyAnimation | None = None
        self.setObjectName("ProductExpiryToastWindow")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self._build_ui()

    def _build_ui(self) -> None:
        shell = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(shell, 18, 18, 18, 18)
        _layout_rules.set_layout_spacing(shell, 0)
        self.card = QFrame(self)
        self.card.setObjectName("ProductExpiryToastCard")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(15, 23, 42, 68))
        self.card.setGraphicsEffect(shadow)
        shell.addWidget(self.card)
        root = QVBoxLayout(self.card)
        _layout_rules.set_layout_contents_margins(root, 28, 24, 28, 20)
        _layout_rules.set_layout_spacing(root, 16)
        body_row = QHBoxLayout()
        _layout_rules.set_layout_spacing(body_row, 24)
        self.logo_label = QLabel()
        self.logo_label.setObjectName("ProductExpiryToastLogo")
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setMinimumSize(86, 86)
        self.logo_label.setMaximumSize(86, 86)
        pixmap = QPixmap(resource_path("resources", "images", "logo.png"))
        if not pixmap.isNull():
            self.logo_label.setPixmap(
                pixmap.scaled(54, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self.logo_label.setText("H")
        body_row.addWidget(self.logo_label, 0, Qt.AlignTop)
        content_col = QVBoxLayout()
        _layout_rules.set_layout_spacing(content_col, 9)
        header_row = QHBoxLayout()
        _layout_rules.set_layout_spacing(header_row, 8)
        self.title_label = QLabel(_("Products expiration tracking"))
        self.title_label.setObjectName("ProductExpiryToastTitle")
        self.title_label.setWordWrap(True)
        header_row.addWidget(self.title_label, 1)
        self.more_label = QLabel("•••")
        self.more_label.setObjectName("ProductExpiryToastMore")
        self.more_label.setAlignment(Qt.AlignCenter)
        header_row.addWidget(self.more_label, 0)
        self.close_button = QToolButton()
        self.close_button.setObjectName("ProductExpiryToastClose")
        self.close_button.setText("×")
        self.close_button.clicked.connect(self.hide)
        header_row.addWidget(self.close_button, 0)
        content_col.addLayout(header_row)
        self.details_label = QLabel()
        self.details_label.setObjectName("ProductExpiryToastDetails")
        self.details_label.setTextFormat(Qt.RichText)
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.details_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        content_col.addWidget(self.details_label)
        body_row.addLayout(content_col, 1)
        root.addLayout(body_row)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("ProductExpiryToastSummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        root.addWidget(self.summary_label)
        self.footer = QFrame()
        self.footer.setObjectName("ProductExpiryToastFooter")
        footer_row = QHBoxLayout(self.footer)
        _layout_rules.set_layout_contents_margins(footer_row, 0, 14, 0, 0)
        self.version_label = QLabel(_("Version {version}").format(version=APP_VERSION))
        self.version_label.setObjectName("ProductExpiryToastVersion")
        footer_row.addWidget(self.version_label)
        footer_row.addStretch(1)
        self.details_button = QPushButton(_("View Details"))
        self.details_button.setObjectName("ProductExpiryToastDetailsButton")
        bell_icon = QIcon(resource_path("resources", "images", "bell.png"))
        if not bell_icon.isNull():
            self.details_button.setIcon(bell_icon)
        self.details_button.clicked.connect(self._open_details)
        footer_row.addWidget(self.details_button, 0)
        root.addWidget(self.footer)

    def show_payload(self, *, title: str, payload: dict, duration_s: int) -> bool:
        try:
            view = build_expiry_toast_view_model(
                title=title, payload=payload, duration_s=duration_s
            )
            self.title_label.setText(view.title)
            if view.has_details:
                self.details_label.setText(view.detail_html)
                self.details_label.show()
                self.summary_label.hide()
            else:
                self.details_label.hide()
                self.summary_label.setText(view.summary_text)
                self.summary_label.setVisible(bool(view.summary_text))
            self.version_label.setText(
                _("Version {version}").format(version=APP_VERSION)
            )
            self.adjustSize()
            self._fit_and_move_to_screen_corner()
            self._hide_timer.stop()
            self._hide_timer.start(max(3000, view.duration_s * 1000))
            self._fade_in()
            self.show()
            self.raise_()
            return True
        except UI_OPERATION_EXCEPTIONS:
            return False

    def close_now(self) -> None:
        try:
            self._hide_timer.stop()
            self.hide()
        except UI_OPERATION_EXCEPTIONS:
            return

    def _fade_in(self) -> None:
        self.setWindowOpacity(0.0)
        self._fade_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_animation.setDuration(180)
        self._fade_animation.setStartValue(0.0)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

    def _fit_and_move_to_screen_corner(self) -> None:
        app = QApplication.instance()
        screen = None
        if app is not None:
            if self._main_window is not None and hasattr(self._main_window, "geometry"):
                try:
                    center = self._main_window.geometry().center()
                    screen = app.screenAt(center)
                except UI_OPERATION_EXCEPTIONS:
                    screen = None
            screen = screen or app.primaryScreen()
        if screen is None:
            self.resize(max(660, self.width()), max(288, self.height()))
            return
        area = screen.availableGeometry()
        max_width = max(480, int(area.width() * 0.58))
        max_height = max(250, int(area.height() * 0.68))
        target_width = min(max(660, self.width()), max_width)
        target_height = min(max(288, self.height()), max_height)
        self.resize(target_width, target_height)
        margin = 26
        x = area.right() - self.width() - margin
        y = area.bottom() - self.height() - margin
        self.move(max(area.left() + margin, x), max(area.top() + margin, y))

    def _open_details(self) -> None:
        self.hide()
        target = getattr(self._main_window, "on_show_notifications", None)
        if not callable(target):
            return
        try:
            target.__call__()
        except UI_OPERATION_EXCEPTIONS:
            return
