from __future__ import annotations
from typing import ClassVar
import logging
from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import QWidget
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.application.services.catalog import PageVisibleStateService
from runtime.application.services.usage import UsageWorkspaceService
from runtime.presentation.layout.interface import polish_interface
from runtime.presentation.layout.scaling import make_scaler
from runtime.presentation.layout.tables import ResponsiveDataPageResizeMixin
from runtime.presentation.tables.headers import COL_H
from runtime.presentation.usage import UsageComputeService
from runtime.presentation.usage.controller import UsageControllerMixin
from runtime.presentation.usage.print_service import UsagePrintService
from runtime.presentation.usage.responsive import UsageResponsiveLayoutMixin
from runtime.presentation.usage.builder import UsageUiBuilderMixin

logger = logging.getLogger(__name__)


class UsagePage(
    UsageResponsiveLayoutMixin,
    UsageUiBuilderMixin,
    ResponsiveDataPageResizeMixin,
    UsageControllerMixin,
    QWidget,
):
    responsive_resize_callbacks = ("apply_responsive_profile",)
    responsive_table_attr = "table"
    responsive_table_size_callback = "_size_columns"
    responsive_table_min_height = None
    responsive_table_resize_after_callbacks = False
    status_label_attr = "lbl_status"
    summary_empty_label_attr = "usage_empty_label"
    summary_loading_text = "Calculating..."
    summary_state_method = "usage_state"
    COL_RATIOS: ClassVar[tuple[int, ...]] = (8, 36, 8, 10, 7, 19, 5, 7)
    COL_MIN_WIDTHS: ClassVar[tuple[int, ...]] = (64, 180, 58, 78, 48, 130, 36, 54)

    def __init__(
        self,
        db,
        usage_service=None,
        usage_print_service: UsagePrintService | None = None,
        usage_workspace_service: UsageWorkspaceService | None = None,
        usage_compute_service: UsageComputeService | None = None,
    ):
        super().__init__()
        self.setObjectName("UsagePage")
        self.db = db
        self.usage_service = usage_service
        self.usage_print_service = usage_print_service or UsagePrintService()
        self.usage_workspace_service = (
            usage_workspace_service or UsageWorkspaceService()
        )
        self.usage_compute_service = usage_compute_service or UsageComputeService(
            usage_service=self.usage_service,
            workspace_service=self.usage_workspace_service,
            parent=self,
        )
        self._access_allowed = True
        self._access_reason = ""
        self.page_visible_state_service = PageVisibleStateService()
        self._S = make_scaler()
        self._receipts_path = ""
        self._beginning_path = ""
        self._build_usage_ui()
        self._connect_usage_signals()
        self._initialize_usage_lifecycle()
        self._finish_usage_ui()

    def _connect_usage_signals(self) -> None:
        self.btn_r.clicked.connect(self._pick_r)
        self.btn_b.clicked.connect(self._pick_b)
        self.search.textChanged.connect(self.proxy.set_search)
        self.chk_hide_total_zero.toggled.connect(self._on_hide_total_zero_toggled)
        self.btn_print.clicked.connect(self._print_table)
        self.proxy.modelReset.connect(self._open_persistent_editors)
        self.proxy.rowsInserted.connect(lambda *_: self._open_persistent_editors())
        self.usage_compute_service.busy_changed.connect(self._on_compute_busy_changed)
        self.usage_compute_service.status_changed.connect(
            self._on_compute_status_changed
        )
        self.usage_compute_service.result_ready.connect(self._on_compute_result_ready)
        self.usage_compute_service.error_raised.connect(self._on_compute_error_raised)
        self.model.dataChanged.connect(self._on_usage_model_data_changed)

    def _initialize_usage_lifecycle(self) -> None:
        self._usage_state_refresh_timer = QTimer(self)
        self._usage_state_refresh_timer.setSingleShot(True)
        self._usage_state_refresh_timer.timeout.connect(
            self._run_app_state_usage_refresh
        )
        self._bound_app_state = None
        self._disposed = False
        self._deferred_usage_refresh = False
        self.destroyed.connect(self._cancel_usage_compute)
        self.destroyed.connect(self._on_destroyed)

    def _finish_usage_ui(self) -> None:
        self._apply_theme()
        self._size_columns()
        self.table.viewport().installEventFilter(self)
        self.table.installEventFilter(self)
        self._set_page_table_summary(0, loading=False)
        polish_interface(self, window_width=self.width())

    def _cancel_usage_compute(self, *_args) -> None:
        try:
            cancel = getattr(self.usage_compute_service, "cancel", None)
            if callable(cancel):
                cancel()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Usage compute cancellation failed", exc_info=True)

    def _summary_state_kwargs(self, state_kwargs: dict) -> dict:
        payload = dict(state_kwargs)
        payload.setdefault("access_allowed", bool(self._access_allowed))
        payload.setdefault("access_reason", self._access_reason)
        return payload

    def eventFilter(self, obj, event):
        if obj is self.table.viewport() and event.type() == QEvent.Resize:
            self._size_columns()
        if (
            obj is self.table
            and event.type() == QEvent.KeyPress
            and (event.key() in (Qt.Key_Return, Qt.Key_Enter))
        ):
            current = self.table.currentIndex()
            row = current.row() if current.isValid() else 0
            column = current.column() if current.isValid() else COL_H
            if column != COL_H:
                column = COL_H
            next_row = min(row + 1, self.proxy.rowCount() - 1)
            target = self.proxy.index(next_row, column)
            if target.isValid():
                self.table.setCurrentIndex(target)
                self.table.edit(target)
                return True
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_deferred_usage_refresh", False):
            self._deferred_usage_refresh = False
            try:
                self._usage_state_refresh_timer.start(120)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug("UsagePage.showEvent fallback failed", exc_info=True)
