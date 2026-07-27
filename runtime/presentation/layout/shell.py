from __future__ import annotations
import logging
from PyQt5.QtCore import QSettings, QSize, Qt
from PyQt5.QtWidgets import QApplication, QSizePolicy
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.presentation.responsive import layout_mode_for_width
from .contract import enforce_layout_contract
from .fitting import fit_window_size
from .helpers import set_icon_box_size, set_size_policy
from .metrics import UI_METRICS
from .profiles import (
    ResponsiveProfile,
    apply_profile_properties,
    apply_screen_device_properties,
    profile_for_dimensions,
    screen_device_profile,
)
from .screen import active_screen_geometry

logger = logging.getLogger(__name__)


def apply_initial_window_geometry(window) -> None:
    try:
        app = QApplication.instance()
        geometry = active_screen_geometry(window, app)
        screen_width = (
            geometry.width()
            if geometry is not None
            else UI_METRICS.app_window_fallback_width
        )
        screen_height = (
            geometry.height()
            if geometry is not None
            else UI_METRICS.app_window_fallback_height
        )
        min_window_width = min(
            UI_METRICS.app_window_min_width, max(900, screen_width - 24)
        )
        min_window_height = min(
            UI_METRICS.app_window_min_height, max(560, screen_height - 24)
        )
        window.setMinimumSize(min_window_width, min_window_height)
        settings = QSettings()
        saved = settings.value("window/main_normal_geometry")
        restored = bool(saved) and bool(window.restoreGeometry(saved))
        window.setWindowState(
            window.windowState() & ~Qt.WindowMaximized & ~Qt.WindowFullScreen
        )
        compact_max_width = max(760, min(screen_width - 30, int(screen_width * 0.955)))
        compact_max_height = max(
            min(UI_METRICS.app_window_min_height, max(430, screen_height - 72)),
            min(screen_height - 34, int(screen_height * 0.92)),
        )
        preferred_size = fit_window_size(
            width_ratio=0.94,
            height_ratio=0.89,
            min_width=min_window_width,
            min_height=min_window_height,
            max_width=compact_max_width,
            max_height=compact_max_height,
            app=app,
        )
        if restored:
            current_width = max(1, int(window.width()))
            current_height = max(1, int(window.height()))
            needs_resize = (
                current_width < int(preferred_size.width() * 0.92)
                or current_height < int(preferred_size.height() * 0.92)
                or current_width > compact_max_width
                or (current_height > compact_max_height)
            )
            if needs_resize:
                size = QSize(
                    min(max(current_width, preferred_size.width()), compact_max_width),
                    min(
                        max(current_height, preferred_size.height()), compact_max_height
                    ),
                )
                window.resize(size)
                if geometry is not None:
                    window.move(
                        geometry.x() + max(0, (geometry.width() - size.width()) // 2),
                        geometry.y() + max(0, (geometry.height() - size.height()) // 2),
                    )
        if not restored:
            window.resize(preferred_size)
            if geometry is not None:
                window.move(
                    geometry.x()
                    + max(0, (geometry.width() - preferred_size.width()) // 2),
                    geometry.y()
                    + max(0, (geometry.height() - preferred_size.height()) // 2),
                )
    except UI_OPERATION_EXCEPTIONS:
        window.resize(
            UI_METRICS.app_window_fallback_width, UI_METRICS.app_window_fallback_height
        )


def save_normal_window_geometry(window) -> None:
    try:
        if window.isMaximized() or window.isFullScreen():
            return
        QSettings().setValue("window/main_normal_geometry", window.saveGeometry())
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Failed to save normal main-window geometry", exc_info=True)


def _full_text(button) -> str:
    return str(button.property("fullText") or button.text() or "")


def _refresh_sidebar(window, profile: ResponsiveProfile, *, is_rtl: bool) -> None:
    """Refresh sidebar chrome without changing the navigation structure.

    The customer reference design keeps a readable left navigation at every
    supported desktop width.  Manual resize must not turn the sidebar into a
    rail or move navigation elements elsewhere; if the window reaches the
    minimum production width the OS stops further shrinking instead of the UI
    changing shape.
    """
    mode = "regular"
    width = int(UI_METRICS.sidebar_width)
    sidebar = getattr(window, "sidebar", None)
    if sidebar is not None:
        apply_profile_properties(sidebar, profile)
        sidebar.setProperty("layoutMode", mode)
        sidebar.setProperty("railMode", False)
        sidebar.setMinimumWidth(width)
        sidebar.setBaseSize(width, 0)
        set_size_policy(sidebar, QSizePolicy.Fixed, QSizePolicy.Expanding)
    logo = getattr(window, "sidebar_logo", None)
    if logo is not None:
        set_icon_box_size(logo, 36 if profile.is_tablet else 40)
    for name in ("sidebar_brand_title", "sidebar_brand_subtitle"):
        label = getattr(window, name, None)
        if label is not None:
            label.setVisible(True)
            label.setTextInteractionFlags(Qt.NoTextInteraction)
            label.setProperty("elideMode", "right")
    for button in list(getattr(window, "sidebar_buttons", []) or []):
        text = _full_text(button)
        button.setProperty("fullText", text)
        button.setProperty("railMode", False)
        button.setProperty("layoutMode", mode)
        button.setProperty("rtlUi", bool(is_rtl))
        button.setText(text)
        button.setToolTip(text)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIconSize(
            QSize(
                15 if not profile.touch_mode else 18,
                15 if not profile.touch_mode else 18,
            )
        )
        button.setMinimumHeight(
            profile.touch_target
            if profile.touch_mode
            else max(24, profile.control_height)
        )
        button.setMinimumWidth(0)
        set_size_policy(button, QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.style().unpolish(button)
        button.style().polish(button)


def _refresh_topbar(window, profile: ResponsiveProfile) -> None:
    """Refresh topbar controls without hard max-width clipping."""
    mode = layout_mode_for_width(profile.width)
    compact_topbar = mode == "compact"
    regular_topbar = mode == "regular"
    very_compact_topbar = profile.width < 940
    top_bar = getattr(window, "top_bar", None)
    if top_bar is not None:
        apply_profile_properties(top_bar, profile)
        top_bar.setProperty("layoutMode", mode)
        top_bar.setMinimumHeight(30 if compact_topbar else 32 if regular_topbar else 34)
        set_size_policy(top_bar, QSizePolicy.Expanding, QSizePolicy.Fixed)
    for name in ("btn_menu_file", "btn_menu_tools"):
        button = getattr(window, name, None)
        if button is None:
            continue
        text = _full_text(button)
        button.setProperty("fullText", text)
        button.setProperty("layoutMode", mode)
        button.setToolTip(text)
        if name.startswith("btn_menu_"):
            button.setText(text)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setMinimumWidth(0)
            set_size_policy(button, QSizePolicy.Minimum, QSizePolicy.Fixed)
        else:
            icon_only = compact_topbar or regular_topbar
            button.setText("" if icon_only else text)
            button.setToolButtonStyle(
                Qt.ToolButtonIconOnly if icon_only else Qt.ToolButtonTextBesideIcon
            )
            button.setMinimumWidth(profile.touch_target if icon_only else 0)
            set_size_policy(
                button,
                QSizePolicy.Minimum if icon_only else QSizePolicy.Preferred,
                QSizePolicy.Fixed,
            )
        button.setIconSize(
            QSize(18 if profile.touch_mode else 16, 18 if profile.touch_mode else 16)
        )
        button.setMinimumHeight(profile.control_height)
        button.style().unpolish(button)
        button.style().polish(button)
    notifications = getattr(window, "btn_notifications", None)
    if notifications is not None:
        text = _full_text(notifications) or str(notifications.toolTip() or "")
        notifications.setText("")
        notifications.setToolTip(text)
        notifications.setToolButtonStyle(Qt.ToolButtonIconOnly)
        notifications.setMinimumHeight(
            profile.touch_target
            if profile.touch_mode
            else max(24, profile.control_height)
        )
        notifications.setMinimumWidth(profile.touch_target)
        set_size_policy(notifications, QSizePolicy.Minimum, QSizePolicy.Fixed)
    notif_wrap = getattr(window, "notif_wrap", None)
    if notif_wrap is not None:
        notif_wrap.setMinimumWidth(
            profile.touch_target if compact_topbar or regular_topbar else 0
        )
        set_size_policy(notif_wrap, QSizePolicy.Minimum, QSizePolicy.Fixed)
    title_block = getattr(window, "topbar_title_block", None)
    if title_block is not None:
        title_block.setVisible(False)
    user_label = getattr(window, "lbl_user_info", None)
    if user_label is not None:
        user_label.setVisible(not very_compact_topbar)
        user_label.setMinimumWidth(0)
        user_label.setTextInteractionFlags(Qt.NoTextInteraction)
        set_size_policy(user_label, QSizePolicy.Preferred, QSizePolicy.Fixed)


def apply_device_properties(
    widget, window_width: int | None = None, app=None, window_height: int | None = None
) -> str:
    profile = profile_for_dimensions(window_width, window_height, app=app)
    if widget is not None:
        apply_profile_properties(widget, profile)
    return (
        "compact"
        if profile.is_narrow
        else "comfortable" if profile.is_tablet else "expanded"
    )


def apply_responsive_shell_metrics(window) -> None:
    try:
        app = QApplication.instance()
        profile = profile_for_dimensions(window.width(), window.height(), app=app)
        is_rtl = window.layoutDirection() == Qt.RightToLeft
        apply_profile_properties(window, profile)
        apply_screen_device_properties(window, screen_device_profile(window, app=app))
        window.setProperty("rtlUi", bool(is_rtl))
        central = window.centralWidget()
        if central is not None:
            apply_profile_properties(central, profile)
            apply_screen_device_properties(
                central, screen_device_profile(window, app=app)
            )
            central.setProperty("rtlUi", bool(is_rtl))
        _refresh_sidebar(window, profile, is_rtl=is_rtl)
        _refresh_topbar(window, profile)
        content_layout = getattr(window, "content_layout", None)
        if content_layout is not None:
            content_layout.setContentsMargins(
                profile.page_margin,
                profile.page_margin,
                profile.page_margin,
                profile.page_margin,
            )
        status = getattr(window, "shell_status_bar", None)
        if status is not None:
            apply_profile_properties(status, profile)
            status.setMinimumHeight(
                20
                if profile.visual_breakpoint == "small_terminal"
                else (
                    22
                    if profile.visual_breakpoint == "hd_720"
                    else 26 if profile.touch_mode else 22
                )
            )
        enforce_layout_contract(central, profile)
        current_page = (
            window.content_stack.currentWidget()
            if getattr(window, "content_stack", None) is not None
            else None
        )
        if current_page is not None:
            apply_profile_properties(current_page, profile)
            current_page.setProperty("rtlUi", bool(is_rtl))
            callback = getattr(current_page, "apply_responsive_profile", None)
            if callable(callback):
                callback(profile)
            enforce_layout_contract(current_page, profile)
        apply_device_properties(window, window.width(), app, window.height())
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Failed to apply responsive shell metrics", exc_info=True)
