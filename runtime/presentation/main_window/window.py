from __future__ import annotations
import logging
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QProgressBar, QSizePolicy
from runtime.shared.settings.config import APP_DISPLAY_NAME, _, load_translations
from runtime.shared.errors import STATE_OPERATION_EXCEPTIONS, UI_OPERATION_EXCEPTIONS
from runtime.application.services.sync import ServerRuntimeService
from runtime.application.services.sync import apply_startup_preferences
from runtime.application.services.translations import is_rtl
from runtime.presentation.dialogs.notification_service import NotificationService
from runtime.presentation.layout.metrics import UI_METRICS
from runtime.presentation.layout.shell import (
    apply_device_properties,
    apply_initial_window_geometry,
    apply_responsive_shell_metrics,
)
from runtime.presentation.layout.scaling import make_scaler
from runtime.presentation.layout.helpers import set_minimum_width, set_size_policy
from runtime.presentation.views.login_page import LoginPage
from runtime.presentation.main_window.access import MainWindowAccessNavigationMixin
from runtime.presentation.main_window.action_sections import (
    MainWindowActionSupportMixin,
    MainWindowDialogActionsMixin,
    MainWindowMenuBuilderMixin,
    MainWindowRouteNavigationMixin,
)
from runtime.presentation.main_window.cloud_sections import MainWindowCloudMixin, MainWindowUpdatesMixin
from runtime.presentation.main_window.layout_sections import MainWindowContentPagesMixin
from runtime.presentation.main_window.layout_sections import MainWindowShellLayoutMixin
from runtime.presentation.main_window.monitoring import MainWindowMonitoringMixin
from runtime.presentation.main_window.notifications import (
    MainWindowNotificationsMixin,
    MainWindowTrayMixin,
)
from runtime.presentation.main_window.session import MainWindowSessionMixin
from runtime.presentation.widgets import apply_window_icon
from runtime.bootstrap.qt.workers import WorkerRegistry, client_thread_pool

logger = logging.getLogger(__name__)


class HerfyMainWindow(
    MainWindowUpdatesMixin,
    MainWindowCloudMixin,
    MainWindowSessionMixin,
    MainWindowMonitoringMixin,
    MainWindowShellLayoutMixin,
    MainWindowContentPagesMixin,
    MainWindowMenuBuilderMixin,
    MainWindowRouteNavigationMixin,
    MainWindowAccessNavigationMixin,
    MainWindowTrayMixin,
    MainWindowNotificationsMixin,
    MainWindowActionSupportMixin,
    MainWindowDialogActionsMixin,
    QMainWindow,
):
    cloud_changed = pyqtSignal()
    cloud_state_changed = pyqtSignal(bool)

    @property
    def app_state(self):
        return self.container.app_state

    def __init__(self, container):
        super().__init__()
        if container is None:
            raise RuntimeError(
                "HerfyMainWindow requires an application dependency container."
            )
        self.container = container
        self.db_manager = self.container.db_manager
        self.session_store = self.container.create_session_store()
        self.tray_icon = None
        self._tray_menu = None
        self.S = make_scaler(QApplication.instance())
        self._configure_db_feedback()
        self._initialize_window_identity()
        self._initialize_shell()
        self._initialize_status_widgets()
        self._initialize_timers()
        self._initialize_runtime_components()
        self._connect_runtime_signals()
        self._defer_startup_flow()

    def _defer_startup_flow(self) -> None:
        self._startup_flow_started = False

        def _run() -> None:
            if bool(getattr(self, "_startup_flow_started", False)):
                return
            self._startup_flow_started = True
            self._start_startup_flow()

        QTimer.singleShot(0, _run)

    def _initialize_window_identity(self) -> None:
        current_language = self.db_manager.get_setting("language", "ar")
        load_translations(current_language)
        self.setLayoutDirection(
            Qt.RightToLeft if is_rtl(current_language) else Qt.LeftToRight
        )
        self.setWindowTitle(_(APP_DISPLAY_NAME))
        self.setObjectName("MainWindow")
        apply_window_icon(self)
        try:
            apply_device_properties(self, self.width(), QApplication.instance())
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "HerfyMainWindow._initialize_window_identity device-properties setup failed",
                exc_info=True,
            )

    def _initialize_shell(self) -> None:
        self.init_ui()
        apply_responsive_shell_metrics(self)
        apply_initial_window_geometry(self)
        self.init_menu_bar()
        self.statusBar().hide()
        self.init_tray_icon()
        self.login_page = LoginPage(self)
        self.content_stack.insertWidget(0, self.login_page)
        self.content_stack.setCurrentWidget(self.login_page)
        self._apply_logged_out_shell(reset_sidebar=True)

    def _create_network_indicator(self) -> QLabel | None:
        try:
            indicator = QLabel("")
            indicator.setObjectName("NetIndicator")
            self.shell_status_widgets_layout.addWidget(indicator)
            return indicator
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "HerfyMainWindow._create_network_indicator failed", exc_info=True
            )
            return None

    def _create_transition_progress(self) -> QProgressBar | None:
        try:
            progress = QProgressBar(self)
            progress.setRange(0, 0)
            progress.setTextVisible(False)
            set_minimum_width(
                progress, self.S(UI_METRICS.transition_progress_min_width)
            )
            set_size_policy(progress, QSizePolicy.Preferred, QSizePolicy.Fixed)
            progress.hide()
            self.shell_status_widgets_layout.addWidget(progress)
            return progress
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "HerfyMainWindow._create_transition_progress failed", exc_info=True
            )
            return None

    def _initialize_status_widgets(self) -> None:
        # Connection is unknown until the first real API result. Do not show a
        # false offline state during normal startup on healthy networks.
        self._cloud_online = False
        self._cloud_state_known = False
        self.net_indicator = self._create_network_indicator()
        self.transition_progress = self._create_transition_progress()
        if self.net_indicator is not None:
            self.net_indicator.setText(_("Checking connection..."))
            self.net_indicator.setProperty("net", "checking")

    def _initialize_timers(self) -> None:
        self._pool = client_thread_pool()
        self._worker_registry = WorkerRegistry(self._pool)
        self._expiry_token = 0
        self._expiry_running = False
        self.check_interval_timer = QTimer(self)
        self.check_interval_timer.timeout.connect(self.check_expiry)
        self.daily_timer = QTimer(self)
        self.daily_timer.timeout.connect(self.update_daily)
        self.token_refresh_timer = QTimer(self)
        self.token_refresh_timer.timeout.connect(self.refresh_cloud_token)

    def _initialize_runtime_components(self) -> None:
        self.notifications_list = []
        self.unread_notifications = 0
        self._notifications_dialog = None
        self.player = None
        self.notifications_service = NotificationService(self)
        self.server_runtime_service = ServerRuntimeService()
        self.player = getattr(self.notifications_service, "player", None)
        self.sync_manager = self.container.create_sync_manager(self)
        self._runtime_scope_token = 0
        self._closing_completely = False
        self._usage_sync_running = False
        self._usage_sync_pending = False
        self._active_worker_keys = set()
        self._active_workers = set()
        self._restore_session_running = False
        self._update_check_running = False
        self._cloud_change_running = False
        self._cloud_change_pending = False
        self._cloud_snapshot_pull_pending = False
        self._change_driven_sync_timer = None
        self._change_driven_sync_pending_domains = set()
        self._change_driven_last_pull_ms = 0
        self._ui_transition_depth = 0
        self._ui_transition_message = ""

    def _runtime_scope_token_value(self) -> int:
        try:
            return int(getattr(self, "_runtime_scope_token", 0))
        except (TypeError, ValueError):
            return 0

    def _mark_runtime_scope_changed(self) -> int:
        """Invalidate current runtime scope and cancel stale client workers.

        The server remains authoritative.  This client-side cancellation is
        cooperative and prevents old worker results from affecting a new user
        session or the UI after manual logout.
        """
        try:
            self._cancel_active_workers("runtime_scope_changed")
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Runtime scope worker cancellation failed", exc_info=True)
        token = self._runtime_scope_token_value() + 1
        self._runtime_scope_token = token
        return token

    def _runtime_scope_is_current(self, token: int) -> bool:
        return self._runtime_scope_token_value() == int(token)

    def _connect_runtime_signals(self) -> None:
        try:
            self.cloud_changed.connect(
                lambda: self.sync_manager.schedule(
                    "cloud_changed", self._on_cloud_changed, 350
                )
            )
            self.cloud_state_changed.connect(self._set_cloud_state)
            self.app_state.item_updated.connect(self._on_runtime_item_mutation)
            self.app_state.item_deleted.connect(self._on_runtime_item_mutation)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "HerfyMainWindow._connect_runtime_signals failed", exc_info=True
            )

    def _apply_startup_preferences(self) -> None:
        try:
            apply_startup_preferences(self.db_manager)
        except STATE_OPERATION_EXCEPTIONS:
            logger.debug(
                "HerfyMainWindow._apply_startup_preferences failed", exc_info=True
            )

    def _start_startup_flow(self) -> None:

        def _apply_preferences() -> None:
            self._apply_startup_preferences()

        def _apply_cached_contract() -> None:
            self._safe_apply_cached_startup_contract()

        def _refresh_contract() -> None:
            self._safe_refresh_startup_contract_async()

        def _restore_session() -> None:
            try:
                self.try_restore_session_async()
            except STATE_OPERATION_EXCEPTIONS:
                logger.debug(
                    "HerfyMainWindow._start_startup_flow failed", exc_info=True
                )

        # Startup is ordered by dependency, not by arbitrary wall-clock delays.
        # A zero-delay handoff lets Qt paint the login shell before background
        # work begins without penalizing fast devices by several seconds.
        _apply_preferences()
        _apply_cached_contract()
        QTimer.singleShot(0, _restore_session)
        QTimer.singleShot(0, _refresh_contract)


MainWindow = HerfyMainWindow
__all__ = ["HerfyMainWindow", "MainWindow"]
