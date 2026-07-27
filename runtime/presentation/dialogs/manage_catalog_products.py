from __future__ import annotations
import logging
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)
from runtime.shared.settings.config import _
from runtime.application.services.translations import is_rtl
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.shared.objects import safe_get
from runtime.application.services.catalog import stored_product_label, validate_stored_product_input
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.dialogs.update_dialogs import _DialogCardMixin
from runtime.presentation.layout.helpers import add_stretch, set_grid_column_stretch
from runtime.presentation.layout.metrics import UI_METRICS
from runtime.presentation.layout.interface import polish_interface
from runtime.presentation.widgets import apply_popup_contract
from runtime.presentation.widgets import DialogFeedbackMixin, confirm_delete
from runtime.presentation.widgets import polish_button
from runtime.bootstrap.qt.workers import WorkerRegistry, client_thread_pool

logger = logging.getLogger(__name__)


class ManageStoredProductsDialog(QDialog, _DialogCardMixin, DialogFeedbackMixin):

    def __init__(self, db_manager, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.setWindowTitle(_("Manage food item catalog"))
        lang_ = db_manager.get_setting("language", "ar")
        self.setLayoutDirection(Qt.RightToLeft if is_rtl(lang_) else Qt.LeftToRight)
        apply_popup_contract(
            self,
            object_name="StoredProductsDialog",
            modal=True,
            size_grip=True,
            width_ratio=0.4,
            height_ratio=0.45,
            min_width=UI_METRICS.stored_products_dialog_min_width,
            min_height=UI_METRICS.stored_products_dialog_min_height,
            max_width=UI_METRICS.stored_products_dialog_max_width,
            max_height=UI_METRICS.stored_products_dialog_max_height,
        )
        self._pool = client_thread_pool()
        self._worker_registry = WorkerRegistry(self._pool)
        self._catalog_worker = None
        self._reload_after_catalog_worker = False
        self.destroyed.connect(self._close_catalog_workers)
        self.init_ui()
        polish_interface(self, window_width=self.width())
        self.load_data()

    def _close_catalog_workers(self, *_args) -> None:
        self._closed = True
        registry = getattr(self, "_worker_registry", None)
        if registry is not None:
            try:
                close = getattr(registry, "close", None)
                if callable(close):
                    close()
                else:
                    registry.cancel_all()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "Stored-products worker registry close failed", exc_info=True
                )

    def init_ui(self):
        lay_main = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(lay_main, 10, 8, 10, 8)
        _layout_rules.set_layout_spacing(lay_main, 6)
        form_card, form_layout = self._card(
            "UsageImportCard", _("Food item catalog"), ""
        )
        grid = QGridLayout()
        _layout_rules.set_layout_horizontal_spacing(grid, 6)
        _layout_rules.set_layout_vertical_spacing(grid, 5)
        self.mat_num_edit = QLineEdit()
        self.mat_num_edit.setPlaceholderText(_("Material number"))
        self.mat_num_edit.setAccessibleName(_("Material number"))
        self.mat_num_edit.setClearButtonEnabled(True)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(_("Material name"))
        self.name_edit.setAccessibleName(_("Material name"))
        self.name_edit.setClearButtonEnabled(True)
        self.btn_add_update = QPushButton(_("Add"))
        polish_button(self.btn_add_update, role="primary")
        self.btn_add_update.clicked.connect(self.on_add_update)
        grid.addWidget(QLabel(_("Material number")), 0, 0)
        grid.addWidget(self.mat_num_edit, 0, 1)
        grid.addWidget(QLabel(_("Material name")), 1, 0)
        grid.addWidget(self.name_edit, 1, 1)
        grid.addWidget(self.btn_add_update, 0, 2, 2, 1)
        set_grid_column_stretch(grid, 1, 1)
        form_layout.addLayout(grid)
        lay_main.addWidget(form_card)
        list_card, list_layout = self._card(
            "UsageTableCard", _("Food item catalog list"), ""
        )
        self.list_widget = QListWidget()
        list_layout.addWidget(self.list_widget, 1)
        lay_main.addWidget(list_card, 1)
        btn_layout = QHBoxLayout()
        self.btn_delete = QPushButton(_("Delete"))
        polish_button(self.btn_delete, role="danger")
        self.btn_delete.clicked.connect(self.on_delete)
        btn_layout.addWidget(self.btn_delete)
        add_stretch(btn_layout)
        self.btn_close = QPushButton(_("Cancel"))
        polish_button(self.btn_close, role="ghost")
        self.btn_close.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_close)
        lay_main.addLayout(btn_layout)

    def load_data(self):
        if self._catalog_worker is not None:
            self._reload_after_catalog_worker = True
            return
        self._run_catalog_worker(
            lambda progress_callback=None: list(
                self.db_manager.fetch_stored_products() or []
            ),
            self._apply_catalog_rows,
            _("Failed to load food item catalog."),
        )

    def _apply_catalog_rows(self, rows) -> None:
        self.list_widget.clear()
        for stored_product in list(rows or []):
            item = QListWidgetItem(stored_product_label(stored_product))
            item.setData(Qt.UserRole, stored_product)
            self.list_widget.addItem(item)

    def _schedule_catalog_reload(self) -> None:
        self._reload_after_catalog_worker = True

    def _set_catalog_busy(self, busy: bool) -> None:
        for widget in (
            getattr(self, "btn_add_update", None),
            getattr(self, "btn_delete", None),
            getattr(self, "btn_close", None),
            getattr(self, "mat_num_edit", None),
            getattr(self, "name_edit", None),
            getattr(self, "list_widget", None),
        ):
            try:
                if widget is not None:
                    widget.setEnabled(not bool(busy))
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "ManageStoredProductsDialog busy-state update failed", exc_info=True
                )

    def _run_catalog_worker(self, work, on_success, fallback_error: str) -> None:
        if self._catalog_worker is not None:
            return
        self._set_catalog_busy(True)

        def _done(result):
            on_success(result)

        def _error(message: str):
            self._warn(_("Error"), str(message or fallback_error))

        def _finished():
            self._catalog_worker = None
            self._set_catalog_busy(False)
            if self._reload_after_catalog_worker:
                self._reload_after_catalog_worker = False
                QTimer.singleShot(0, self.load_data)

        worker = self._worker_registry.start(
            work,
            on_result=_done,
            on_error=_error,
            on_finished=_finished,
            operation_key="dialog:stored_products",
            scope_checker=lambda: not bool(getattr(self, "_closed", False)),
        )
        self._catalog_worker = worker
        if worker is None:
            self._set_catalog_busy(False)

    def on_add_update(self):
        mat_num = self.mat_num_edit.text().strip()
        nm_ = self.name_edit.text().strip()
        error_message = validate_stored_product_input(mat_num, nm_)
        if error_message:
            self._warn(_("Error"), error_message)
            return

        def _on_success(_result):
            self._info(_("Success"), _("Food item added."))
            self._schedule_catalog_reload()
            self.mat_num_edit.clear()
            self.name_edit.clear()

        self._run_catalog_worker(
            lambda progress_callback=None: self.db_manager.add_stored_product(
                mat_num, nm_
            ),
            _on_success,
            _("Failed to save food item."),
        )

    def on_delete(self):
        sel = self.list_widget.selectedItems()
        if not sel:
            self._warn(_("Error"), _("No food item selected."))
            return
        it = sel[0]
        data_ = it.data(Qt.UserRole) or {}
        mat_ = safe_get(data_, "material_number", "")
        if not confirm_delete(self, mat_):
            return

        def _on_success(_result):
            self._schedule_catalog_reload()

        self._run_catalog_worker(
            lambda progress_callback=None: self.db_manager.delete_stored_product(mat_),
            _on_success,
            _("Failed to delete food item."),
        )
