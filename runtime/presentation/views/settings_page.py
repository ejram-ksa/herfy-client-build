from __future__ import annotations
import logging
from typing import Any
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.application.services.preferences import SettingsService
from runtime.application.services.settings_schema import (
    CANONICAL_SETTINGS_DEFAULTS,
    validate_canonical_settings,
)
from runtime.application.services.translations import (
    available_languages,
    get_language,
    is_rtl,
    set_language,
    tr,
)
from runtime.presentation.widgets import apply_popup_contract, center_dialog_over_parent

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Compact customer settings dialog for local UI and alert behavior only."""

    def __init__(self, db_manager: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db_manager = db_manager
        self.settings_service = SettingsService(db_manager)
        self.widgets: dict[str, Any] = {}
        self._label_keys: list[tuple[Any, str]] = []
        self._button_keys: list[tuple[Any, str]] = []
        self._original_snapshot: dict[str, str] = {}
        self.alert_settings_changed = False
        self.setObjectName("SettingsDialog")
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumSize(720, 540)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        try:
            apply_popup_contract(
                self,
                object_name="SettingsDialog",
                modal=True,
                size_grip=False,
                width_ratio=0.52,
                height_ratio=0.72,
                min_width=720,
                min_height=540,
                max_width=920,
                max_height=700,
            )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("SettingsDialog popup contract unavailable", exc_info=True)
        self._build_ui()
        self.load_settings()

    def _remember_label(self, widget: Any, key: str) -> Any:
        self._label_keys.append((widget, key))
        try:
            widget.setText(tr(key))
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "Unable to apply translated label text: %s", key, exc_info=True
            )
        return widget

    def _remember_button(self, widget: Any, key: str) -> Any:
        self._button_keys.append((widget, key))
        try:
            widget.setText(tr(key))
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "Unable to apply translated button text: %s", key, exc_info=True
            )
        return widget

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)
        header = QFrame(self)
        header.setObjectName("SettingsHeader")
        header.setProperty("settingsHeader", True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(12)
        icon = QLabel("⚙", self)
        icon.setObjectName("SettingsHeaderIcon")
        icon.setAlignment(Qt.AlignCenter)
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        self.title_label = self._remember_label(QLabel(), "settings.title")
        self.title_label.setObjectName("SettingsTitle")
        self.subtitle_label = self._remember_label(
            QLabel(), "settings.customer_subtitle"
        )
        self.subtitle_label.setObjectName("SettingsSubtitle")
        self.subtitle_label.setWordWrap(True)
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        close_button = QToolButton(self)
        close_button.setObjectName("SettingsCloseButton")
        close_button.setText("✕")
        close_button.setToolTip(tr("common.close"))
        close_button.clicked.connect(self.reject)
        header_layout.addWidget(icon, 0, Qt.AlignTop)
        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(close_button, 0, Qt.AlignTop)
        root.addWidget(header)
        workspace = QFrame(self)
        workspace.setObjectName("SettingsWorkspace")
        workspace.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        stack = QVBoxLayout(workspace)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(10)
        stack.addWidget(self._build_general_card())
        stack.addWidget(self._build_expiry_card())
        stack.addWidget(self._build_notifications_card())
        stack.addWidget(self._build_monitoring_card())
        stack.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setObjectName("SettingsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(workspace)
        root.addWidget(scroll, 1)
        self.validation_label = QLabel("")
        self.validation_label.setObjectName("SettingsValidationLabel")
        self.validation_label.setWordWrap(True)
        root.addWidget(self.validation_label)
        footer_frame = QFrame(self)
        footer_frame.setObjectName("SettingsFooter")
        footer_layout = QHBoxLayout(footer_frame)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)
        self.btn_reset = self._remember_button(QPushButton(), "settings.reset_defaults")
        self.btn_apply = self._remember_button(QPushButton(), "common.apply")
        self.btn_save = self._remember_button(QPushButton(), "common.save")
        self.btn_cancel = self._remember_button(QPushButton(), "common.cancel")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_apply.setObjectName("SecondaryButton")
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_reset.setObjectName("SecondaryButton")
        footer_layout.addWidget(self.btn_reset)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.btn_cancel)
        footer_layout.addWidget(self.btn_apply)
        footer_layout.addWidget(self.btn_save)
        self.btn_reset.clicked.connect(self.reset_defaults)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self.on_apply)
        self.btn_save.clicked.connect(self.on_save)
        root.addWidget(footer_frame)

    def _card(self, title_key: str) -> tuple[QFrame, QFormLayout]:
        card = QFrame(self)
        card.setObjectName("SettingsCard")
        card.setProperty("settingsCard", True)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        title = self._remember_label(QLabel(), title_key)
        title.setObjectName("SettingsCardTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(7)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setLabelAlignment(Qt.AlignLeading | Qt.AlignVCenter)
        layout.addLayout(form)
        layout.addStretch(1)
        return (card, form)

    def _label(self, key: str) -> QLabel:
        label = self._remember_label(QLabel(), key)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        return label

    def _check(self, key: str) -> QCheckBox:
        box = QCheckBox()
        self._remember_label(box, key)
        box.setMinimumWidth(0)
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return box

    @staticmethod
    def _spin(minimum: int, maximum: int, suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        if suffix:
            spin.setSuffix(suffix)
        spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return spin

    def _build_general_card(self) -> QFrame:
        card, form = self._card("settings.general.title")
        language = QComboBox()
        for code in available_languages():
            language.addItem(tr(f"settings.language.{code}"), code)
        self.widgets["language"] = language
        form.addRow(self._label("settings.language"), language)
        self.widgets["start_with_windows"] = self._check("settings.start_with_windows")
        form.addRow("", self.widgets["start_with_windows"])
        return card

    def _build_expiry_card(self) -> QFrame:
        card, form = self._card("settings.expiry.title")
        self.widgets["expiry_expiring_soon_threshold_days"] = self._spin(
            3, 60, f" {tr('Days')}"
        )
        self.widgets["expiry_critical_threshold_days"] = self._spin(
            1, 60, f" {tr('Days')}"
        )
        form.addRow(
            self._label("settings.expiry.expiring_soon_threshold_days"),
            self.widgets["expiry_expiring_soon_threshold_days"],
        )
        form.addRow(
            self._label("settings.expiry.critical_threshold_days"),
            self.widgets["expiry_critical_threshold_days"],
        )
        self.widgets["expiry_expiring_soon_threshold_days"].valueChanged.connect(
            self._sync_threshold_limits
        )
        return card

    def _build_notifications_card(self) -> QFrame:
        card, form = self._card("settings.notifications.title")
        for key, label_key in (
            ("enable_alerts", "settings.notifications.enable_alerts"),
            (
                "enable_smart_notifications",
                "settings.notifications.smart_notifications",
            ),
            (
                "enable_desktop_notifications",
                "settings.notifications.desktop_notifications",
            ),
            ("enable_sounds", "settings.notifications.sound_alerts"),
            ("notification_once_per_day", "settings.notifications.once_per_day"),
        ):
            self.widgets[key] = self._check(label_key)
            form.addRow("", self.widgets[key])
        self.widgets["notification_repeat_interval_minutes"] = self._spin(
            15, 1440, f" {tr('Minutes')}"
        )
        self.widgets["notification_max_per_cycle"] = self._spin(1, 20)
        form.addRow(
            self._label("settings.notifications.repeat_interval"),
            self.widgets["notification_repeat_interval_minutes"],
        )
        form.addRow(
            self._label("settings.notifications.max_per_cycle"),
            self.widgets["notification_max_per_cycle"],
        )
        return card

    def _build_monitoring_card(self) -> QFrame:
        card, form = self._card("settings.monitoring.title")
        self.widgets["monitoring_active_check_interval_minutes"] = self._spin(
            5, 1440, f" {tr('Minutes')}"
        )
        self.widgets["monitoring_background_check_interval_minutes"] = self._spin(
            5, 1440, f" {tr('Minutes')}"
        )
        form.addRow(
            self._label("settings.monitoring.active_interval"),
            self.widgets["monitoring_active_check_interval_minutes"],
        )
        form.addRow(
            self._label("settings.monitoring.background_interval"),
            self.widgets["monitoring_background_check_interval_minutes"],
        )
        self.widgets["monitoring_active_check_interval_minutes"].valueChanged.connect(
            self._sync_monitoring_limits
        )
        return card

    def load_settings(self) -> None:
        state = self.settings_service.load()
        self._original_snapshot = dict(state.alert_snapshot or {})
        self._set_combo_data("language", state.language)
        for key in CANONICAL_SETTINGS_DEFAULTS:
            widget = self.widgets.get(key)
            value = getattr(state, key, CANONICAL_SETTINGS_DEFAULTS.get(key))
            self._set_widget_value(widget, value)
        self._set_widget_value(
            self.widgets.get("start_with_windows"), state.start_with_windows
        )
        self._sync_threshold_limits()
        self._sync_monitoring_limits()
        self._apply_language_direction(state.language)
        self.validation_label.clear()

    def _set_combo_data(self, key: str, value: Any) -> None:
        combo = self.widgets.get(key)
        if not isinstance(combo, QComboBox):
            return
        idx = combo.findData(str(value or ""))
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    @staticmethod
    def _set_widget_value(widget: Any, value: Any) -> None:
        if widget is None:
            return
        if isinstance(widget, QCheckBox):
            widget.setChecked(
                str(value).lower() in {"true", "1", "yes", "on"}
                if not isinstance(value, bool)
                else value
            )
        elif isinstance(widget, QSpinBox):
            try:
                widget.setValue(int(value))
            except (TypeError, ValueError):
                logger.debug("Ignoring invalid spin-box settings value: %r", value)
                return
        elif isinstance(widget, QComboBox):
            idx = widget.findText(str(value or ""))
            if idx >= 0:
                widget.setCurrentIndex(idx)

    def collect_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, widget in self.widgets.items():
            if isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                values[key] = widget.value()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentData() or widget.currentText()
        return values

    def _validate_current(self) -> tuple[bool, dict[str, str], dict[str, str]]:
        validation = validate_canonical_settings(self.collect_values())
        self.validation_label.setText(
            "; ".join((tr(v) for v in validation.errors.values()))
        )
        return (validation.ok, validation.errors, validation.values)

    def on_apply(self) -> None:
        ok, errors, values = self._validate_current()
        if not ok:
            self.validation_label.setText("; ".join((tr(v) for v in errors.values())))
            return
        result = self.settings_service.save(
            values, original_alert_snapshot=self._original_snapshot
        )
        self.alert_settings_changed = bool(
            self.alert_settings_changed or result.alert_settings_changed
        )
        self._original_snapshot = self.settings_service.alert_snapshot()
        self._apply_language_direction(values.get("language", get_language()))
        self._retranslate_ui()
        if result.errors:
            self.validation_label.setText(
                "; ".join((tr(v) for v in result.errors.values()))
            )
        else:
            self.validation_label.setText(tr("settings.apply_success"))

    def on_save(self) -> None:
        self.on_apply()
        if not self.validation_label.text() or self.validation_label.text() == tr(
            "settings.apply_success"
        ):
            self.validation_label.setText(tr("settings.save_success"))
            self.accept()

    def reset_defaults(self) -> None:
        for key, default in CANONICAL_SETTINGS_DEFAULTS.items():
            self._set_widget_value(self.widgets.get(key), default)
        self._set_combo_data("language", CANONICAL_SETTINGS_DEFAULTS["language"])
        self._set_widget_value(self.widgets.get("start_with_windows"), False)
        self._sync_threshold_limits()
        self._sync_monitoring_limits()

    def _sync_threshold_limits(self) -> None:
        soon = self.widgets.get("expiry_expiring_soon_threshold_days")
        critical = self.widgets.get("expiry_critical_threshold_days")
        if isinstance(soon, QSpinBox) and isinstance(critical, QSpinBox):
            critical.setMaximum(max(1, soon.value()))
            if critical.value() > soon.value():
                critical.setValue(soon.value())

    def _sync_monitoring_limits(self) -> None:
        active = self.widgets.get("monitoring_active_check_interval_minutes")
        background = self.widgets.get("monitoring_background_check_interval_minutes")
        if isinstance(active, QSpinBox) and isinstance(background, QSpinBox):
            background.setMinimum(max(5, active.value()))
            if background.value() < active.value():
                background.setValue(active.value())

    def _apply_language_direction(self, language: str | None) -> None:
        code = set_language(language)
        direction = Qt.RightToLeft if is_rtl(code) else Qt.LeftToRight
        self.setLayoutDirection(direction)

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(tr("settings.title"))
        self.subtitle_label.setText(tr("settings.customer_subtitle"))
        for widget, key in self._label_keys:
            try:
                widget.setText(tr(key))
            except UI_OPERATION_EXCEPTIONS:
                logger.debug("Failed to retranslate label %s", key, exc_info=True)
        for widget, key in self._button_keys:
            try:
                widget.setText(tr(key))
            except UI_OPERATION_EXCEPTIONS:
                logger.debug("Failed to retranslate button %s", key, exc_info=True)
        language = self.widgets.get("language")
        if isinstance(language, QComboBox):
            current = language.currentData()
            language.blockSignals(True)
            language.clear()
            for code in available_languages():
                language.addItem(tr(f"settings.language.{code}"), code)
            idx = language.findData(current or get_language())
            language.setCurrentIndex(idx if idx >= 0 else 0)
            language.blockSignals(False)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        try:
            center_dialog_over_parent(self)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("SettingsDialog center failed", exc_info=True)


SettingsPage = SettingsDialog
__all__ = ["SettingsDialog", "SettingsPage"]
