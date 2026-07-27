from __future__ import annotations
from .usage_form import UsageProductsFormMixin
from .update_dialogs import _DialogCardMixin
import logging
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QDialog, QListWidgetItem
from runtime.shared.settings.config import _
from runtime.application.services.translations import is_rtl
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.shared.booleans import parse_bool
from runtime.shared.objects import normalize_int, safe_get
from runtime.shared.signals import safe_disconnect
from runtime.application.services.catalog import (
    find_usage_selected_row,
    queued_status_message,
    usage_product_label,
    usage_reload_status,
    validate_usage_product_input,
)
from runtime.presentation.layout.interface import polish_interface
from runtime.presentation.layout.metrics import UI_METRICS
from runtime.presentation.widgets import apply_popup_contract
from runtime.presentation.widgets import confirm_delete
from runtime.presentation.widgets import widget_alive
from runtime.bootstrap.qt.workers import WorkerRegistry, client_thread_pool

logger = logging.getLogger(__name__)


class ManageUsageProductsDialog(QDialog, UsageProductsFormMixin, _DialogCardMixin):

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._pool = client_thread_pool()
        self._worker_registry = WorkerRegistry(self._pool)
        self._usage_state_timer = QTimer(self)
        self._usage_state_timer.setSingleShot(True)
        self._usage_state_timer.timeout.connect(self._reload_async)
        self.setWindowTitle(_("Consumption item catalog"))
        language = db.get_setting("language", "ar")
        self.setLayoutDirection(Qt.RightToLeft if is_rtl(language) else Qt.LeftToRight)
        apply_popup_contract(
            self,
            object_name="UsageProductsDialog",
            modal=True,
            size_grip=True,
            width_ratio=0.52,
            height_ratio=0.56,
            min_width=UI_METRICS.usage_products_dialog_min_width,
            min_height=UI_METRICS.usage_products_dialog_min_height,
            max_width=UI_METRICS.usage_products_dialog_max_width,
            max_height=UI_METRICS.usage_products_dialog_max_height,
        )
        self._build_catalog_ui()
        self._bind_application_state(parent)
        polish_interface(self, window_width=self.width())
        self._reload_async()

    def _bind_application_state(self, parent) -> None:
        self._bound_app_state = None
        self._disposed = False
        self.destroyed.connect(self._on_destroyed)
        state = getattr(parent, "app_state", None)
        if state is None:
            return
        try:
            state.data_changed.connect(self._on_app_state_usage_changed)
            state.item_updated.connect(self._on_app_state_usage_changed)
            state.item_deleted.connect(self._on_app_state_usage_changed)
            self._bound_app_state = state
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "ManageUsageProductsDialog state binding failed", exc_info=True
            )

    def _on_destroyed(self, *_args):
        self._disposed = True
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
                    "Usage-products worker registry close failed", exc_info=True
                )
        state = getattr(self, "_bound_app_state", None)
        if state is not None:
            for signal_name in ("data_changed", "item_updated", "item_deleted"):
                safe_disconnect(
                    getattr(state, signal_name),
                    self._on_app_state_usage_changed,
                    logger_=logger,
                    context="ManageUsageProductsDialog._on_destroyed disconnect",
                )
        self._bound_app_state = None

    def _on_app_state_usage_changed(self, domain, payload=None):
        try:
            if getattr(self, "_disposed", False) or not widget_alive(self):
                return
        except UI_OPERATION_EXCEPTIONS:
            return
        if str(domain or "").strip().lower() != "usage":
            return
        try:
            self._usage_state_timer.start(120)
        except RuntimeError:
            logger.debug(
                "ManageUsageProductsDialog._on_app_state_usage_changed skipped: timer no longer available"
            )

    def _selected_material(self) -> str:
        item = self.list.currentItem()
        if not item:
            return ""
        data = item.data(Qt.UserRole) or {}
        return str(safe_get(data, "material", "") or "").strip()

    def _set_busy(self, busy: bool, text: str = ""):
        for widget in (
            self.ed_m,
            self.ed_n,
            self.ed_u,
            self.btn_add,
            self.btn_del,
            self.btn_refresh,
        ):
            widget.setEnabled(not busy)
        if text:
            self.lbl_status.setText(text)

    def _reload_async(
        self, *, select_material: str | None = None, status_text: str | None = None
    ):
        selected = str(
            select_material or self._selected_material() or self.ed_m.text().strip()
        )
        self._set_busy(True, status_text or _("Loading..."))

        def _work(progress_callback=None):
            return {
                "rows": list(self.db.fetch_usage_products() or []),
                "pending": int(self.db.pending_usage_changes_count() or 0),
                "selected": selected,
            }

        self._run_usage_worker(
            _work, self._apply_reload_result, _("Failed to load usage catalog.")
        )

    def _apply_reload_result(self, payload):
        payload = payload or {}
        rows = list(payload.get("rows") or [])
        selected = str(payload.get("selected") or "").strip()
        pending = normalize_int(payload.get("pending"), 0)
        self.list.clear()
        for row in rows:
            item = QListWidgetItem(usage_product_label(row))
            item.setData(Qt.UserRole, row)
            self.list.addItem(item)
        selected_row = find_usage_selected_row(rows, selected)
        if selected_row is not None:
            self.list.setCurrentRow(selected_row)
            item = self.list.item(selected_row)
            if item is not None:
                self._fill_from_item(item)
        self.lbl_status.setText(
            usage_reload_status(pending=pending, current_text=self.lbl_status.text())
        )

    def _on_reload_error(self, message: str):
        self.lbl_status.setText(str(message or _("Operation failed.")))

    def _run_usage_worker(self, work, result_handler, fallback_error: str):
        worker = self._worker_registry.start(
            work,
            on_result=result_handler,
            on_error=lambda msg: self._on_reload_error(msg or fallback_error),
            on_finished=lambda: self._set_busy(False, self.lbl_status.text()),
            operation_key="dialog:usage_products",
            scope_checker=lambda: not bool(getattr(self, "_disposed", False))
            and widget_alive(self),
        )
        if worker is None:
            self._set_busy(False, self.lbl_status.text())

    def _fill_from_item(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole) or {}
        self.ed_m.setText(str(safe_get(data, "material", "") or ""))
        self.ed_n.setText(str(safe_get(data, "name", "") or ""))
        self.ed_u.setText(str(safe_get(data, "uom", "") or ""))

    def _add(self):
        m = self.ed_m.text().strip()
        n = self.ed_n.text().strip()
        u = self.ed_u.text().strip()
        error_message = validate_usage_product_input(m, n)
        if error_message:
            self.lbl_status.setText(error_message)
            return
        self._set_busy(True, _("Saving..."))
        self._run_usage_worker(
            lambda progress_callback=None: self.db.add_usage_product(
                m, n, u, remote_first=True
            ),
            self._on_add_done,
            _("Failed to save usage item."),
        )

    def _on_add_done(self, result):
        queued = (
            parse_bool((result or {}).get("queued"), False)
            if isinstance(result, dict)
            else False
        )
        material = self.ed_m.text().strip()
        self.ed_m.clear()
        self.ed_n.clear()
        self.ed_u.clear()
        self.lbl_status.setText(queued_status_message(action="save", queued=queued))
        self._reload_async(select_material=material)

    def _del(self):
        it = self.list.currentItem()
        if not it:
            self.lbl_status.setText(_("Select an item."))
            return
        data = it.data(Qt.UserRole) or {}
        material = safe_get(data, "material", "")
        if not confirm_delete(self, material):
            return
        self._set_busy(True, _("Deleting..."))
        self._run_usage_worker(
            lambda progress_callback=None: self.db.delete_usage_product(
                str(material or ""), remote_first=True
            ),
            self._on_delete_done,
            _("Failed to delete usage item."),
        )

    def _on_delete_done(self, result):
        queued = (
            parse_bool((result or {}).get("queued"), False)
            if isinstance(result, dict)
            else False
        )
        self.lbl_status.setText(queued_status_message(action="delete", queued=queued))
        self._reload_async()

    def _refresh_remote(self):
        if not self.db.app_state.api_client:
            self.lbl_status.setText(_("Working in local mode."))
            self._reload_async(status_text=self.lbl_status.text())
            return
        self._set_busy(True, _("Refreshing..."))

        def _work(progress_callback=None):
            try:
                self.db.sync_pending_usage_changes()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "ManageUsageProductsDialog._refresh_remote._work fallback failed",
                    exc_info=True,
                )
            rows = self.db.refresh_usage_products_from_server(force_refresh=True)
            return {"count": len(rows or [])}

        self._run_usage_worker(
            _work,
            lambda _res: self._on_refresh_done(),
            _("Failed to refresh usage catalog."),
        )

    def _on_refresh_done(self):
        self.lbl_status.setText(queued_status_message(action="refresh", queued=False))
        self._reload_async(status_text=self.lbl_status.text())
