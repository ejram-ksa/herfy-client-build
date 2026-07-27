from __future__ import annotations
import logging
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFileDialog
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.presentation.tables.headers import COL_B, COL_H, COL_R, COL_T, COL_U, usage_print_headers
from runtime.presentation.usage import UsageComputePayload
from runtime.presentation.widgets import DomainAppStateBindingMixin
from runtime.presentation.widgets import ControllerLifecycleMixin
from runtime.presentation.widgets import refresh_widget_style

logger = logging.getLogger(__name__)


class UsageControllerMixin(DomainAppStateBindingMixin, ControllerLifecycleMixin):
    app_state_page_name = "UsagePage"
    app_state_callback_name = "_on_app_state_usage_changed"

    def _on_app_state_usage_changed(self, domain, payload=None):
        if not self._is_alive():
            return
        if str(domain or "").strip().lower() != "usage":
            return
        if self._usage_workspace_has_active_input():
            self._mark_usage_server_refresh_pending(payload)
            return
        if not self._should_refresh_now():
            self._deferred_usage_refresh = True
            return
        try:
            self._usage_state_refresh_timer.start(120)
        except RuntimeError:
            logger.debug(
                "UsagePage._on_app_state_usage_changed skipped: timer no longer available"
            )

    def _run_app_state_usage_refresh(self):
        if not self._is_alive():
            return
        try:
            if self._usage_workspace_has_active_input():
                self._mark_usage_server_refresh_pending(
                    {"reason": "deferred_usage_refresh"}
                )
                return
            if self._receipts_path or self._beginning_path or self.model.rowCount() > 0:
                self._auto_compute()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "UsagePage._run_app_state_usage_refresh fallback failed", exc_info=True
            )

    def _usage_workspace_has_active_input(self) -> bool:
        return bool(
            getattr(self, "_usage_workspace_active", False)
            or getattr(self, "_usage_input_dirty", False)
            or str(getattr(self, "_receipts_path", "") or "").strip()
            or str(getattr(self, "_beginning_path", "") or "").strip()
            or (hasattr(self, "model") and self.model.rowCount() > 0)
        )

    def _mark_usage_server_refresh_pending(self, payload=None) -> None:
        self._usage_server_refresh_pending = True
        try:
            self._set_page_table_summary(
                self.proxy.rowCount(),
                loading=False,
                status_text=_("Server catalog changed. Worksheet preserved."),
            )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "UsagePage._mark_usage_server_refresh_pending fallback failed",
                exc_info=True,
            )

    def set_access_state(self, allowed: bool, *, reason: str = ""):
        self._access_allowed = bool(allowed)
        self._access_reason = str(reason or "").strip()
        self._apply_access_state()

    def _apply_access_state(self):
        enabled = bool(self._access_allowed and (not self._compute_is_running()))
        for widget in (
            self.btn_r,
            self.btn_b,
            getattr(self, "chk_hide_total_zero", None),
            self.btn_print,
            self.search,
            self.table,
        ):
            if widget is None:
                continue
            try:
                widget.setEnabled(enabled)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "UsagePage._apply_access_state fallback failed", exc_info=True
                )
        if not self._access_allowed or not self._compute_is_running():
            self._set_page_table_summary(self.proxy.rowCount(), loading=False)

    def _select_excel_file(self, title: str) -> str:
        dialog = QFileDialog(self, title)
        dialog.setObjectName("AppFileDialog")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setFileMode(QFileDialog.ExistingFile)
        all_files_filter = _("All files (*.*)")
        dialog.setNameFilters(
            [
                all_files_filter,
                _("Supported data files (*.xlsx *.xls *.xlsm *.csv *.txt *.tsv)"),
            ]
        )
        dialog.selectNameFilter(all_files_filter)
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setOption(QFileDialog.DontUseNativeDialog, False)
        try:
            dialog.setLayoutDirection(self.layoutDirection())
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("UsagePage._select_excel_file fallback failed", exc_info=True)
        if dialog.exec_() != QFileDialog.Accepted:
            return ""
        files = dialog.selectedFiles() or []
        return str(files[0] or "") if files else ""

    def _apply_file_selection(self, path: str, *, target: str):
        self._usage_workspace_active = True
        self._usage_server_refresh_pending = False
        present = self.usage_workspace_service.format_selected_file(path)
        if target == "receipts":
            self._receipts_path = str(path or "")
            self.ed_r.setText(present.display_name)
            self.ed_r.setToolTip(present.tooltip)
            self.btn_r.setToolTip(present.tooltip or _("Import receipts file"))
            self.btn_r.setText(_("Receipts") + " ✓")
            self.btn_r.setProperty("fileSelected", True)
            refresh_widget_style(self.btn_r)
            return
        self._beginning_path = str(path or "")
        self.ed_b.setText(present.display_name)
        self.ed_b.setToolTip(present.tooltip)
        self.btn_b.setToolTip(present.tooltip or _("Import opening stock file"))
        self.btn_b.setText(_("Opening stock") + " ✓")
        self.btn_b.setProperty("fileSelected", True)
        refresh_widget_style(self.btn_b)

    def _pick_usage_file(self, title: str, *, target: str):
        path = self._select_excel_file(title)
        if not path:
            return
        self._apply_file_selection(path, target=target)
        self._auto_compute()

    def _pick_r(self):
        self._pick_usage_file(_("Receipts"), target="receipts")

    def _pick_b(self):
        self._pick_usage_file(_("Opening stock"), target="beginning")

    def _compute_is_running(self) -> bool:
        return bool(getattr(self.usage_compute_service, "is_busy", False))

    def _auto_compute(self):
        self._usage_workspace_active = True
        started = self.usage_compute_service.request_auto_compute(
            access_allowed=self._access_allowed,
            access_reason=self._access_reason,
            receipts_path=self._receipts_path,
            beginning_path=self._beginning_path,
            db_manager=self.db,
        )
        if started:
            self._set_page_status(_("Preparing…"), role="muted")

    def compute(self):
        self._usage_workspace_active = True
        self._usage_server_refresh_pending = False
        self.usage_compute_service.request_compute(
            access_allowed=self._access_allowed,
            access_reason=self._access_reason,
            receipts_path=self._receipts_path,
            beginning_path=self._beginning_path,
            db_manager=self.db,
        )

    def _on_compute_busy_changed(self, busy: bool):
        self._apply_access_state()
        current_rows = self.model.rowCount() if hasattr(self, "model") else 0
        self._safe_set_page_table_summary(
            current_rows, loading=bool(busy), status_text=self.lbl_status.text()
        )

    def _on_compute_status_changed(self, message):
        if message:
            self._set_page_table_summary(
                self.proxy.rowCount(),
                loading=self._compute_is_running(),
                status_text=str(message),
            )

    def _on_compute_result_ready(self, payload):
        if isinstance(payload, UsageComputePayload):
            rows = payload.rows
            status_text = payload.status_text
        else:
            rows = list(getattr(payload, "rows", []) or [])
            status_text = str(getattr(payload, "status_text", "") or "")
        try:
            self._model_replace_in_progress = True
            self.model.replace_rows_preserving_user_inputs(rows)
        finally:
            self._model_replace_in_progress = False
        self._usage_workspace_active = bool(
            self._receipts_path or self._beginning_path or self.model.rowCount() > 0
        )
        self.proxy.set_hide_total_zero(
            self.usage_workspace_service.hide_total_zero_enabled(self.db)
        )
        self.proxy.invalidateFilter()
        self._open_persistent_editors()
        self._size_columns()
        self._safe_set_page_table_summary(
            self.proxy.rowCount(), loading=False, status_text=status_text
        )

    def _on_compute_error_raised(self, message: str):
        self._usage_server_refresh_pending = False
        self.model.replace_rows([])
        self._safe_set_page_table_summary(
            0,
            loading=False,
            error_message=str(message or _("Usage calculation failed.")),
        )

    def _on_hide_total_zero_toggled(self, checked: bool) -> None:
        self.usage_workspace_service.set_hide_total_zero_enabled(self.db, bool(checked))
        self.proxy.set_hide_total_zero(bool(checked))
        self.proxy.invalidateFilter()
        self._open_persistent_editors()
        self._size_columns()
        status = (
            _("Zero-total rows are hidden.")
            if checked
            else _("Zero-total rows are visible.")
        )
        self._safe_set_page_table_summary(
            self.proxy.rowCount(),
            loading=self._compute_is_running(),
            status_text=status,
        )

    def _on_usage_model_data_changed(self, top_left, bottom_right, _roles=None):
        if getattr(self, "_model_replace_in_progress", False):
            return
        try:
            if top_left.column() <= COL_H <= bottom_right.column():
                self._usage_workspace_active = True
                self._usage_input_dirty = True
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "UsagePage._on_usage_model_data_changed fallback failed", exc_info=True
            )

    def _open_persistent_editors(self):
        self.table.setItemDelegateForColumn(COL_H, self.delegate)
        for r in range(self.proxy.rowCount()):
            ix = self.proxy.index(r, COL_H)
            self.table.openPersistentEditor(ix)

    def _print_table(self):
        decision = self.usage_workspace_service.evaluate_preview_request(
            access_allowed=self._access_allowed,
            access_reason=self._access_reason,
            row_count=self.proxy.rowCount(),
        )
        if not decision.allowed:
            self._set_page_status(decision.message, role="warning")
            return
        context = self.usage_workspace_service.build_print_context(
            usage_print_service=self.usage_print_service,
            model=self.proxy,
            headers=usage_print_headers(),
            numeric_columns=(COL_R, COL_B, COL_T, COL_H, COL_U),
            column_ratios=self.COL_RATIOS,
            db_manager=self.db,
        )
        shown = self.usage_print_service.show_preview(self, context=context)
        if not shown:
            self._set_page_status(_("No usage rows to preview."), role="warning")


UsageController = UsageControllerMixin
__all__ = ["UsageControllerMixin", "UsageController"]
