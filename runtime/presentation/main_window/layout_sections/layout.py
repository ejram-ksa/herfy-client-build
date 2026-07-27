from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

import logging
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QWidget
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.presentation.dialogs.about import create_about_page
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.shell import apply_device_properties
from runtime.presentation.main_window.widgets import build_sidebar
from runtime.presentation.usage.print_service import UsagePrintService
from runtime.presentation.views.home_sections import create_home_page
from runtime.presentation.views.tracking_sections import TrackingPage
from runtime.presentation.views.usage_page import UsagePage

logger = logging.getLogger(__name__)


class MainWindowContentPagesMixin:

    def _bind_runtime_state(self, page: QWidget | None) -> None:
        if page is None:
            return
        binder = getattr(page, "bind_app_state", None)
        if callable(binder):
            try:
                binder(getattr(self, "app_state", None))
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "MainWindowContentPagesMixin._bind_runtime_state failed",
                    exc_info=True,
                )

    def _insert_content_page(self, page: QWidget | None) -> None:
        stack = getattr(self, "content_stack", None)
        if stack is None or page is None:
            return
        try:
            if stack.indexOf(page) < 0:
                stack.addWidget(page)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "MainWindowContentPagesMixin._insert_content_page failed", exc_info=True
            )

    def _create_home_page(self) -> QWidget:
        home_page = create_home_page(self.db_manager)
        try:
            home_page.navigate_requested.connect(self._on_home_navigation_requested)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Home navigation signal connection failed", exc_info=True)
        self._bind_runtime_state(home_page)
        return home_page

    def _create_tracking_page(self) -> TrackingPage:
        track_page = TrackingPage(
            self.db_manager,
            parent=self,
            tracking_service=self.container.create_tracking_service(),
        )
        try:
            track_page.branch_context_changed.connect(self.on_branch_context_changed)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "Tracking branch-context signal connection failed", exc_info=True
            )
        self._bind_runtime_state(track_page)
        return track_page

    def _create_usage_page(self) -> UsagePage:
        usage_page = UsagePage(
            self.db_manager,
            usage_service=self.container.create_usage_service(),
            usage_print_service=UsagePrintService(),
            usage_workspace_service=self.container.create_usage_workspace_service(),
        )
        self._bind_runtime_state(usage_page)
        return usage_page

    def _create_about_widget(self) -> QWidget:
        about_page = create_about_page(self.db_manager)
        try:
            about_page.setObjectName("Card")
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("About page object-name setup failed", exc_info=True)
        return about_page

    def _ensure_home_page(self) -> QWidget | None:
        if getattr(self, "home_page", None) is None:
            self.home_page = self._create_home_page()
        self._insert_content_page(self.home_page)
        return self.home_page

    def _ensure_track_page(self) -> TrackingPage | None:
        if getattr(self, "track_page", None) is None:
            self.track_page = self._create_tracking_page()
        self._insert_content_page(self.track_page)
        return self.track_page

    def _ensure_usage_page(self) -> UsagePage | None:
        if getattr(self, "usage_page", None) is None:
            self.usage_page = self._create_usage_page()
        self._insert_content_page(self.usage_page)
        return self.usage_page

    def _ensure_about_page(self) -> QWidget | None:
        if getattr(self, "about_page", None) is None:
            self.about_page = self._create_about_widget()
        self._insert_content_page(self.about_page)
        return self.about_page

    def _create_content_pages(self) -> tuple[QWidget, TrackingPage, UsagePage, QWidget]:
        return (
            self._create_home_page(),
            self._create_tracking_page(),
            self._create_usage_page(),
            self._create_about_widget(),
        )

    def _content_pages_ready(self) -> bool:
        stack = getattr(self, "content_stack", None)
        pages = (
            getattr(self, "home_page", None),
            getattr(self, "track_page", None),
            getattr(self, "usage_page", None),
            getattr(self, "about_page", None),
        )
        if stack is None or any((page is None for page in pages)):
            return False
        try:
            return all((stack.indexOf(page) >= 0 for page in pages))
        except UI_OPERATION_EXCEPTIONS:
            return False

    def _ensure_content_pages(self) -> None:
        self._ensure_home_page()
        self._ensure_track_page()
        self._ensure_usage_page()
        self._ensure_about_page()

    def _rebuild_content_pages(self, preserve_index: bool = False) -> None:
        old_index = self.content_stack.currentIndex() if preserve_index else 0
        login_page = getattr(self, "login_page", None)
        login_index = (
            self.content_stack.indexOf(login_page) if login_page is not None else -1
        )
        if login_index >= 0:
            self.content_stack.removeWidget(login_page)
        while self.content_stack.count() > 0:
            widget = self.content_stack.widget(0)
            self.content_stack.removeWidget(widget)
            binder = getattr(widget, "bind_app_state", None)
            if callable(binder):
                try:
                    binder(None)
                except UI_OPERATION_EXCEPTIONS:
                    logger.debug(
                        "MainWindowContentPagesMixin._rebuild_content_pages unbind failed",
                        exc_info=True,
                    )
            widget.deleteLater()
        if login_index >= 0:
            self.content_stack.insertWidget(0, login_page)
        self.home_page = None
        self.track_page = None
        self.usage_page = None
        self.about_page = None
        if self.app_state.session:
            self._ensure_content_pages()
        if preserve_index:
            self.content_stack.setCurrentIndex(
                min(max(old_index, 0), self.content_stack.count() - 1)
            )
        else:
            self._select_home_page()

    def init_ui(self):
        self._apply_root_theme()
        central = QWidget()
        central.setObjectName("AppRoot")
        try:
            apply_device_properties(central, self.width(), QApplication.instance())
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("MainWindowUiMixin.init_ui fallback failed", exc_info=True)
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        _layout_rules.set_layout_contents_margins(main_layout, 0, 0, 0, 0)
        _layout_rules.set_layout_spacing(main_layout, 0)
        self.home_page = None
        self.track_page = None
        self.usage_page = None
        self.about_page = None
        build_sidebar(self, main_layout)
        self._build_content_shell(main_layout)


from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QLabel, QSizePolicy, QStackedWidget, QVBoxLayout
from runtime.presentation.layout.helpers import set_minimum_height, set_minimum_width, set_size_policy
from runtime.presentation.layout.shell import apply_responsive_shell_metrics
from runtime.presentation.main_window.widgets import build_top_bar
from runtime.presentation.responsive import ensure_layout_mode_controller
from runtime.presentation.theme import apply_app_theme



class MainWindowShellLayoutMixin:

    def _scaled(self, value: int) -> int:
        try:
            return int(self.S(value))
        except UI_OPERATION_EXCEPTIONS:
            return int(value)

    def _apply_root_theme(self):
        app = QApplication.instance()
        font_name = str(self.db_manager.get_setting("font", "Segoe UI") or "Segoe UI")
        try:
            font_size = int(self.db_manager.get_setting("font_size", "10") or 10)
        except (TypeError, ValueError):
            font_size = 10
        if app is not None:
            apply_app_theme(app, font_name=font_name, font_size_pt=font_size)

    def _build_content_shell(self, parent_layout: QHBoxLayout) -> None:
        right_shell = QWidget()
        right_shell.setObjectName("RightShell")
        right_layout = QVBoxLayout(right_shell)
        _layout_rules.set_layout_contents_margins(right_layout, 0, 0, 0, 0)
        _layout_rules.set_layout_spacing(right_layout, 0)
        parent_layout.addWidget(right_shell, 1)
        right_layout.addWidget(build_top_bar(self))
        self.content_scroll = None
        content_host = QWidget()
        content_host.setObjectName("ContentHost")
        self.content_host = content_host
        content_layout = QVBoxLayout(content_host)
        self.content_layout = content_layout
        _layout_rules.set_layout_contents_margins(
            content_layout,
            self._scaled(14),
            self._scaled(12),
            self._scaled(14),
            self._scaled(10),
        )
        _layout_rules.set_layout_spacing(content_layout, 0)
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("ContentStack")
        content_layout.addWidget(self.content_stack)
        right_layout.addWidget(content_host, 1)
        self.shell_status_bar = QWidget()
        self.shell_status_bar.setObjectName("ShellStatusBar")
        set_minimum_height(self.shell_status_bar, self._scaled(32))
        shell_status_layout = QHBoxLayout(self.shell_status_bar)
        _layout_rules.set_layout_contents_margins(
            shell_status_layout,
            self._scaled(28),
            self._scaled(4),
            self._scaled(28),
            self._scaled(4),
        )
        _layout_rules.set_layout_spacing(shell_status_layout, self._scaled(8))
        self.shell_status_message = QLabel("")
        self.shell_status_message.setObjectName("ShellStatusMessage")
        set_size_policy(
            self.shell_status_message, QSizePolicy.Expanding, QSizePolicy.Preferred
        )
        shell_status_layout.addWidget(self.shell_status_message, 1)
        self.shell_status_widgets_layout = QHBoxLayout()
        _layout_rules.set_layout_contents_margins(
            self.shell_status_widgets_layout, 0, 0, 0, 0
        )
        _layout_rules.set_layout_spacing(self.shell_status_widgets_layout, 4)
        shell_status_layout.addLayout(self.shell_status_widgets_layout)
        right_layout.addWidget(self.shell_status_bar, 0)
        self._responsive_layout_timer = QTimer(self)
        self._responsive_layout_timer.setSingleShot(True)
        self._responsive_layout_timer.setInterval(16)
        self._responsive_layout_timer.timeout.connect(
            lambda: apply_responsive_shell_metrics(self)
        )

    def _show_shell_status_message(self, message: str, timeout_ms: int = 0) -> None:
        text = str(message or "").strip()
        try:
            self.shell_status_message.setText(text)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Failed to show shell status message", exc_info=True)
        timer = getattr(self, "_shell_status_clear_timer", None)
        self._safe_stop_timer(timer)
        if text and int(timeout_ms or 0) > 0:
            try:
                if timer is None:
                    timer = QTimer(self)
                    timer.setSingleShot(True)
                    timer.timeout.connect(self._clear_shell_status_message)
                    self._shell_status_clear_timer = timer
                timer.start(int(timeout_ms))
            except UI_OPERATION_EXCEPTIONS:
                logger.debug("Failed to start shell status clear timer", exc_info=True)

    def _clear_shell_status_message(self) -> None:
        try:
            self.shell_status_message.clear()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Failed to clear shell status message", exc_info=True)

    def _show_runtime_status_message(self, message: str, timeout_ms: int = 0) -> None:
        if int(getattr(self, "_ui_transition_depth", 0) or 0) > 0:
            return
        self._show_shell_status_message(message, timeout_ms)

    def _schedule_responsive_layout_refresh(self, *, force: bool = False) -> None:
        """Schedule shell chrome reflow without recalculating on every pixel."""
        try:
            controller = ensure_layout_mode_controller(
                self, attr_name="_shell_layout_mode_controller", interval_ms=60
            )
            if not bool(getattr(self, "_shell_layout_mode_connected", False)):
                controller.reflowRequested.connect(
                    lambda *_args: apply_responsive_shell_metrics(self)
                )
                self._shell_layout_mode_connected = True
            controller.schedule(force=force)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("responsive shell controller failed", exc_info=True)
            timer = getattr(self, "_responsive_layout_timer", None)
            if timer is not None:
                timer.start()
            else:
                apply_responsive_shell_metrics(self)

    def _connect_screen_change_refresh(self) -> None:
        """Refresh adaptive layout when the window moves to another monitor."""
        if bool(getattr(self, "_screen_change_refresh_connected", False)):
            return
        handle = self.windowHandle() if hasattr(self, "windowHandle") else None
        if handle is None:
            return
        signal = getattr(handle, "screenChanged", None)
        if signal is None:
            return
        try:
            signal.connect(
                lambda *_args: self._schedule_responsive_layout_refresh(force=True)
            )
            self._screen_change_refresh_connected = True
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("screen change refresh connection failed", exc_info=True)

    def showEvent(self, event):
        """Refresh responsive metrics when the main window is shown."""
        super().showEvent(event)
        self._connect_screen_change_refresh()
        self._schedule_responsive_layout_refresh(force=True)

    def moveEvent(self, event):
        """Refresh responsive metrics after moving between monitors."""
        super().moveEvent(event)
        self._schedule_responsive_layout_refresh(force=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_responsive_layout_refresh()
        try:
            filler = getattr(self, "sidebar_status_filler", None)
            if filler is not None and getattr(self, "sidebar", None) is not None:
                sidebar_width = int(self.sidebar.width())
                if getattr(self, "_last_sidebar_filler_width", None) != sidebar_width:
                    self._last_sidebar_filler_width = sidebar_width
                    set_minimum_width(filler, sidebar_width)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "MainWindowShellLayoutMixin.resizeEvent fallback failed", exc_info=True
            )
