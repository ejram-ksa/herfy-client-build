from __future__ import annotations
from runtime.presentation.layout import helpers as _layout_rules
import logging
from PyQt5.QtCore import Qt
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from PyQt5.QtWidgets import QPushButton, QWidget
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)
from runtime.presentation.layout.metrics import UI_METRICS
from runtime.presentation.widgets import apply_button_icon
from runtime.presentation.widgets import build_logo_label
from runtime.presentation.layout.helpers import (
    add_stretch,
    set_badge_size,
    set_minimum_height,
    set_minimum_width,
    set_size_policy,
)

logger = logging.getLogger(__name__)


def show_runtime_notice(
    owner, notice, *, logger_: logging.Logger, context: str
) -> None:
    if not getattr(notice, "text", ""):
        return
    try:
        owner._show_runtime_status_message(notice.text, notice.timeout_ms)
    except UI_OPERATION_EXCEPTIONS:
        logger_.debug("%s status fallback failed", context, exc_info=True)


def create_sidebar_button(
    window,
    text: str,
    icon_name: str,
    handler,
    *,
    page_button: bool = False,
    exit_button: bool = False,
    route_name: str | None = None,
) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("SidebarButton")
    button.setProperty("fullText", text)
    button.setCursor(Qt.PointingHandCursor)
    button.setProperty("pageButton", bool(page_button))
    button.setProperty("isExitButton", bool(exit_button))
    if route_name:
        button.setProperty("routeName", str(route_name))
    icon_px = window._scaled(UI_METRICS.icon_size)
    apply_button_icon(button, icon_name, size=QSize(icon_px, icon_px))
    button.setAccessibleName(text)
    button.setCheckable(True)
    button.clicked.connect(
        lambda checked, btn=button, fn=handler: window.handle_sidebar_click(btn, fn)
    )
    return button


def build_sidebar(window, parent_layout: QHBoxLayout) -> None:
    window.sidebar = QFrame()
    window.sidebar.setObjectName("Sidebar")
    set_size_policy(window.sidebar, QSizePolicy.Fixed, QSizePolicy.Expanding)
    sidebar_width = window._scaled(int(UI_METRICS.sidebar_width))
    set_minimum_width(window.sidebar, sidebar_width)
    window.sidebar.setBaseSize(sidebar_width, 0)
    parent_layout.addWidget(window.sidebar)
    side_layout = QVBoxLayout(window.sidebar)
    _layout_rules.set_layout_contents_margins(
        side_layout,
        window._scaled(8),
        window._scaled(10),
        window._scaled(8),
        window._scaled(8),
    )
    _layout_rules.set_layout_spacing(side_layout, window._scaled(4))
    logo_size = window._scaled(40)
    logo = build_logo_label(
        width=logo_size, object_name="SidebarLogo", ui_role="logoMissingSidebar"
    )
    _layout_rules.set_layout_contents_margins(logo, 4, 4, 4, 2)
    logo.setAttribute(Qt.WA_StyledBackground, False)
    window.sidebar_logo = logo
    side_layout.addWidget(logo, 0, Qt.AlignHCenter | Qt.AlignTop)
    brand_title = QLabel("HERFY")
    brand_title.setObjectName("SidebarBrandTitle")
    brand_title.setAlignment(Qt.AlignCenter)
    window.sidebar_brand_title = brand_title
    side_layout.addWidget(brand_title)
    brand_subtitle = QLabel(_("Herfy Product\nTracking System"))
    brand_subtitle.setObjectName("SidebarBrandSubtitle")
    brand_subtitle.setAlignment(Qt.AlignCenter)
    brand_subtitle.setWordWrap(True)
    window.sidebar_brand_subtitle = brand_subtitle
    side_layout.addWidget(brand_subtitle)
    side_layout.addSpacing(window._scaled(6))
    window.sidebar_buttons = []
    window.sidebar_page_buttons = []
    window.btn_org_sidebar = None
    window.btn_settings_sidebar = None
    window.sidebar_buttons_info = [
        (_("Home"), "home.png", window.show_home, "home"),
        (_("Track Products"), "products.png", window.show_track, "tracking"),
        (_("Usage"), "usage.png", window.show_usage, "usage"),
        (_("Control Panel"), "admin.png", window.open_admin_dashboard, "admin"),
        (_("About"), "about.png", window.show_about, "about"),
    ]
    sidebar_shortcuts = {
        "home": "Alt+1",
        "tracking": "Alt+2",
        "usage": "Alt+3",
        "admin": "Alt+4",
        "about": "Alt+5",
    }
    for text, icon_name, handler, route_name in window.sidebar_buttons_info:
        button = create_sidebar_button(
            window, text, icon_name, handler, page_button=True, route_name=route_name
        )
        shortcut = sidebar_shortcuts.get(route_name)
        if shortcut:
            button.setShortcut(shortcut)
            button.setToolTip(f"{text} ({shortcut})")
        side_layout.addWidget(button)
        if route_name == "admin":
            window.btn_org_sidebar = button
        if route_name == "settings":
            window.btn_settings_sidebar = button
        window.sidebar_page_buttons.append(button)
        window.sidebar_buttons.append(button)
    add_stretch(side_layout, 1)
    window.sidebar_footer = QFrame()
    window.sidebar_footer.setObjectName("SidebarFooter")
    set_size_policy(window.sidebar_footer, QSizePolicy.Preferred, QSizePolicy.Minimum)
    footer_layout = QVBoxLayout(window.sidebar_footer)
    _layout_rules.set_layout_contents_margins(footer_layout, 0, 6, 0, 0)
    _layout_rules.set_layout_spacing(footer_layout, 4)
    window.btn_exit_sidebar = create_sidebar_button(
        window,
        _("Exit"),
        "exit.png",
        getattr(window, "close_app_completely", window.close),
        exit_button=True,
        route_name="exit",
    )
    footer_layout.addWidget(window.btn_exit_sidebar)
    window.sidebar_buttons.append(window.btn_exit_sidebar)
    side_layout.addWidget(window.sidebar_footer)


def _make_top_bar_button(
    window,
    text: str,
    handler_name: str,
    standard_icon=None,
    shortcut: str | None = None,
    icon_name: str | None = None,
) -> QToolButton:
    button = QToolButton()
    button.setObjectName("TopBarActionButton")
    button.setCursor(Qt.PointingHandCursor)
    button.setText(text)
    button.setProperty("fullText", text)
    button.setAccessibleName(text)
    if shortcut:
        button.setShortcut(shortcut)
        button.setToolTip(f"{text} ({shortcut})")
    else:
        button.setToolTip(text)
    icon_px = window._scaled(max(UI_METRICS.icon_size + 1, 18))
    button.setText(text)
    if icon_name:
        apply_button_icon(
            button,
            icon_name,
            size=QSize(icon_px, icon_px),
            fallback_standard_icon=standard_icon,
        )
    elif standard_icon is not None:
        apply_button_icon(
            button,
            "",
            size=QSize(icon_px, icon_px),
            fallback_standard_icon=standard_icon,
        )
    button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    button.setAccessibleName(text)
    button.setToolTip(text)
    set_minimum_height(button, window._scaled(28))
    set_minimum_width(button, window._scaled(72))
    handler = getattr(window, handler_name, None)
    if callable(handler):
        button.clicked.connect(handler)
    return button


def _make_top_menu_button(
    window, text: str, icon_name: str | None = None
) -> QToolButton:
    button = QToolButton()
    button.setObjectName("TopMenuButton")
    button.setCursor(Qt.PointingHandCursor)
    button.setText(text)
    button.setProperty("fullText", text)
    button.setPopupMode(QToolButton.InstantPopup)
    button.setToolButtonStyle(Qt.ToolButtonTextOnly)
    button.setAccessibleName(text)
    button.setToolTip(text)
    button.setText(text)
    if icon_name:
        icon_px = window._scaled(max(UI_METRICS.icon_size, 18))
        apply_button_icon(button, icon_name, size=QSize(icon_px, icon_px))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    button.setText(text)
    set_minimum_height(button, window._scaled(28))
    set_minimum_width(button, window._scaled(48))
    return button


def build_top_bar(window) -> QWidget:
    top_bar = QWidget()
    top_bar.setObjectName("TopBar")
    top_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    set_minimum_height(top_bar, window._scaled(36))
    top_bar.setLayoutDirection(window.layoutDirection())
    top_layout = QHBoxLayout(top_bar)
    _layout_rules.set_layout_contents_margins(
        top_layout,
        window._scaled(10),
        window._scaled(4),
        window._scaled(10),
        window._scaled(4),
    )
    _layout_rules.set_layout_spacing(top_layout, window._scaled(8))
    window.btn_menu_file = _make_top_menu_button(window, _("File"))
    window.btn_menu_tools = _make_top_menu_button(window, _("Tools"))
    window.btn_menu_file.setObjectName("TopMainMenuButton")
    window.btn_menu_tools.setObjectName("TopMainMenuButton")
    top_layout.addWidget(window.btn_menu_file, 0, Qt.AlignVCenter)
    top_layout.addWidget(window.btn_menu_tools, 0, Qt.AlignVCenter)
    window.topbar_title_block = QFrame()
    window.topbar_title_block.setObjectName("TopBarTitleBlock")
    title_layout = QVBoxLayout(window.topbar_title_block)
    _layout_rules.set_layout_contents_margins(title_layout, 6, 0, 6, 0)
    _layout_rules.set_layout_spacing(title_layout, 0)
    window.lbl_topbar_title = QLabel(_("Herfy Client"))
    window.lbl_topbar_title.setObjectName("TopBarTitle")
    window.lbl_topbar_subtitle = QLabel(_("Food safety tracking workspace"))
    window.lbl_topbar_subtitle.setObjectName("TopBarSubTitle")
    title_layout.addWidget(window.lbl_topbar_title)
    title_layout.addWidget(window.lbl_topbar_subtitle)
    window.topbar_title_block.setVisible(False)
    add_stretch(top_layout, 1)
    window.btn_notifications = QToolButton()
    window.btn_notifications.setObjectName("NotificationsButton")
    window.btn_notifications.setCursor(Qt.PointingHandCursor)
    window.btn_notifications.setText("")
    window.btn_notifications.setToolButtonStyle(Qt.ToolButtonIconOnly)
    notif_icon = window._scaled(max(UI_METRICS.icon_size, 21))
    apply_button_icon(
        window.btn_notifications, "bell.png", size=QSize(notif_icon, notif_icon)
    )
    set_minimum_height(window.btn_notifications, window._scaled(32))
    set_minimum_width(window.btn_notifications, window._scaled(36))
    window.btn_notifications.clicked.connect(window.on_show_notifications)
    window.btn_notifications.setToolTip(_("Notifications"))
    window.notif_wrap = QFrame()
    window.notif_wrap.setObjectName("NotifWrap")
    set_size_policy(window.notif_wrap, QSizePolicy.Fixed, QSizePolicy.Fixed)
    set_minimum_height(window.notif_wrap, window._scaled(34))
    set_minimum_width(window.notif_wrap, window._scaled(42))
    notif_layout = QGridLayout(window.notif_wrap)
    _layout_rules.set_layout_contents_margins(notif_layout, 0, 0, 0, 0)
    _layout_rules.set_layout_spacing(notif_layout, 0)
    notif_layout.addWidget(window.btn_notifications, 0, 0, alignment=Qt.AlignCenter)
    window.lbl_notif_count = QLabel("0")
    window.lbl_notif_count.setObjectName("NotifBadge")
    window.lbl_notif_count.setAlignment(Qt.AlignCenter)
    badge_px = window._scaled(max(16, UI_METRICS.badge_size))
    set_badge_size(window.lbl_notif_count, badge_px, badge_px)
    window.lbl_notif_count.hide()
    notif_layout.addWidget(
        window.lbl_notif_count, 0, 0, alignment=Qt.AlignTop | Qt.AlignRight
    )
    window.lbl_user_info = QLabel("")
    window.lbl_user_info.setObjectName("UserInfoLabel")
    window.lbl_user_info.setToolTip(_("Current user and branch"))
    window.lbl_user_info.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
    window.lbl_user_info.setTextInteractionFlags(Qt.NoTextInteraction)
    window.lbl_user_info.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    set_minimum_height(window.lbl_user_info, window._scaled(28))
    set_minimum_width(window.lbl_user_info, 0)
    window.command_bar = QFrame()
    window.command_bar.setObjectName("CommandBar")
    window.command_bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    command_layout = QHBoxLayout(window.command_bar)
    _layout_rules.set_layout_contents_margins(command_layout, 4, 3, 4, 3)
    _layout_rules.set_layout_spacing(command_layout, 4)
    command_layout.addWidget(window.notif_wrap, 0, Qt.AlignVCenter)
    top_layout.addWidget(window.command_bar, 0, Qt.AlignVCenter)
    top_layout.addWidget(window.lbl_user_info, 0, Qt.AlignVCenter)
    window.top_bar = top_bar
    return top_bar
