from __future__ import annotations
from typing import ClassVar
import logging
import re
from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from runtime.shared.objects import normalized_result_key
from runtime.shared.settings.config import _, resource_path
from runtime.shared.settings.version import APP_VERSION
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.fitting import FitOnceToScreenMixin
from runtime.presentation.layout.helpers import add_stretch, set_minimum_height, set_size_policy
from runtime.presentation.widgets import apply_popup_contract
from runtime.presentation.widgets import polish_dialog_action_buttons

logger = logging.getLogger(__name__)
_VERSION_RE = re.compile("\\b\\d+(?:\\.\\d+){1,3}\\b")


class _DialogCardMixin:

    def _card(
        self, object_name: str, title: str = "", subtitle: str = ""
    ) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName(object_name)
        layout = QVBoxLayout(card)
        _layout_rules.set_layout_contents_margins(layout, 10, 8, 10, 8)
        _layout_rules.set_layout_spacing(layout, 6)
        if title:
            lbl_title = QLabel(title)
            lbl_title.setObjectName("SectionTitle")
            layout.addWidget(lbl_title)
        if subtitle:
            lbl_subtitle = QLabel(subtitle)
            lbl_subtitle.setObjectName("MutedStatusLabel")
            lbl_subtitle.setWordWrap(True)
            layout.addWidget(lbl_subtitle)
        return (card, layout)


class UpdateActionDialog(FitOnceToScreenMixin, QDialog):
    result_key = normalized_result_key
    fit_once_screen_options: ClassVar[dict[str, int | float | str]] = {
        "width_ratio": 0.28,
        "height_ratio": 0.2,
        "min_width": 350,
        "min_height": 180,
        "padding": 28,
    }

    def __init__(
        self,
        parent=None,
        *,
        title: str,
        details: str,
        informative_text: str,
        primary_text: str,
        secondary_text: str,
        tertiary_text: str | None = None,
        current_version: str = "",
        target_version: str = "",
        mandatory: bool = False,
        mode: str = "update",
    ) -> None:
        super().__init__(parent)
        self._fit_once = False
        self._result = "secondary"
        self.setWindowTitle(title)
        apply_popup_contract(
            self,
            object_name="UpdateActionDialog",
            modal=True,
            size_grip=False,
            width_ratio=0.34,
            height_ratio=0.24,
            min_width=380,
            min_height=200,
            max_width=620,
            max_height=360,
        )
        root = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(root, 10, 9, 10, 10)
        _layout_rules.set_layout_spacing(root, 7)
        badge = QLabel(_("Update") if mode == "update" else _("Check"))
        badge.setObjectName("UpdateDialogBadge")
        root.addWidget(badge, 0, Qt.AlignLeft)
        title_label = QLabel(details)
        title_label.setObjectName("UpdateDialogTitle")
        title_label.setWordWrap(True)
        root.addWidget(title_label)
        meta_row = QHBoxLayout()
        _layout_rules.set_layout_spacing(meta_row, 8)
        if current_version:
            curr = QLabel(_("Current: {version}").format(version=current_version))
            curr.setObjectName("UpdateDialogMeta")
            meta_row.addWidget(curr)
        if target_version:
            target = QLabel(_("Latest: {version}").format(version=target_version))
            target.setObjectName("UpdateDialogMeta")
            meta_row.addWidget(target)
        add_stretch(meta_row, 1)
        root.addLayout(meta_row)
        info = QLabel(informative_text or "")
        info.setObjectName("UpdateDialogNotes")
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        set_minimum_height(info, 32)
        set_size_policy(info, QSizePolicy.Expanding, QSizePolicy.Preferred)
        root.addWidget(info, 0)
        if mandatory:
            notice = QLabel(
                _("This update is required to keep the application supported.")
            )
            notice.setObjectName("UpdateDialogMandatory")
            notice.setWordWrap(True)
            root.addWidget(notice)
        button_box = QDialogButtonBox()
        self.primary_button = QPushButton(primary_text)
        self.primary_button.clicked.connect(self._accept_primary)
        button_box.addButton(self.primary_button, QDialogButtonBox.AcceptRole)
        self.secondary_button = QPushButton(secondary_text)
        self.secondary_button.clicked.connect(self._accept_secondary)
        button_box.addButton(self.secondary_button, QDialogButtonBox.RejectRole)
        self.tertiary_button = None
        if tertiary_text:
            self.tertiary_button = QPushButton(tertiary_text)
            self.tertiary_button.clicked.connect(self._accept_tertiary)
            button_box.addButton(self.tertiary_button, QDialogButtonBox.ActionRole)
        polish_dialog_action_buttons(
            self.primary_button, self.secondary_button, self.tertiary_button
        )
        root.addWidget(button_box)

    def _accept_choice(self, result: str, close_action) -> None:
        self._result = result
        close_action()

    def _accept_primary(self) -> None:
        self._accept_choice("primary", self.accept)

    def _accept_secondary(self) -> None:
        self._accept_choice("secondary", self.reject)

    def _accept_tertiary(self) -> None:
        self._accept_choice("tertiary", lambda: self.done(2))


class _UpdateLogoBadge(QWidget):
    """Paint the branded circular logo and progress arc used by update dialogs."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._progress = 0
        self._logo = QPixmap(resource_path("resources", "images", "logo.png"))
        self.setObjectName("UpdateDownloadLogoBadge")
        self.setMinimumSize(100, 100)
        self.setMaximumSize(100, 100)

    def setProgress(self, value: int) -> None:
        self._progress = max(0, min(100, int(value)))
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        bounds = self.rect().adjusted(9, 9, -9, -9)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 248))
        painter.drawEllipse(bounds)
        logo_bounds = bounds.adjusted(21, 21, -21, -21)
        if not self._logo.isNull():
            scaled = self._logo.scaled(
                logo_bounds.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            x = logo_bounds.center().x() - scaled.width() // 2
            y = logo_bounds.center().y() - scaled.height() // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.setPen(QColor("#0F6DEB"))
            painter.drawText(bounds, Qt.AlignCenter, "H")
        if self._progress <= 0:
            return
        arc_rect = QRectF(bounds).adjusted(-1.5, -1.5, 1.5, 1.5)
        painter.setPen(QPen(QColor("#0F6DEB"), 5.2, Qt.SolidLine, Qt.RoundCap))
        span_angle = -int(self._progress * 3.6 * 16)
        painter.drawArc(arc_rect, 88 * 16, span_angle)


class UpdateProgressDialog(FitOnceToScreenMixin, QDialog):
    fit_once_screen_options: ClassVar[dict[str, int | float | str]] = {
        "width_ratio": 0.38,
        "height_ratio": 0.32,
        "min_width": 560,
        "min_height": 360,
        "padding": 28,
    }

    def __init__(self, parent=None, *, title: str, label_text: str) -> None:
        super().__init__(parent)
        self._fit_once = False
        self._closing_allowed = False
        self._target_version = self._extract_version(label_text) or APP_VERSION
        self._base_stage_text = ""
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(
            (self.windowFlags() | Qt.FramelessWindowHint) & ~Qt.WindowCloseButtonHint
        )
        apply_popup_contract(
            self,
            object_name="UpdateProgressDialog",
            modal=True,
            size_grip=False,
            width_ratio=0.38,
            height_ratio=0.32,
            min_width=560,
            min_height=360,
            max_width=780,
            max_height=480,
        )
        shell = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(shell, 16, 16, 16, 16)
        _layout_rules.set_layout_spacing(shell, 0)
        self.card = QFrame()
        self.card.setObjectName("UpdateDownloadCard")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 13)
        shadow.setColor(QColor(13, 42, 82, 72))
        self.card.setGraphicsEffect(shadow)
        shell.addWidget(self.card, 1)
        root = QVBoxLayout(self.card)
        _layout_rules.set_layout_contents_margins(root, 42, 30, 42, 34)
        _layout_rules.set_layout_spacing(root, 12)
        self.logo_badge = _UpdateLogoBadge(self.card)
        root.addWidget(self.logo_badge, 0, Qt.AlignHCenter)
        self.title_label = QLabel(_("Downloading Update..."))
        self.title_label.setObjectName("UpdateDownloadTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(False)
        root.addWidget(self.title_label)
        self.version_label = QLabel(self._version_text())
        self.version_label.setObjectName("UpdateDownloadVersion")
        self.version_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.version_label)
        progress_block = QVBoxLayout()
        _layout_rules.set_layout_contents_margins(progress_block, 8, 8, 8, 0)
        _layout_rules.set_layout_spacing(progress_block, 7)
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("UpdateDownloadPercent")
        self.percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        progress_block.addWidget(self.percent_label)
        self.progress = QProgressBar()
        self.progress.setObjectName("UpdateDownloadProgressBar")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        progress_block.addWidget(self.progress)
        root.addLayout(progress_block)
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("UpdateDownloadDetail")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.hide()
        root.addWidget(self.detail_label)
        self.footer_label = QLabel(
            _(
                "*The application will close to install the update and restart automatically.*"
            )
        )
        self.footer_label.setObjectName("UpdateDownloadFooter")
        self.footer_label.setAlignment(Qt.AlignCenter)
        self.footer_label.setWordWrap(True)
        root.addWidget(self.footer_label)
        self._value_animation = QPropertyAnimation(self.progress, b"value", self)
        self._value_animation.setDuration(240)
        self._value_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(650)
        self._pulse_timer.timeout.connect(self._advance_pulse)
        self._pulse_timer.start()

    def closeEvent(self, event) -> None:
        if self._closing_allowed:
            super().closeEvent(event)
            return
        event.ignore()

    def hide(self) -> None:
        self._closing_allowed = True
        super().hide()

    def setLabelText(self, text: str) -> None:
        version = self._extract_version(text)
        if version:
            self._target_version = version
            self.version_label.setText(self._version_text())
        lower = str(text or "").lower()
        if "install" in lower:
            self.title_label.setText(_("Installing Update..."))
        else:
            self.title_label.setText(_("Downloading Update..."))

    def setDetailText(self, text: str) -> None:
        clean = str(text or "").strip()
        self.detail_label.setText(clean)
        self.detail_label.setVisible(bool(clean))

    def setStageText(self, text: str) -> None:
        self._base_stage_text = str(text or "").strip()

    def setFooterText(self, text: str) -> None:
        clean = str(text or "").strip()
        if "restart" in clean.lower() or "automatically" in clean.lower():
            self.footer_label.setText(
                _(
                    "*The application will close to install the update and restart automatically.*"
                )
            )
        elif clean:
            self.footer_label.setText(clean)

    def setValue(self, value: int) -> None:
        current = max(0, min(100, int(value)))
        self.percent_label.setText(f"{current}%")
        self.logo_badge.setProgress(current)
        self._value_animation.stop()
        self._value_animation.setStartValue(int(self.progress.value()))
        self._value_animation.setEndValue(current)
        self._value_animation.start()

    def value(self) -> int:
        return int(self.progress.value())

    def _advance_pulse(self) -> None:
        if self.value() >= 100:
            return
        base_title = (
            _("Installing Update...")
            if "install" in self._base_stage_text.lower()
            else _("Downloading Update...")
        )
        dots = "." * (len(str(self.title_label.text())) % 3 + 1)
        self.title_label.setText(f"{base_title.rstrip('.')}{dots}")

    @staticmethod
    def _extract_version(text: str) -> str:
        match = _VERSION_RE.search(str(text or ""))
        return match.group(0) if match else ""

    def _version_text(self) -> str:
        return _("Version {version}").format(version=self._target_version)
