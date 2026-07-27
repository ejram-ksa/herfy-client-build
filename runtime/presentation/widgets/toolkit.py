from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

from collections.abc import Iterable
from typing import Any
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.shared.signals import safe_disconnect

DEFAULT_DATA_SIGNALS = ("data_changed", "item_updated", "item_deleted")
SignalCallback = tuple[str, Any]


def _owner_is_alive(owner: Any) -> bool:
    checker = getattr(owner, "_is_alive", None)
    if callable(checker):
        try:
            return bool(checker())
        except UI_OPERATION_EXCEPTIONS:
            return False
    return True


def disconnect_app_state_callbacks(
    owner: Any,
    signal_callbacks: Iterable[SignalCallback],
    *,
    logger_=None,
    context: str = "app_state disconnect",
) -> None:
    old_state = getattr(owner, "_bound_app_state", None)
    if old_state is None:
        return
    for signal_name, callback in signal_callbacks:
        signal = getattr(old_state, signal_name, None)
        if signal is not None:
            safe_disconnect(signal, callback, logger_=logger_, context=context)
    owner._bound_app_state = None


def bind_app_state_callbacks(
    owner: Any,
    app_state: Any,
    signal_callbacks: Iterable[SignalCallback],
    *,
    logger_=None,
    context: str = "app_state bind",
) -> bool:
    if app_state is None:
        owner._bound_app_state = None
        return False
    callbacks = tuple(signal_callbacks)
    try:
        for signal_name, callback in callbacks:
            getattr(app_state, signal_name).connect(callback)
        owner._bound_app_state = app_state
        return True
    except UI_OPERATION_EXCEPTIONS:
        for signal_name, callback in callbacks:
            safe_disconnect(
                getattr(app_state, signal_name, None),
                callback,
                logger_=logger_,
                context=context,
            )
        owner._bound_app_state = None
        if logger_ is not None:
            logger_.debug("%s failed", context, exc_info=True)
        return False


def rebind_app_state_callbacks_if_alive(
    owner: Any,
    app_state: Any,
    signal_callbacks: Iterable[SignalCallback],
    *,
    logger_=None,
    disconnect_context: str = "app_state disconnect",
    bind_context: str = "app_state bind",
) -> bool:
    callbacks = tuple(signal_callbacks)
    disconnect_app_state_callbacks(
        owner, callbacks, logger_=logger_, context=disconnect_context
    )
    if app_state is None or not _owner_is_alive(owner):
        return False
    return bind_app_state_callbacks(
        owner, app_state, callbacks, logger_=logger_, context=bind_context
    )


def rebind_domain_app_state_signal_if_alive(
    owner: Any,
    app_state: Any,
    callback: Any,
    *,
    page_name: str,
    logger_=None,
    signal_names: Iterable[str] = DEFAULT_DATA_SIGNALS,
) -> bool:
    callbacks = tuple(((signal_name, callback) for signal_name in signal_names))
    return rebind_app_state_callbacks_if_alive(
        owner,
        app_state,
        callbacks,
        logger_=logger_,
        disconnect_context=f"{page_name}.bind_app_state disconnect",
        bind_context=f"{page_name}.bind_app_state",
    )


class DomainAppStateBindingMixin:
    app_state_page_name = "Page"
    app_state_callback_name = ""
    app_state_signal_names = DEFAULT_DATA_SIGNALS

    def bind_app_state(self, app_state: Any) -> bool:
        callback = getattr(self, str(self.app_state_callback_name or ""), None)
        if callback is None:
            return False
        module_logger = None
        try:
            import logging

            module_logger = logging.getLogger(self.__class__.__module__)
        except UI_OPERATION_EXCEPTIONS:
            module_logger = None
        return rebind_domain_app_state_signal_if_alive(
            self,
            app_state,
            callback,
            page_name=str(self.app_state_page_name or self.__class__.__name__),
            signal_names=self.app_state_signal_names,
            logger_=module_logger,
        )


import logging
from PyQt5.QtWidgets import QWidget
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.presentation.layout.profiles import apply_profile_properties, profile_for_dimensions

logger = logging.getLogger(__name__)


def _iter_widget_tree(widget) -> Iterable:
    if widget is None:
        return []
    try:
        return [widget, *list(widget.findChildren(QWidget))]
    except SERVICE_OPERATION_EXCEPTIONS:
        return [widget]


def apply_device_properties(
    widget, window_width: int | None = None, app=None, window_height: int | None = None
) -> str:
    profile = profile_for_dimensions(window_width, window_height, app=app)
    if widget is not None:
        try:
            apply_profile_properties(widget, profile)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("apply_device_properties fallback failed", exc_info=True)
    return (
        "compact"
        if profile.is_narrow
        else "comfortable" if profile.is_tablet else "expanded"
    )


def repolish_widget_tree(widget) -> None:
    for item in _iter_widget_tree(widget):
        try:
            if item is None or not hasattr(item, "style"):
                continue
            style = item.style()
            if style is None:
                continue
            style.unpolish(item)
            style.polish(item)
            if hasattr(item, "update"):
                item.update()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("repolish_widget_tree fallback failed", exc_info=True)


from collections.abc import Callable
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QGridLayout, QSizePolicy
from runtime.shared.settings.config import _
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.helpers import set_minimum_height, set_minimum_width, set_size_policy

BUTTON_ROLES = {
    "primary": "PrimaryButton",
    "secondary": "SecondaryButton",
    "danger": "DangerButton",
    "ghost": "GhostButton",
}


def _safe_ui(action: Callable[[], None]) -> None:
    try:
        action()
    except UI_OPERATION_EXCEPTIONS:
        return


def call_if_supported(widget: Any, method_name: str, *args) -> None:
    method = getattr(widget, method_name, None)
    if callable(method):
        method(*args)


_call_if_supported = call_if_supported


def _set_if_supported(widget: Any, method_name: str, value: Any) -> None:
    if value is not None:
        _call_if_supported(widget, method_name, value)


def _iter_widgets(widgets: Iterable[Any] | None) -> Iterable[Any]:
    return widgets or []


def direction_for_rtl(rtl: bool) -> Qt.LayoutDirection:
    return Qt.RightToLeft if bool(rtl) else Qt.LeftToRight


def leading_alignment(rtl: bool) -> Qt.Alignment:
    return Qt.AlignRight if bool(rtl) else Qt.AlignLeft


def trailing_alignment(rtl: bool) -> Qt.Alignment:
    return Qt.AlignLeft if bool(rtl) else Qt.AlignRight


def set_accessibility(widget: Any, *, name: str = "", description: str = "") -> None:
    if widget is None:
        return
    if name and hasattr(widget, "setAccessibleName"):
        widget.setAccessibleName(name)
    if description and hasattr(widget, "setAccessibleDescription"):
        widget.setAccessibleDescription(description)


def set_tab_order(parent: Any, widgets: list[Any]) -> None:
    if parent is None:
        return
    valid = [item for item in widgets if item is not None]
    for left, right in zip(valid, valid[1:], strict=False):
        if hasattr(parent, "setTabOrder"):
            parent.setTabOrder(left, right)


def clear_layout(layout: Any) -> None:
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget() if item is not None else None
        if widget is not None:
            widget.setParent(None)
        child_layout = item.layout() if item is not None else None
        if child_layout is not None:
            clear_layout(child_layout)


def configure_grid_layout(
    layout: QGridLayout, *, margin: int = 8, gap: int = 6
) -> QGridLayout:
    _layout_rules.set_layout_contents_margins(
        layout, int(margin), int(margin), int(margin), int(margin)
    )
    _layout_rules.set_layout_horizontal_spacing(layout, int(gap))
    _layout_rules.set_layout_vertical_spacing(layout, int(gap))
    return layout


def make_grid_panel(object_name: str = "GridPanel") -> QFrame:
    panel = QFrame()
    panel.setObjectName(object_name)
    set_size_policy(panel, QSizePolicy.Expanding, QSizePolicy.Preferred)
    return panel


def set_widget_visible(widget, visible: bool) -> None:
    _set_if_supported(widget, "setVisible", bool(visible))


def set_widget_enabled(widget, enabled: bool) -> None:
    _set_if_supported(widget, "setEnabled", bool(enabled))


def normalize_button_role(role: str | None) -> str:
    key = str(role or "secondary").strip().lower()
    return BUTTON_ROLES.get(key, BUTTON_ROLES["secondary"])


def polish_button(
    button: Any,
    *,
    role: str = "secondary",
    min_width: int | None = None,
    min_height: int | None = None,
    tooltip: str | None = None,
    cursor: Any | None = None,
) -> None:
    if button is None:
        return

    def _apply_polish_button() -> None:
        _call_if_supported(button, "setObjectName", normalize_button_role(role))
        set_minimum_width(button, int(min_width)) if min_width is not None else None
        set_minimum_height(button, int(min_height)) if min_height is not None else None
        if tooltip:
            _call_if_supported(button, "setToolTip", str(tooltip))
        _set_if_supported(button, "setCursor", cursor)

    _safe_ui(_apply_polish_button)


def set_busy_text(
    label: Any, *, busy: bool, text: str = "", busy_text: str | None = None
) -> None:
    if label is None:
        return
    _call_if_supported(
        label, "setText", str(busy_text or _("Loading...")) if busy else str(text or "")
    )


def clamp_text(value: str | None, *, fallback: str = "") -> str:
    normalized = " ".join(str(value or "").split())
    return normalized or str(fallback or "")


def polish_buttons(
    buttons: list[Any] | tuple[Any, ...],
    *,
    default_role: str = "secondary",
    min_height: int | None = None,
) -> None:
    for button in _iter_widgets(buttons):
        polish_button(button, role=default_role, min_height=min_height)


def polish_input(
    widget: Any,
    *,
    min_height: int | None = None,
    tooltip: str | None = None,
    placeholder: str | None = None,
) -> None:
    if widget is None:
        return

    def _apply_polish_input() -> None:
        set_minimum_height(widget, int(min_height)) if min_height is not None else None
        if tooltip:
            _call_if_supported(widget, "setToolTip", str(tooltip))
        if placeholder:
            _call_if_supported(widget, "setPlaceholderText", str(placeholder))

    _safe_ui(_apply_polish_input)


def polish_form_layout(
    form: Any,
    *,
    label_alignment: Any | None = None,
    field_growth_policy: Any | None = None,
    horizontal_spacing: int | None = None,
    vertical_spacing: int | None = None,
) -> None:
    if form is None:
        return

    def _apply_polish_form_layout() -> None:
        _set_if_supported(form, "setLabelAlignment", label_alignment)
        _set_if_supported(form, "setFieldGrowthPolicy", field_growth_policy)
        _set_if_supported(
            form,
            "setHorizontalSpacing",
            None if horizontal_spacing is None else int(horizontal_spacing),
        )
        _set_if_supported(
            form,
            "setVerticalSpacing",
            None if vertical_spacing is None else int(vertical_spacing),
        )

    _safe_ui(_apply_polish_form_layout)


def polish_dialog_action_buttons(
    primary: Any | None = None,
    secondary: Any | None = None,
    tertiary: Any | None = None,
    *,
    min_height: int | None = None,
) -> None:
    polish_button(primary, role="primary", min_height=min_height)
    polish_button(secondary, role="secondary", min_height=min_height)
    polish_button(tertiary, role="ghost", min_height=min_height)


def polish_line_edits(
    widgets: list[Any] | tuple[Any, ...], *, min_height: int | None = None
) -> None:
    for widget in _iter_widgets(widgets):
        polish_input(widget, min_height=min_height)


def polish_card(
    widget: Any, *, object_name: str = "Card", min_height: int | None = None
) -> None:
    if widget is None:
        return

    def _apply_polish_card() -> None:
        _call_if_supported(widget, "setObjectName", str(object_name or "Card"))
        set_minimum_height(widget, int(min_height)) if min_height is not None else None

    _safe_ui(_apply_polish_card)


def polish_page_container(widget: Any, *, object_name: str = "PageContainer") -> None:
    if widget is None:
        return

    def _apply_polish_page_container() -> None:
        _call_if_supported(widget, "setObjectName", str(object_name or "PageContainer"))
        _call_if_supported(widget, "setProperty", "uiRole", "page")

    _safe_ui(_apply_polish_page_container)


def polish_status_label(label: Any, *, role: str = "muted") -> None:
    if label is None:
        return

    def _apply_polish_status_label() -> None:
        _call_if_supported(label, "setObjectName", "StatusLabel")
        _call_if_supported(
            label, "setProperty", "statusRole", str(role or "muted").lower()
        )

    _safe_ui(_apply_polish_status_label)


def set_status_label_text(label: Any, text: str = "", *, role: str = "muted") -> None:
    if label is None:
        return

    def _apply_status_label_text() -> None:
        polish_status_label(label, role=role)
        _call_if_supported(label, "setText", str(text or ""))
        _safe_repolish(label)

    _safe_ui(_apply_status_label_text)


def _safe_repolish(widget: Any) -> None:
    if widget is None or not hasattr(widget, "style"):
        return

    def _apply_safe_repolish() -> None:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        _call_if_supported(widget, "update")

    _safe_ui(_apply_safe_repolish)


def set_input_state(
    widget: Any, state: str = "", *, tooltip: str | None = None
) -> None:
    if widget is None:
        return
    normalized = str(state or "").strip().lower()

    def _apply_set_input_state() -> None:
        _call_if_supported(widget, "setProperty", "inputState", normalized)
        if tooltip is not None:
            _call_if_supported(widget, "setToolTip", str(tooltip or ""))
        _safe_repolish(widget)

    _safe_ui(_apply_set_input_state)


def clear_input_state(widget: Any, *, tooltip: str | None = None) -> None:
    set_input_state(widget, "", tooltip=tooltip)


def set_widget_tooltip_from_text(widget: Any, text: str | None = None) -> None:
    if widget is None or not hasattr(widget, "setToolTip"):
        return

    def _apply_widget_tooltip_from_text() -> None:
        value = text if text is not None else getattr(widget, "text", lambda: "")()
        widget.setToolTip(" ".join(str(value).split()))

    _safe_ui(_apply_widget_tooltip_from_text)


from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout
from runtime.presentation.layout.helpers import add_stretch


def create_page_header(
    title: str,
    *,
    scale: Callable[[int], int],
    subtitle: str = "",
    title_role: str = "pageTitle",
) -> tuple[QFrame, QLabel, QLabel]:
    header = QFrame()
    header.setObjectName("PageHeader")
    layout = QVBoxLayout(header)
    _layout_rules.set_layout_contents_margins(layout, 0, 0, 0, 0)
    _layout_rules.set_layout_spacing(layout, scale(2))
    title_label = QLabel(title)
    title_label.setProperty("uiRole", title_role)
    layout.addWidget(title_label)
    subtitle_label = QLabel(subtitle)
    subtitle_label.setProperty("uiRole", "pageSubTitle")
    subtitle_label.setWordWrap(True)
    subtitle_label.setVisible(bool(subtitle))
    layout.addWidget(subtitle_label)
    return (header, title_label, subtitle_label)


def create_table_heading(
    title: str, *, scale: Callable[[int], int]
) -> tuple[QFrame, QLabel, QLabel]:
    row = QFrame()
    row.setObjectName("TransparentRow")
    layout = QHBoxLayout(row)
    _layout_rules.set_layout_contents_margins(layout, 0, 0, 0, 0)
    _layout_rules.set_layout_spacing(layout, scale(4))
    title_label = QLabel(title)
    title_label.setObjectName("SectionTitle")
    count_label = QLabel("")
    count_label.setObjectName("MutedStatusLabel")
    count_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
    layout.addWidget(title_label)
    add_stretch(layout, 1)
    layout.addWidget(count_label)
    return (row, title_label, count_label)


import os
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QStyle
from runtime.shared.settings.config import APP_ICON_RELATIVE_PATH, LOGO_RELATIVE_PATH
from runtime.shared.assets import existing_asset_path

_APP_ICON_CANDIDATES: tuple[tuple[str, ...], ...] = (
    APP_ICON_RELATIVE_PATH,
    LOGO_RELATIVE_PATH,
)


def qt_file_image_loading_enabled() -> bool:
    try:
        app = QApplication.instance()
        platform_name = ""
        if app is not None and hasattr(app, "platformName"):
            platform_name = str(app.platformName() or "").lower()
        env_platform = str(os.environ.get("QT_QPA_PLATFORM", "") or "").lower()
        return platform_name not in {
            "offscreen",
            "minimal",
            "minimalegl",
        } and env_platform not in {"offscreen", "minimal", "minimalegl"}
    except UI_OPERATION_EXCEPTIONS:
        return False


def load_asset_icon(*parts: str, fallback_to_app: bool = False) -> QIcon:
    if not qt_file_image_loading_enabled():
        return app_icon() if fallback_to_app else QIcon()
    path = existing_asset_path(*parts)
    if path:
        icon = QIcon(path)
        if not icon.isNull():
            return icon
    return app_icon() if fallback_to_app else QIcon()


def app_icon() -> QIcon:
    for candidate in _APP_ICON_CANDIDATES:
        icon = load_asset_icon(*candidate, fallback_to_app=False)
        if not icon.isNull():
            return icon
    return QIcon()


def apply_application_icon(app: QApplication | None) -> None:
    if app is None:
        return
    try:
        icon = app_icon()
        if not icon.isNull():
            app.setWindowIcon(icon)
    except UI_OPERATION_EXCEPTIONS:
        return


def apply_window_icon(widget: Any) -> None:
    if widget is None or not hasattr(widget, "setWindowIcon"):
        return
    try:
        icon = app_icon()
        if not icon.isNull():
            widget.setWindowIcon(icon)
    except UI_OPERATION_EXCEPTIONS:
        return


def apply_button_icon(
    button: Any,
    icon_name: str,
    *,
    size: int | QSize | None = None,
    fallback_standard_icon: QStyle.StandardPixmap | None = None,
) -> None:
    if button is None:
        return
    try:
        icon = load_asset_icon("resources", "images", icon_name)
        if icon.isNull() and fallback_standard_icon is not None:
            style = button.style() if hasattr(button, "style") else None
            if style is not None:
                icon = style.standardIcon(fallback_standard_icon)
        if not icon.isNull() and hasattr(button, "setIcon"):
            button.setIcon(icon)
        if size is not None and hasattr(button, "setIconSize"):
            if isinstance(size, QSize):
                _layout_rules.set_button_icon_size(button, size)
            else:
                px = max(1, int(size))
                _layout_rules.set_button_icon_size(button, QSize(px, px))
    except UI_OPERATION_EXCEPTIONS:
        return


def set_menu_action_icon(action: Any, icon_name: str) -> None:
    if action is None:
        return
    try:
        icon = load_asset_icon("resources", "images", icon_name)
        if not icon.isNull() and hasattr(action, "setIcon"):
            action.setIcon(icon)
    except UI_OPERATION_EXCEPTIONS:
        return


def tray_icon_or_fallback(owner: Any) -> QIcon:
    icon = app_icon()
    if not icon.isNull():
        return icon
    try:
        if owner is not None and hasattr(owner, "style"):
            return owner.style().standardIcon(QStyle.SP_DesktopIcon)
    except UI_OPERATION_EXCEPTIONS:
        return QIcon()
    return QIcon()


from runtime.shared.objects import call_if_callable
from runtime.presentation.responsive import dispatch_reflow_callback, ensure_layout_mode_controller



def widget_alive(widget) -> bool:
    if widget is None:
        return False
    try:
        from PyQt5 import sip
    except ImportError:
        return True
    try:
        return not bool(sip.isdeleted(widget))
    except UI_OPERATION_EXCEPTIONS:
        return True


def should_refresh_widget(widget) -> bool:
    if not widget_alive(widget):
        return False
    try:
        if bool(getattr(widget, "_disposed", False)):
            return False
        is_visible = getattr(widget, "isVisible", None)
        return bool(is_visible()) if callable(is_visible) else True
    except UI_OPERATION_EXCEPTIONS:
        return False


class ControllerLifecycleMixin:

    def _on_destroyed(self, *_args) -> None:
        self._disposed = True
        try:
            bind_app_state = getattr(self, "bind_app_state", None)
            if callable(bind_app_state):
                call_if_callable(bind_app_state, None)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "ControllerLifecycleMixin._on_destroyed cleanup failed", exc_info=True
            )

    def _is_alive(self) -> bool:
        return widget_alive(self)

    def _should_refresh_now(self) -> bool:
        return should_refresh_widget(self)


class ResizeCallbackMixin:
    """Debounce resize callbacks and reflow only on layout-mode changes."""

    resize_callback_name = ""
    responsive_resize_interval_ms = 60

    def _ensure_resize_callback_controller(self):
        """Return the shared debounced resize controller for this widget."""
        controller = ensure_layout_mode_controller(
            self,
            attr_name="_resize_callback_mode_controller",
            interval_ms=int(getattr(self, "responsive_resize_interval_ms", 60)),
        )
        if not bool(getattr(self, "_resize_callback_mode_connected", False)):
            controller.reflowRequested.connect(
                self._on_resize_callback_reflow_requested
            )
            self._resize_callback_mode_connected = True
        return controller

    def _on_resize_callback_reflow_requested(self, mode, profile) -> None:
        """Dispatch the configured resize callback after debounce."""
        dispatch_reflow_callback(
            self,
            str(self.resize_callback_name or ""),
            mode=str(mode or ""),
            profile=profile,
            force=True,
        )

    def resizeEvent(self, event):
        """Schedule an adaptive resize callback instead of reflowing per pixel."""
        super().resizeEvent(event)
        self._ensure_resize_callback_controller().schedule()

    def showEvent(self, event):
        """Force one callback after the widget receives a real visible size."""
        super().showEvent(event)
        self._ensure_resize_callback_controller().schedule(force=True)





def _safe_common_ui(action: Callable[[], None], message: str) -> None:
    try:
        action()
    except UI_OPERATION_EXCEPTIONS:
        logger.debug(message, exc_info=True)


def refresh_widget_style(widget: QWidget) -> None:
    if widget is None:
        return

    def _apply_refresh_widget_style() -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    _safe_common_ui(_apply_refresh_widget_style, "refresh_widget_style fallback failed")


from PyQt5.QtCore import QPoint, QTimer
from runtime.presentation.layout.profiles import profile_for_widget
from runtime.presentation.layout.fitting import clamp_size_to_screen



def apply_dialog_basics(
    dialog: Any,
    *,
    object_name: str | None = None,
    modal: bool | None = None,
    size_grip: bool | None = None,
    rtl: bool | None = None,
) -> None:
    if dialog is None:
        return
    try:
        if object_name and hasattr(dialog, "setObjectName"):
            dialog.setObjectName(str(object_name))
        set_dialog_app_icon(dialog)
        if hasattr(dialog, "windowFlags") and hasattr(dialog, "setWindowFlags"):
            dialog.setWindowFlags(
                dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint
            )
        if hasattr(dialog, "setProperty"):
            dialog.setProperty("modernDialog", True)
            dialog.setProperty("popupContract", "responsive_visual_qa")
            apply_profile_properties(dialog, profile_for_widget(dialog))
        if modal is not None and hasattr(dialog, "setModal"):
            dialog.setModal(bool(modal))
        if size_grip is not None and hasattr(dialog, "setSizeGripEnabled"):
            dialog.setSizeGripEnabled(bool(size_grip))
        if hasattr(dialog, "setLayoutDirection"):
            if rtl is not None:
                dialog.setLayoutDirection(direction_for_rtl(bool(rtl)))
            else:
                parent = (
                    dialog.parentWidget() if hasattr(dialog, "parentWidget") else None
                )
                if parent is not None and hasattr(parent, "layoutDirection"):
                    dialog.setLayoutDirection(parent.layoutDirection())
        if hasattr(dialog, "setMinimumSize"):
            size = clamp_size_to_screen(QSize(360, 240), padding=32)
            dialog.setMinimumSize(size.width(), size.height())
        QTimer.singleShot(0, lambda: center_dialog_over_parent(dialog))
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Applying dialog basics failed", exc_info=True)


def set_dialog_app_icon(dialog: Any) -> None:
    try:
        apply_window_icon(dialog)
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Applying dialog app icon failed", exc_info=True)


def _available_screen_geometry(dialog: Any):
    app = QApplication.instance()
    if app is None:
        return None
    parent = (
        dialog.parentWidget()
        if dialog is not None and hasattr(dialog, "parentWidget")
        else None
    )
    anchor = None
    if parent is not None and hasattr(parent, "frameGeometry"):
        try:
            anchor = parent.frameGeometry().center()
        except UI_OPERATION_EXCEPTIONS:
            anchor = None
    if anchor is None and dialog is not None and hasattr(dialog, "frameGeometry"):
        try:
            anchor = dialog.frameGeometry().center()
        except UI_OPERATION_EXCEPTIONS:
            anchor = None
    screen = (
        app.screenAt(anchor)
        if anchor is not None and hasattr(app, "screenAt")
        else None
    )
    if screen is None:
        screen = app.primaryScreen()
    return screen.availableGeometry() if screen is not None else None


def _effective_dialog_ratios(
    name: str, width_ratio: float, height_ratio: float
) -> tuple[float, float]:
    caps = {
        "compact": (0.96, 0.92),
        "tablet_portrait": (0.9, 0.88),
        "tablet_landscape": (0.82, 0.78),
        "desktop": (0.62, 0.68),
        "wide": (0.58, 0.64),
    }
    cap_w, cap_h = caps.get(str(name or "desktop"), (0.62, 0.68))
    if name in {"desktop", "wide"}:
        return (min(width_ratio, cap_w), min(height_ratio, cap_h))
    return (max(width_ratio, cap_w), max(height_ratio, cap_h))


def fit_dialog(
    dialog: Any,
    width_ratio: float,
    height_ratio: float,
    *,
    min_width: int = 360,
    min_height: int = 240,
    max_width: int | None = None,
    max_height: int | None = None,
    padding: int = 24,
) -> None:
    apply_popup_contract(
        dialog,
        width_ratio=width_ratio,
        height_ratio=height_ratio,
        min_width=min_width,
        min_height=min_height,
        max_width=max_width,
        max_height=max_height,
        padding=padding,
    )


def _popup_contract_size(
    dialog: Any,
    width_ratio: float,
    height_ratio: float,
    *,
    min_width: int,
    min_height: int,
    max_width: int | None,
    max_height: int | None,
    padding: int,
    constrain_to_parent: bool,
) -> QSize:
    """Resolve size from the active monitor without exceeding its work area."""
    app = QApplication.instance()
    bounds = _available_screen_geometry(dialog)
    if bounds is None:
        return clamp_size_to_screen(
            QSize(max(360, min_width), max(240, min_height)),
            padding=padding,
            app=app,
        )

    profile = profile_for_dimensions(bounds.width(), bounds.height(), app=app)
    width_ratio, height_ratio = _effective_dialog_ratios(
        profile.name, float(width_ratio), float(height_ratio)
    )
    safe_width = max(320, bounds.width() - int(padding))
    safe_height = max(240, bounds.height() - int(padding))
    effective_min_width = min(max(320, int(min_width)), safe_width)
    effective_min_height = min(max(240, int(min_height)), safe_height)
    effective_max_width = safe_width
    effective_max_height = safe_height
    if max_width is not None:
        effective_max_width = min(effective_max_width, max(320, int(max_width)))
    if max_height is not None:
        effective_max_height = min(effective_max_height, max(240, int(max_height)))

    target_width = max(effective_min_width, int(round(bounds.width() * width_ratio)))
    target_height = max(
        effective_min_height, int(round(bounds.height() * height_ratio))
    )
    size = QSize(
        min(target_width, effective_max_width),
        min(target_height, effective_max_height),
    )

    parent = dialog.parentWidget() if hasattr(dialog, "parentWidget") else None
    if constrain_to_parent and parent is not None and hasattr(parent, "frameGeometry"):
        try:
            parent_frame = parent.frameGeometry()
            parent_safe_width = max(320, parent_frame.width() - int(padding))
            parent_safe_height = max(240, parent_frame.height() - int(padding))
            size.setWidth(min(size.width(), parent_safe_width, safe_width))
            size.setHeight(min(size.height(), parent_safe_height, safe_height))
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Parent-aware popup contract fit failed", exc_info=True)
    return size


def apply_popup_contract(
    dialog: Any,
    *,
    object_name: str | None = None,
    modal: bool | None = True,
    size_grip: bool | None = False,
    width_ratio: float = 0.34,
    height_ratio: float = 0.26,
    min_width: int = 360,
    min_height: int = 220,
    max_width: int | None = 720,
    max_height: int | None = 520,
    padding: int = 28,
    constrain_to_parent: bool = True,
) -> None:
    """Apply the unified responsive popup/dialog contract.

    All user-facing popups pass through this helper so update prompts, busy
    indicators, message boxes, and form dialogs share sizing, centering, app
    icon, RTL, and screen-clamping behavior.
    """
    apply_dialog_basics(
        dialog, object_name=object_name, modal=modal, size_grip=size_grip
    )
    try:
        if dialog is None or not hasattr(dialog, "resize"):
            return
        size = _popup_contract_size(
            dialog,
            width_ratio,
            height_ratio,
            min_width=min_width,
            min_height=min_height,
            max_width=max_width,
            max_height=max_height,
            padding=padding,
            constrain_to_parent=constrain_to_parent,
        )
        dialog.resize(size)
        apply_profile_properties(
            dialog,
            profile_for_dimensions(
                int(size.width()), int(size.height()), app=QApplication.instance()
            ),
        )
        center_dialog_over_parent(dialog)
        if hasattr(dialog, "setProperty"):
            dialog.setProperty("popupContract", "responsive_visual_qa")
            refresh_widget_style(dialog)
        labels = dialog.findChildren(QLabel) if hasattr(dialog, "findChildren") else []
        for label in labels:
            label.setWordWrap(True)
            if not str(label.toolTip() or "").strip():
                label.setToolTip(" ".join(str(label.text() or "").split()))
        QTimer.singleShot(0, lambda: center_dialog_over_parent(dialog))
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Applying responsive popup contract failed", exc_info=True)


def center_dialog_over_parent(dialog: Any) -> None:
    if dialog is None or not hasattr(dialog, "move"):
        return
    try:
        frame = dialog.frameGeometry() if hasattr(dialog, "frameGeometry") else None
        if frame is None:
            return
        parent = dialog.parentWidget() if hasattr(dialog, "parentWidget") else None
        bounds = _available_screen_geometry(dialog)
        anchor = None
        if parent is not None and hasattr(parent, "frameGeometry"):
            anchor = parent.frameGeometry()
        elif bounds is not None:
            anchor = bounds
        if anchor is None:
            return
        target = anchor.center() - frame.center()
        if bounds is not None:
            x = max(bounds.left(), min(target.x(), bounds.right() - frame.width() + 1))
            y = max(bounds.top(), min(target.y(), bounds.bottom() - frame.height() + 1))
            target = QPoint(x, y)
        dialog.move(target)
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Centering dialog failed", exc_info=True)


from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QMessageBox, QAbstractItemView
from runtime.shared.settings.config import resource_path
from runtime.shared.settings.messages import user_error_message
from runtime.shared.feedback import normalize_feedback_severity
from runtime.presentation.theme import theme_color

NOTICE_PALETTES: dict[str, dict[str, str]] = {
    name: {
        "border": theme_color(f"notice_{name}_border"),
        "background": theme_color(f"notice_{name}_bg"),
        "color": theme_color(f"notice_{name}_text"),
    }
    for name in ("info", "success", "warning", "danger", "neutral", "muted")
}
_NOTICE_SEVERITIES = frozenset(NOTICE_PALETTES)


def _normalize_notice_severity(severity: str | None) -> str:
    normalized = normalize_feedback_severity(severity)
    return normalized if normalized in _NOTICE_SEVERITIES else "info"


def build_logo_label(
    *,
    width: int,
    height: int | None = None,
    object_name: str = "",
    ui_role: str = "logoMissing",
    alignment: int = Qt.AlignCenter,
) -> QLabel:
    label = QLabel()
    if object_name:
        label.setObjectName(object_name)
    logo_path = resource_path(*LOGO_RELATIVE_PATH)
    target_height = int(height if height is not None else width)
    if not qt_file_image_loading_enabled():
        label.setText("HERFY")
        label.setProperty("uiRole", ui_role)
    else:
        pixmap = QPixmap(logo_path)
        if pixmap.isNull():
            label.setText(_("Logo Not Found"))
            label.setProperty("uiRole", ui_role)
        else:
            label.setPixmap(
                pixmap.scaled(
                    int(width),
                    target_height,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
    label.setAlignment(alignment)
    return label


def confirm_delete(parent: QWidget | None, thing_label: str = "") -> bool:
    prompt = f"{_('Delete')} {str(thing_label or '').strip()}?".strip()
    return show_question_message(
        parent, _("Confirm Delete"), prompt, default_no=True, danger=True
    )


def _style_message_buttons(box: QMessageBox, *, danger: bool = False) -> None:

    def _apply_style_message_buttons() -> None:
        for button in box.buttons():
            role = box.buttonRole(button)
            is_accept = role in (
                QMessageBox.AcceptRole,
                QMessageBox.YesRole,
                QMessageBox.ApplyRole,
            )
            polish_button(
                button,
                role=(
                    "danger"
                    if danger and is_accept
                    else "primary" if is_accept else "secondary"
                ),
            )
            refresh_widget_style(button)

    _safe_common_ui(
        _apply_style_message_buttons, "_style_message_buttons fallback failed"
    )


def _styled_message_box(
    parent: QWidget | None, icon: QMessageBox.Icon, title: str, message: str
) -> QMessageBox:
    box = QMessageBox(parent)
    apply_popup_contract(
        box,
        object_name="AppMessageBox",
        modal=True,
        width_ratio=0.34,
        height_ratio=0.24,
        min_width=380,
        min_height=180,
        max_width=760,
        max_height=420,
    )
    box.setIcon(icon)
    box.setWindowTitle(str(title or ""))
    box.setText(str(message or ""))
    box.setStandardButtons(QMessageBox.Ok)

    def _apply_message_box_direction() -> None:
        direction = parent.layoutDirection() if parent is not None else Qt.LeftToRight
        box.setLayoutDirection(direction)

    _safe_common_ui(
        _apply_message_box_direction, "_styled_message_box layout direction failed"
    )
    _style_message_buttons(box)
    return box


def _show_inline_runtime_message(
    parent: QWidget | None, title: str, message: str, *, duration_ms: int = 4500
) -> bool:
    """Prefer non-blocking main-window status feedback over modal popups.

    Confirmation dialogs still use QMessageBox.  Informational/warning/error
    feedback should not freeze the UI or create the small black popup effect.
    """
    text = " — ".join(
        (
            part
            for part in (str(title or "").strip(), str(message or "").strip())
            if part
        )
    )
    if not text:
        return True
    candidates = []
    if parent is not None:
        candidates.append(parent)
        try:
            window = parent.window()
            if window is not parent:
                candidates.append(window)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug(
                "Unable to resolve parent window for feedback delivery", exc_info=True
            )
    app = QApplication.instance()
    if app is not None:
        try:
            active = app.activeWindow()
            if active is not None:
                candidates.append(active)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.debug("Unable to resolve active feedback window", exc_info=True)
    for candidate in candidates:
        try:
            handler = getattr(candidate, "_show_runtime_status_message", None)
            if callable(handler):
                handler(text, int(duration_ms))
                return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
    return False


def show_info_message(parent: QWidget | None, title: str, message: str) -> None:
    """Show informational feedback without blocking the main UI."""
    if _show_inline_runtime_message(parent, title, message, duration_ms=3500):
        return
    _styled_message_box(parent, QMessageBox.Information, title, message).exec_()


def show_warning_message(parent: QWidget | None, title: str, message: str) -> None:
    """Show warning feedback inline when a main shell is available."""
    if _show_inline_runtime_message(parent, title, message, duration_ms=5000):
        return
    _styled_message_box(parent, QMessageBox.Warning, title, message).exec_()


def show_error_message(parent: QWidget | None, title: str, message: str) -> None:
    """Show recoverable error feedback inline when possible."""
    display_message = user_error_message(message, context="general")
    if _show_inline_runtime_message(parent, title, display_message, duration_ms=6500):
        return
    _styled_message_box(parent, QMessageBox.Critical, title, display_message).exec_()


def show_question_message(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    default_no: bool = True,
    danger: bool = False,
) -> bool:
    box = _styled_message_box(parent, QMessageBox.Question, title, message)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No if default_no else QMessageBox.Yes)
    _style_message_buttons(box, danger=danger)
    return box.exec_() == QMessageBox.Yes


def _resolve_notice_palette(severity: str | None) -> dict[str, str]:
    return dict(
        NOTICE_PALETTES.get(
            _normalize_notice_severity(severity), NOTICE_PALETTES["info"]
        )
    )


def build_notice_stylesheet(
    *,
    severity: str = "info",
    border: str | None = None,
    background: str | None = None,
    color: str | None = None,
    radius: int = 10,
    padding: int = 8,
    font_weight: int | None = None,
) -> str:
    palette = _resolve_notice_palette(severity)
    declarations = [
        f"border:1px solid {border or palette['border']}",
        f"background:{background or palette['background']}",
        f"color:{color or palette['color']}",
        f"border-radius:{int(radius)}px",
        f"padding:{int(padding)}px",
    ]
    if font_weight is not None:
        declarations.append(f"font-weight:{int(font_weight)}")
    return ";".join(declarations) + ";"


def apply_notice_style(widget: QWidget, **kwargs) -> None:
    severity = _normalize_notice_severity(kwargs.get("severity"))

    def _apply_notice_theme_properties() -> None:
        widget.setObjectName(widget.objectName() or "NoticeLabel")
        widget.setProperty("notice", True)
        widget.setProperty("noticeSeverity", severity)
        widget.setProperty("uiRole", "notice")
        refresh_widget_style(widget)

    try:
        _apply_notice_theme_properties()
    except UI_OPERATION_EXCEPTIONS:
        widget.setStyleSheet(build_notice_stylesheet(**kwargs))


def configure_modern_table(
    table: QWidget, *, window_width: int | None = None
) -> dict[str, int | str | bool]:
    from runtime.presentation.tables.metrics import apply_table_metrics

    metrics = apply_table_metrics(table, window_width)

    def _apply_modern_table() -> None:
        if not table.objectName():
            table.setObjectName("ModernTable")
        table.setProperty("uiRole", "dataTable")
        table.setProperty(
            "tableDensity",
            "compact" if metrics.get("device_class") == "compact" else "regular",
        )
        call_if_supported(table, "setSelectionBehavior", QAbstractItemView.SelectRows)
        call_if_supported(table, "setSelectionMode", QAbstractItemView.SingleSelection)
        call_if_supported(table, "setTextElideMode", Qt.ElideRight)
        viewport = getattr(table, "viewport", lambda: None)()
        if viewport is not None:
            viewport.setProperty("uiRole", "tableViewport")
            refresh_widget_style(viewport)
        refresh_widget_style(table)

    _safe_common_ui(_apply_modern_table, "configure_modern_table fallback failed")
    return metrics


class DialogFeedbackMixin:

    def _feedback(self, level: str, title: str, message: str):
        if level == "warning":
            return self._show_warning_message(title, message)
        if level == "error":
            return self._show_error_message(title, message)
        if level == "question":
            return self._show_question_message(title, message)
        return self._show_info_message(title, message)

    def _show_warning_message(self, title: str, message: str) -> None:
        show_warning_message(self, str(title or ""), str(message or ""))

    def _show_info_message(self, title: str, message: str) -> None:
        show_info_message(self, str(title or ""), str(message or ""))

    def _show_error_message(self, title: str, message: str) -> None:
        show_error_message(self, str(title or ""), str(message or ""))

    def _show_question_message(self, title: str, message: str) -> bool:
        return bool(show_question_message(self, str(title or ""), str(message or "")))

    def _warn(self, title: str, message: str) -> None:
        self._show_warning_message(title, message)

    def _info(self, title: str, message: str) -> None:
        self._show_info_message(title, message)

    def _error(self, title: str, message: str) -> None:
        self._show_error_message(title, message)

    def _confirm(self, title: str, message: str) -> bool:
        return self._show_question_message(title, message)
