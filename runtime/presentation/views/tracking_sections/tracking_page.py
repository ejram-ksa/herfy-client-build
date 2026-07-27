from __future__ import annotations
from typing import ClassVar

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

from PyQt5.QtCore import QTimer
from runtime.presentation.tables.metrics import fit_table_height_to_rows
import logging
import time
from collections.abc import Callable
from PyQt5.QtWidgets import QApplication, QLineEdit
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.application.services.tracking_runtime import tracking_baseline

logger = logging.getLogger(__name__)


class TrackingDataControllerMixin:
    _load_token = 0

    def _on_app_state_tracking_changed(self, domain, payload=None) -> None:
        if not self._is_alive():
            return
        if str(domain or "").strip().lower() != "tracking":
            return
        if time.monotonic() < float(
            getattr(self, "_suppress_state_refresh_until", 0.0) or 0.0
        ):
            return
        self._pending_state_payload = payload
        try:
            if not self.isVisible():
                return
            self._state_refresh_timer.start(120)
        except RuntimeError:
            logger.debug(
                "TrackingPage._on_app_state_tracking_changed skipped: timer unavailable"
            )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "TrackingPage._on_app_state_tracking_changed failed", exc_info=True
            )

    def _run_state_refresh(self) -> None:
        if not self._is_alive():
            return
        payload = self._pending_state_payload
        payload = payload if isinstance(payload, dict) else {}
        try:
            preloaded = payload.get("preloaded")
            delta = payload.get("tracking_delta")
            if preloaded is not None:
                tracking_baseline.publish(preloaded, source="app_state")
                self.load_tracked_products(show_busy=False)
                return
            if isinstance(delta, dict) and delta.get("applied"):
                if not tracking_baseline.snapshot().ready:
                    self._pending_tracking_delta = dict(delta)
                    return
                self._apply_tracking_delta(delta)
                return
            self.load_tracked_products(show_busy=False)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage._run_state_refresh failed", exc_info=True)

    def _apply_tracking_delta(self, delta: dict) -> None:
        rows = self.tracking_service.merge_visible_delta_rows(
            list(getattr(self, "tracked_products", []) or []),
            delta,
            catalog_rows=list(getattr(self, "_product_catalog_rows", []) or []),
        )
        self._apply_rows(rows)

    def _is_user_editing(self) -> bool:
        try:
            focus_widget = QApplication.focusWidget()
            return isinstance(focus_widget, QLineEdit) and focus_widget in {
                getattr(self, "product_entry", None),
                getattr(self, "qty_entry", None),
            }
        except UI_OPERATION_EXCEPTIONS:
            return False

    def _is_current_load_token(self, token: int) -> bool:
        return (
            int(token) == int(getattr(self, "_load_token", -1))
            and self._is_alive()
            and (not bool(getattr(self, "_disposed", False)))
        )

    def _show_busy(self, text: str) -> None:
        """Show non-blocking inline tracking busy state.

        Tracking must not open the small floating progress popup because it
        interrupts resize/typing workflows and looks like the black in-app
        overlay reported during visual QA.  Long-running tracking operations
        now use the page status label/table disabled state only.
        """
        try:
            if not self.isVisible():
                return
            self._busy_depth += 1
            self._set_page_status(str(text or _("Working...")), role="muted")
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage._show_busy inline state failed", exc_info=True)

    def _hide_busy(self) -> None:
        """Clear non-blocking inline tracking busy state."""
        try:
            self._busy_depth = max(0, int(self._busy_depth) - 1)
            if self._busy is not None:
                self._busy.hide()
                self._busy = None
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage._hide_busy inline cleanup failed", exc_info=True)

    def _set_table_enabled(self, enabled: bool) -> None:
        try:
            self.table_view.setEnabled(enabled)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage._set_table_enabled failed", exc_info=True)

    def _begin_async_action(self, *, label: str, disable_add: bool = False) -> None:
        self._show_busy(label)
        self._set_page_status(label, role="muted")
        self._set_table_enabled(False)
        if disable_add:
            self.btn_add.setEnabled(False)

    def _finish_async_action(self, *, restore_add_button: bool = True) -> None:
        self._hide_busy()
        self._action_running = False
        self._set_table_enabled(True)
        self._set_page_status("", role="muted")
        if restore_add_button:
            self._update_branch_ui_state()

    def _handle_async_success(
        self, *, message: str, refresh: bool = True, reset_form: bool = False
    ) -> None:
        self._suppress_state_refresh_until = time.monotonic() + 0.8
        self._finish_async_action()
        self._info(_("Success"), message)
        if refresh:
            self.load_tracked_products(show_busy=False)
        if reset_form:
            self._reset_tracking_form()

    def _handle_async_error(self, message: str) -> None:
        self._finish_async_action()
        self._warn(_("Error"), message or _("Operation failed."))

    def _run_tracking_action(
        self,
        *,
        label: str,
        worker_fn: Callable,
        success_message: str,
        failure_message: str,
        reset_form: bool = False,
    ) -> None:
        if not self._is_alive():
            return
        if getattr(self, "_action_running", False):
            self._set_page_status(
                _("Please wait for the current operation to finish."), role="muted"
            )
            return
        self._action_running = True
        self._action_token = int(getattr(self, "_action_token", 0) or 0) + 1
        action_token = self._action_token
        self._begin_async_action(label=label, disable_add=True)

        def _is_current_action() -> bool:
            return self._is_alive() and action_token == int(
                getattr(self, "_action_token", -1) or -1
            )

        def _done(result):
            if not _is_current_action():
                return
            ok, message, error = self._normalize_action_result(result)
            if ok:
                self._handle_async_success(
                    message=message or success_message, reset_form=reset_form
                )
                return
            self._handle_async_error(error or failure_message)

        def _error(message: str):
            if not _is_current_action():
                return
            self._handle_async_error(message or failure_message)

        worker = self._worker_registry.start(
            worker_fn,
            on_result=_done,
            on_error=_error,
            on_finished=lambda: setattr(self, "_action_running", False),
            operation_key="tracking:action",
            scope_checker=_is_current_action,
        )
        if worker is None:
            self._action_running = False
            self._finish_async_action()
            self._set_page_status(
                _("Please wait for the current operation to finish."), role="muted"
            )

    @staticmethod
    def _normalize_action_result(result) -> tuple[bool, str, str]:
        if isinstance(result, list | tuple) and len(result) == 3:
            ok, message, error = result
            return (bool(ok), str(message or ""), str(error or ""))
        return (False, "", "")

    def _auto_refresh_tick(self) -> None:
        try:
            if self.isVisible():
                self.load_tracked_products(show_busy=False)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Tracking auto-refresh skipped", exc_info=True)

    def load_tracked_products(
        self, preloaded: list | None = None, show_busy: bool = True
    ) -> None:
        if preloaded is not None:
            tracking_baseline.publish(preloaded, source="page_preload")
        snapshot = tracking_baseline.snapshot()
        if snapshot.ready and not show_busy:
            self._load_token += 1
            token = self._load_token
            rows = self.tracking_service.filter_rows_for_active_branch(
                list(snapshot.rows)
            )
            rows = self.tracking_service.enrich_rows_for_display(
                rows, list(getattr(self, "_product_catalog_rows", []) or [])
            )
            if self._is_current_load_token(token):
                self._apply_rows(rows)
                pending_delta = getattr(self, "_pending_tracking_delta", None)
                if isinstance(pending_delta, dict):
                    self._pending_tracking_delta = None
                    self._apply_tracking_delta(pending_delta)
            return
        if getattr(self, "_loading", False):
            self._load_pending = True
            self._load_pending_show_busy = bool(
                getattr(self, "_load_pending_show_busy", False) or show_busy
            )
            self._set_page_status(_("Updating..."), role="muted")
            return
        if not show_busy and self._is_user_editing():
            return
        self._load_token += 1
        token = self._load_token
        self._loading = True
        self._last_load_show_busy = bool(show_busy)
        self._begin_load_ui(show_busy=show_busy)

        def _load_tracking_payload():
            cloud_mode = self.tracking_service.is_cloud_mode()
            rows = self.tracking_service.fetch_rows(
                cloud=cloud_mode, force_network=bool(show_busy)
            )
            catalog = self.tracking_service.catalog_products(
                force_network=bool(show_busy)
            )
            return {"rows": rows, "catalog": catalog}

        worker = self._worker_registry.start(
            _load_tracking_payload,
            on_result=lambda result: self._on_load_result(token, result),
            on_error=lambda message: self._on_load_error(token, message),
            on_finished=lambda: self._on_load_finished(token),
            operation_key="tracking:load",
            scope_checker=lambda: self._is_current_load_token(token),
        )
        if worker is None:
            self._loading = False
            self._finish_load_ui()
            self._load_pending = True
            self._load_pending_show_busy = bool(
                getattr(self, "_load_pending_show_busy", False) or show_busy
            )
            QTimer.singleShot(
                120, lambda: self.load_tracked_products(show_busy=show_busy)
            )

    def _begin_load_ui(self, *, show_busy: bool) -> None:
        self._set_table_enabled(False)
        self._update_table_summary(loading=True)
        if show_busy:
            self._show_busy(_("Loading..."))
            self._set_page_status(_("Loading..."), role="muted")
            return
        self._set_page_status(_("Updating..."), role="muted")

    def _finish_load_ui(self) -> None:
        if not self._is_alive():
            return
        self._set_table_enabled(True)
        self._loading = False
        self._hide_busy()

    def _on_load_result(self, token: int, result) -> None:
        if not self._is_current_load_token(token):
            return
        payload = result if isinstance(result, dict) else {"rows": result or []}
        catalog = payload.get("catalog")
        if catalog is not None:
            self.update_completer(list(catalog or []))
        self._apply_rows(list(payload.get("rows") or []))
        pending_delta = getattr(self, "_pending_tracking_delta", None)
        if isinstance(pending_delta, dict):
            self._pending_tracking_delta = None
            self._apply_tracking_delta(pending_delta)

    def _on_load_error(self, token: int, message: str) -> None:
        if not self._is_current_load_token(token):
            return
        error_message = message or _("Failed to load data.")
        self._set_page_status(error_message, role="error")
        self._update_table_summary(loading=False, error_message=error_message)
        self._finish_load_ui()
        if getattr(self, "_last_load_show_busy", True):
            self._warn(_("Error"), error_message)

    def _on_load_finished(self, token: int) -> None:
        if not self._is_current_load_token(token):
            return
        self._finish_load_ui()
        self._update_table_summary(
            loading=False, truncated=bool(self.tracking_service.items_truncated())
        )
        if not self.tracking_service.items_truncated() and self.tracked_products:
            self._set_page_status("", role="muted")
        if getattr(self, "_load_pending", False):
            pending_show_busy = bool(getattr(self, "_load_pending_show_busy", False))
            self._load_pending = False
            self._load_pending_show_busy = False
            QTimer.singleShot(
                120, lambda: self.load_tracked_products(show_busy=pending_show_busy)
            )

    def _reconcile_visible_rows_with_catalog(
        self, catalog_rows: list | None = None
    ) -> None:
        rows = list(getattr(self, "tracked_products", []) or [])
        if not rows:
            return
        enriched = self.tracking_service.enrich_rows_for_display(
            rows, list(catalog_rows or [])
        )
        if enriched != rows:
            self._apply_rows(enriched)

    def _apply_rows(self, rows: list) -> None:
        if not self._is_alive():
            return
        catalog_rows = list(getattr(self, "_product_catalog_rows", []) or [])
        self.tracked_products = self.tracking_service.enrich_rows_for_display(
            list(rows or []), catalog_rows
        )
        self.model.load_data(self.tracked_products)
        fit_table_height_to_rows(self.table_view, min_rows=5, max_rows=18)
        self._size_tracking_columns()
        self._update_table_summary(
            loading=False, truncated=bool(self.tracking_service.items_truncated())
        )
        self._refresh_completer_if_needed()

    def load_product_catalog(self, *, force_network: bool = False) -> None:
        if not self._is_alive():
            return
        if getattr(self, "_catalog_loading", False):
            self._catalog_load_pending_force_network = bool(
                getattr(self, "_catalog_load_pending_force_network", False)
                or force_network
            )
            return
        self._catalog_loading = True
        self._catalog_load_token = int(getattr(self, "_catalog_load_token", 0) or 0) + 1
        token = self._catalog_load_token
        worker = self._worker_registry.start(
            lambda: self.tracking_service.catalog_products(
                force_network=bool(force_network)
            ),
            on_result=lambda products: self._on_catalog_loaded(token, products),
            on_error=lambda message: logger.debug(
                "Product catalog load skipped: %s", message
            ),
            on_finished=lambda: self._on_catalog_load_finished(token),
            operation_key="tracking:catalog",
            scope_checker=lambda: self._is_alive()
            and token == int(getattr(self, "_catalog_load_token", -1) or -1),
        )
        if worker is None:
            self._catalog_loading = False
            self._catalog_load_pending_force_network = bool(
                getattr(self, "_catalog_load_pending_force_network", False)
                or force_network
            )
            QTimer.singleShot(
                120, lambda: self.load_product_catalog(force_network=force_network)
            )

    def _on_catalog_load_finished(self, token: int) -> None:
        """Release catalog-load gate and run one coalesced pending request."""
        if token != int(getattr(self, "_catalog_load_token", -1) or -1):
            return
        self._catalog_loading = False
        if getattr(self, "_catalog_load_pending_force_network", False):
            self._catalog_load_pending_force_network = False
            QTimer.singleShot(
                120, lambda: self.load_product_catalog(force_network=True)
            )

    def _on_catalog_loaded(self, token: int, products) -> None:
        if not self._is_alive() or token != int(
            getattr(self, "_catalog_load_token", -1) or -1
        ):
            return
        self.update_completer(list(products or []))

    def _update_table_summary(
        self, *, loading: bool, truncated: bool = False, error_message: str = ""
    ) -> None:
        self._safe_set_page_table_summary(
            len(getattr(self, "tracked_products", []) or []),
            loading=loading,
            truncated=truncated,
            error_message=error_message,
        )

    def _refresh_completer_if_needed(self) -> None:
        try:
            cache_size = len(getattr(self.db_manager, "_stored_name_cache", {}) or {})
            if cache_size == getattr(self, "_completer_cache_size", -1):
                return
            self._completer_cache_size = cache_size
            self.update_completer()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "TrackingPage._refresh_completer_if_needed failed", exc_info=True
            )


from runtime.presentation.layout.helpers import set_minimum_width, set_size_policy
from runtime.presentation.widgets import polish_button, polish_status_label
from runtime.presentation.layout.profiles import profile_for_widget
from runtime.presentation.layout.metrics import UI_METRICS
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtGui import QIntValidator
from PyQt5.QtCore import QDate, Qt
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.helpers import set_grid_column_stretch



class TrackingFormBuilderMixin:

    def _build_controls_card(self) -> None:
        S = self._S
        self.controls_card = QFrame()
        self.controls_card.setObjectName("GridPanel")
        set_size_policy(self.controls_card, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.main_layout.addWidget(self.controls_card)
        controls_layout = QGridLayout(self.controls_card)
        _layout_rules.set_layout_contents_margins(
            controls_layout, S(18), S(16), S(18), S(16)
        )
        _layout_rules.set_layout_horizontal_spacing(controls_layout, S(14))
        _layout_rules.set_layout_vertical_spacing(controls_layout, S(8))
        set_grid_column_stretch(controls_layout, 0, 1)
        self._build_status_label()
        self._build_toolbar()
        controls_layout.addWidget(self.toolbar_frame, 0, 0, 1, 1)
        controls_layout.addWidget(self._status_lbl, 1, 0, 1, 1)

    def _build_status_label(self) -> None:
        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("MutedStatusLabel")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._status_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        set_size_policy(self._status_lbl, QSizePolicy.Expanding, QSizePolicy.Fixed)
        polish_status_label(self._status_lbl, role="muted")

    def _build_toolbar(self) -> None:
        S = self._S
        self.toolbar_frame = QFrame()
        self.toolbar_frame.setObjectName("TrackingToolbarCard")
        set_size_policy(self.toolbar_frame, QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toolbar_lay = QGridLayout(self.toolbar_frame)
        _layout_rules.set_layout_contents_margins(self.toolbar_lay, 0, 0, 0, 0)
        _layout_rules.set_layout_horizontal_spacing(self.toolbar_lay, S(14))
        _layout_rules.set_layout_vertical_spacing(self.toolbar_lay, S(8))
        self._build_form_widgets()
        self._build_toolbar_fields()
        self._tracking_toolbar_mode = ""
        self._apply_responsive_toolbar(force=True)

    def _build_form_widgets(self) -> None:
        self.cmb_view_branch = self._create_branch_combo()
        self.product_entry = self._create_product_entry()
        self.qty_entry = self._create_quantity_entry()
        date_format = self.db_manager.get_setting("date_format", "yyyy-MM-dd")
        self.prod_edit = self._create_date_edit(_("Production date"), date_format)
        self.exp_edit = self._create_date_edit(_("Expiry date"), date_format)
        self.btn_add = self._create_add_button()

    def _create_branch_combo(self) -> QComboBox:
        S = self._S
        combo = QComboBox()
        combo.setToolTip(_("Restaurant branch"))
        set_minimum_width(combo, S(96))
        set_size_policy(combo, QSizePolicy.Expanding, QSizePolicy.Fixed)
        return combo

    def _create_product_entry(self) -> QLineEdit:
        S = self._S
        entry = QLineEdit()
        entry.setToolTip(_("Material number or material name"))
        entry.setPlaceholderText(_("Search by material number or material name"))
        entry.setAccessibleName(_("Material number or material name"))
        entry.setClearButtonEnabled(True)
        set_minimum_width(entry, S(160))
        set_size_policy(entry, QSizePolicy.Expanding, QSizePolicy.Fixed)
        return entry

    def _create_quantity_entry(self) -> QLineEdit:
        S = self._S
        entry = QLineEdit()
        entry.setToolTip(_("Quantity"))
        entry.setAccessibleName(_("Quantity"))
        entry.setValidator(QIntValidator(1, 999999))
        entry.setPlaceholderText(_("Qty"))
        entry.setClearButtonEnabled(True)
        set_minimum_width(entry, S(72))
        set_size_policy(entry, QSizePolicy.Expanding, QSizePolicy.Fixed)
        return entry

    def _create_date_edit(self, label: str, date_format: str) -> QDateEdit:
        S = self._S
        edit = QDateEdit()
        edit.setToolTip(label)
        edit.setAccessibleName(label)
        edit.setCalendarPopup(True)
        edit.setDisplayFormat(date_format)
        edit.setDate(QDate.currentDate())
        set_minimum_width(edit, S(122))
        set_size_policy(edit, QSizePolicy.Expanding, QSizePolicy.Fixed)
        return edit

    def _create_add_button(self) -> QPushButton:
        S = self._S
        button = QPushButton(_("Add/Update"))
        button.setAccessibleName(_("Save item"))
        button.setAccessibleDescription(_("Add or update tracked product"))
        button.setShortcut("Ctrl+Return")
        polish_button(
            button,
            role="primary",
            min_width=S(UI_METRICS.compact_button_min_width),
            min_height=S(40),
            cursor=Qt.PointingHandCursor,
        )
        return button

    def _build_toolbar_fields(self) -> None:
        self.cmb_view_branch.setObjectName("TrackingBranchInput")
        self.product_entry.setObjectName("TrackingProductInput")
        self.prod_edit.setObjectName("TrackingDateInput")
        self.exp_edit.setObjectName("TrackingDateInput")
        self.qty_entry.setObjectName("TrackingQuantityInput")
        self.btn_add.setObjectName("TrackingAddButton")
        self.branch_field = self._build_toolbar_field(
            _("Restaurant branch"), self.cmb_view_branch
        )
        self.product_field = self._build_toolbar_field(
            _("Material number or material name"), self.product_entry
        )
        self.production_field = self._build_toolbar_field(
            _("Production date"), self.prod_edit
        )
        self.expiry_field = self._build_toolbar_field(_("Expiry date"), self.exp_edit)
        self.quantity_field = self._build_toolbar_field(_("Quantity"), self.qty_entry)
        self.action_field = self.btn_add
        self._tracking_fields = [
            self.branch_field,
            self.product_field,
            self.production_field,
            self.expiry_field,
            self.quantity_field,
            self.action_field,
        ]
        self._tracking_inputs = [
            self.cmb_view_branch,
            self.product_entry,
            self.prod_edit,
            self.exp_edit,
            self.qty_entry,
            self.btn_add,
        ]
        self._apply_control_size_policies(
            "wide", profile_for_widget(self, app=QApplication.instance())
        )

    def _build_toolbar_field(self, label_text: str, control: QWidget) -> QFrame:
        field = QFrame()
        field.setObjectName("TrackingFieldGroup")
        field.setProperty("innerPanel", True)
        set_size_policy(field, QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(field)
        _layout_rules.set_layout_contents_margins(layout, 0, 0, 0, 0)
        _layout_rules.set_layout_spacing(layout, self._S(8))
        label = QLabel(label_text)
        label.setObjectName("FlatFieldLabel")
        label.setBuddy(control)
        layout.addWidget(label)
        layout.addWidget(control)
        return field


from runtime.presentation.dialogs.confirm_delete_tracked_product import confirm_tracked_product_delete
from runtime.presentation.dialogs.edit_tracked_product import EditTrackedProductDialog
from runtime.presentation.widgets import clear_input_state, set_input_state



class TrackingFormControllerMixin:
    _load_token = 0

    def _warn_missing_remote_id(self) -> None:
        self._warn(
            _("Error"),
            _("Server record id is missing. Refresh shelf-life data and try again."),
        )
        try:
            self.load_tracked_products(show_busy=True)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage._warn_missing_remote_id failed", exc_info=True)

    def _selected_tracked_product(self, row: int, *, action: str) -> dict | None:
        product_id = self.model.get_product_id(row)
        if product_id is None:
            self._warn(_("Error"), _("Food item was not found."))
            return None
        selection = self.tracking_service.select_record_for_action(
            product_id=product_id, rows=list(self.tracked_products or []), action=action
        )
        if selection.record is not None:
            return selection.record
        if selection.requires_refresh:
            self._warn_missing_remote_id()
            return None
        self._warn(_("Error"), selection.message or _("Food item was not found."))
        return None

    def _clear_tracking_form_feedback(self, *args) -> None:
        del args
        fields = (
            (
                getattr(self, "product_entry", None),
                _("Material number or material name"),
            ),
            (getattr(self, "qty_entry", None), _("Quantity")),
            (getattr(self, "prod_edit", None), _("Production date")),
            (getattr(self, "exp_edit", None), _("Expiry date")),
        )
        for widget, tooltip in fields:
            clear_input_state(widget, tooltip=tooltip)

    def _apply_tracking_form_error(self, message: str) -> None:
        text = str(message or "").strip()
        product_text = str(self.product_entry.text() or "").strip()
        quantity_text = str(self.qty_entry.text() or "").strip()
        if not product_text:
            self._mark_form_error(self.product_entry, text, focus=True)
        if not quantity_text or _("Quantity") in text:
            self._mark_form_error(self.qty_entry, text, focus=bool(product_text))
        if self._is_date_error(text):
            self._mark_form_error(self.prod_edit, text)
            self._mark_form_error(self.exp_edit, text, focus=True)
        if self._is_catalog_warning(text):
            set_input_state(self.product_entry, "warning", tooltip=text)
            self.product_entry.setFocus()

    @staticmethod
    def _mark_form_error(widget, text: str, *, focus: bool = False) -> None:
        set_input_state(widget, "error", tooltip=text)
        if focus:
            widget.setFocus()

    @staticmethod
    def _message_contains_any(text: str, *needles: str) -> bool:
        return any((str(needle or "") in text for needle in needles if needle))

    @classmethod
    def _is_date_error(cls, text: str) -> bool:
        return cls._message_contains_any(
            text,
            _("Production date cannot be after expiry date."),
            _("Invalid date format!"),
        )

    @classmethod
    def _is_catalog_warning(cls, text: str) -> bool:
        return cls._message_contains_any(
            text,
            _("product catalog"),
            _("This food item was not found in the product catalog."),
        )

    def _reset_tracking_form(self) -> None:
        self.product_entry.clear()
        self.qty_entry.clear()
        self.prod_edit.setDate(QDate.currentDate())
        self.exp_edit.setDate(QDate.currentDate())
        self._clear_tracking_form_feedback()

    def add_product(self) -> None:
        prepared, error_message = self.tracking_form_service.prepare_create(
            product_text=self.product_entry.text(),
            quantity_text=self.qty_entry.text(),
            production_date=self.prod_edit.date().toString("yyyy-MM-dd"),
            expiry_date=self.exp_edit.date().toString("yyyy-MM-dd"),
        )
        if error_message or prepared is None:
            self._reject_tracking_form(
                error_message or _("Food item details and quantity are required.")
            )
            return

        def _save_logic():
            return self.tracking_service.create_or_merge_item(
                material_number=prepared.material_number,
                quantity=prepared.quantity,
                production_date=prepared.production_date,
                expiry_date=prepared.expiry_date,
                current_rows=list(self.tracked_products or []),
            )

        try:
            self._run_tracking_action(
                label=_("Saving..."),
                worker_fn=_save_logic,
                success_message=_("Saved."),
                failure_message=_("Failed to save."),
                reset_form=True,
            )
        except UI_OPERATION_EXCEPTIONS as exc:
            logger.error("Failed to add product: %s", exc)
            self._error(_("Error"), _("Failed to save food item."))

    def _reject_tracking_form(self, message: str) -> None:
        self._apply_tracking_form_error(message)
        self._warn(_("Error"), message)

    def edit_tracked_product(self, row: int) -> None:
        product = self._selected_tracked_product(row, action="update")
        if not product:
            return
        dialog = EditTrackedProductDialog(self.db_manager, product, self)
        if not dialog.exec_():
            return
        prepared, error_message = self.tracking_form_service.prepare_update(
            quantity_text=dialog.qty_edit.text(),
            production_date=dialog.prod_edit.date().toString("yyyy-MM-dd"),
            expiry_date=dialog.exp_edit.date().toString("yyyy-MM-dd"),
        )
        if error_message or prepared is None:
            self._warn(
                _("Error"), error_message or _("Quantity must be a positive integer.")
            )
            return

        def _update_logic():
            return self.tracking_service.update_item(
                product,
                quantity=prepared.quantity,
                production_date=prepared.production_date,
                expiry_date=prepared.expiry_date,
            )

        self._run_tracking_action(
            label=_("Updating..."),
            worker_fn=_update_logic,
            success_message=_("Updated."),
            failure_message=_("Failed to update."),
        )

    def delete_tracked_product(self, row: int) -> None:
        product = self._selected_tracked_product(row, action="delete")
        if not product:
            return
        if not confirm_tracked_product_delete(self.db_manager, product, self):
            return
        self._run_tracking_action(
            label=_("Deleting..."),
            worker_fn=lambda: self.tracking_service.delete_item(product),
            success_message=_("Deleted."),
            failure_message=_("Failed to delete."),
        )

    def reset_after_logout(self) -> None:
        try:
            self._load_token += 1
            self._action_token = int(getattr(self, "_action_token", 0) or 0) + 1
            self._catalog_load_token = (
                int(getattr(self, "_catalog_load_token", 0) or 0) + 1
            )
            self._loading = False
            self._load_pending = False
            self._load_pending_show_busy = False
            self._catalog_loading = False
            self._catalog_load_pending_force_network = False
            self._action_running = False
            registry = getattr(self, "_worker_registry", None)
            if registry is not None:
                registry.cancel_all()
            self._hide_busy()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "TrackingPage.reset_after_logout cleanup failed", exc_info=True
            )
        try:
            self.cmb_view_branch.hide()
            self.cmb_view_branch.blockSignals(True)
            self.cmb_view_branch.clear()
            self.cmb_view_branch.blockSignals(False)
            self.tracked_products = []
            self.model.load_data([])
            self._update_table_summary(loading=False)
            self._set_page_status("", role="muted")
            self.btn_add.setEnabled(False)
            self.btn_add.setToolTip(_("Login required"))
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage.reset_after_logout failed", exc_info=True)


from runtime.presentation.layout.helpers import (
    set_minimum_height,
    set_section_resize_mode,
    set_stretch_last_section,
)
from runtime.presentation.views.tracking_support import toolbar_layout_spec
from runtime.presentation.widgets import refresh_widget_style
from runtime.presentation.tables.metrics import fit_table_columns
from runtime.presentation.tables.headers import COL_NAME, COL_STATUS
from runtime.presentation.layout.profiles import (
    ResponsiveProfile,
    apply_profile_properties,
    fluid_content_width,
    layout_mode_for_width,
)
from PyQt5.QtWidgets import QHeaderView
from PyQt5.QtWidgets import QAbstractItemView



class TrackingResponsiveLayoutMixin:

    def _apply_control_size_policies(
        self, mode: str, profile: ResponsiveProfile
    ) -> None:
        """Apply fluid control policies without max-width or fixed-height clamps."""
        try:
            height = int(profile.control_height)
            for widget in self._tracking_inputs:
                set_minimum_height(widget, height)
                widget.setMinimumWidth(0)
                set_size_policy(widget, QSizePolicy.Expanding, QSizePolicy.Fixed)
            if mode == "wide":
                set_minimum_width(self.cmb_view_branch, 94)
                set_minimum_width(self.product_entry, 210)
                for date_edit in (self.prod_edit, self.exp_edit):
                    set_minimum_width(date_edit, 98)
                set_minimum_width(self.qty_entry, 54)
                set_minimum_width(self.btn_add, 82)
            else:
                set_minimum_width(self.cmb_view_branch, 88)
                set_minimum_width(self.product_entry, 150)
                for date_edit in (self.prod_edit, self.exp_edit):
                    set_minimum_width(date_edit, 94)
                set_minimum_width(self.qty_entry, 50)
                set_minimum_width(self.btn_add, 74)
            set_size_policy(
                self.cmb_view_branch, QSizePolicy.Preferred, QSizePolicy.Fixed
            )
            set_size_policy(
                self.product_entry, QSizePolicy.Expanding, QSizePolicy.Fixed
            )
            for date_edit in (self.prod_edit, self.exp_edit):
                set_size_policy(date_edit, QSizePolicy.Expanding, QSizePolicy.Fixed)
            set_size_policy(self.qty_entry, QSizePolicy.Preferred, QSizePolicy.Fixed)
            set_size_policy(self.btn_add, QSizePolicy.Preferred, QSizePolicy.Fixed)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage control sizing failed", exc_info=True)

    def apply_responsive_profile(
        self, profile: ResponsiveProfile | None = None, mode: str | None = None
    ) -> None:
        profile = profile or profile_for_widget(self, app=QApplication.instance())
        apply_profile_properties(self, profile)
        _layout_rules.set_layout_contents_margins(
            self.main_layout,
            profile.page_margin,
            profile.page_margin,
            profile.page_margin,
            profile.page_margin,
        )
        _layout_rules.set_layout_spacing(self.main_layout, profile.gap)
        self._apply_responsive_toolbar(force=True, profile=profile, semantic_mode=mode)
        self._size_tracking_columns()

    def _apply_responsive_toolbar(
        self,
        *,
        force: bool = False,
        profile: ResponsiveProfile | None = None,
        semantic_mode: str | None = None,
    ) -> None:
        try:
            profile = profile or profile_for_widget(self, app=QApplication.instance())
            available_width = max(
                1,
                fluid_content_width(
                    self.toolbar_frame, fallback=int(profile.width or self.width() or 0)
                )
                - int(profile.dialog_margin * 2),
            )
            semantic = semantic_mode or layout_mode_for_width(available_width)
            mode = "wide" if str(semantic or "").lower() == "wide" else "compact"
            if not force and mode == getattr(self, "_tracking_toolbar_mode", ""):
                return
            self._tracking_toolbar_mode = mode
            self._tracking_semantic_mode = semantic
            self._apply_control_size_policies(mode, profile)
            spec = toolbar_layout_spec(mode)
            for widget in self._tracking_fields:
                self.toolbar_lay.removeWidget(widget)
            for column in range(6):
                set_grid_column_stretch(self.toolbar_lay, column, 0)
            for placement in spec.placements:
                widget = getattr(self, placement.name)
                if placement.name == "action_field":
                    self.toolbar_lay.addWidget(
                        widget,
                        placement.row,
                        placement.column,
                        placement.row_span,
                        placement.column_span,
                        Qt.AlignBottom,
                    )
                else:
                    self.toolbar_lay.addWidget(
                        widget,
                        placement.row,
                        placement.column,
                        placement.row_span,
                        placement.column_span,
                    )
            for column, stretch in enumerate(spec.column_stretches):
                set_grid_column_stretch(self.toolbar_lay, column, stretch)
            self.toolbar_frame.setProperty("toolbarMode", mode)
            self.toolbar_frame.setProperty("touchUi", profile.touch_mode)
            refresh_widget_style(self.toolbar_frame)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage responsive toolbar layout failed", exc_info=True)

    def _apply_responsive_table_visibility(self, profile: ResponsiveProfile) -> bool:
        for column in range(self.model.columnCount()):
            self.table_view.setColumnHidden(column, False)
        self.table_view.setProperty("portraitSummary", False)
        return False

    def _size_tracking_columns(self) -> None:
        profile = profile_for_widget(self, app=QApplication.instance())
        self._apply_responsive_table_visibility(profile)
        if profile.is_narrow:
            ratios = self.COMPACT_COL_RATIOS
            minimums = self.COMPACT_COL_MIN_WIDTHS
        elif profile.is_tablet:
            ratios = self.TABLET_COL_RATIOS
            minimums = self.TABLET_COL_MIN_WIDTHS
        else:
            ratios = self.TABLE_COL_RATIOS
            minimums = self.TABLE_COL_MIN_WIDTHS
        fit_table_columns(
            self.table_view,
            ratios,
            min_widths=[self._S(value) for value in minimums],
            stretch_columns=(COL_NAME, COL_STATUS),
            allow_overflow=False,
        )
        self._lock_tracking_table_layout()

    def _lock_tracking_table_layout(self) -> None:
        try:
            header = self.table_view.horizontalHeader()
            header.setSectionsMovable(False)
            header.setSectionsClickable(False)
            set_stretch_last_section(header, False)
            _layout_rules.set_header_cascading_section_resizes(header, False)
            available = max(1, int(self.table_view.viewport().width()))
            total_width = sum(
                (
                    max(1, int(self.table_view.columnWidth(column)))
                    for column in range(self.model.columnCount())
                )
            )
            for column in range(self.model.columnCount()):
                set_section_resize_mode(header, column, QHeaderView.Interactive)
            if total_width <= available:
                for column in (COL_NAME, COL_STATUS):
                    set_section_resize_mode(header, column, QHeaderView.Stretch)
            self.table_view.setDragDropMode(QAbstractItemView.NoDragDrop)
            self.table_view.setSortingEnabled(False)
            self.table_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.table_view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            self.table_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "TrackingPage._lock_tracking_table_layout failed", exc_info=True
            )


from runtime.presentation.layout.helpers import set_minimum_section_size
from runtime.presentation.widgets import create_table_heading
from runtime.presentation.tables.metrics import configure_responsive_table
from runtime.presentation.tables.tracking_model import TrackedProductsTableModel
from runtime.presentation.tables.delegates import ActionDelegate, ProgressBarDelegate
from PyQt5.QtWidgets import QTableView



class TrackingTableBuilderMixin:

    def _build_table_card(self) -> None:
        S = self._S
        self.model = TrackedProductsTableModel([], self.db_manager)
        self.table_view = self._create_table_view()
        self.table_card = QFrame()
        self.table_card.setObjectName("GridPanel")
        set_size_policy(self.table_card, QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.main_layout.addWidget(self.table_card, 1)
        table_layout = QVBoxLayout(self.table_card)
        _layout_rules.set_layout_contents_margins(
            table_layout, S(18), S(18), S(18), S(14)
        )
        _layout_rules.set_layout_spacing(table_layout, S(12))
        self._build_table_title_row(table_layout)
        table_layout.addWidget(self.table_view, 1)
        self.tracking_empty_label = QLabel(_("No monitored food items."))
        self.tracking_empty_label.setObjectName("TableEmptyStateLabel")
        self.tracking_empty_label.setAlignment(Qt.AlignCenter)
        self.tracking_empty_label.setWordWrap(True)
        self.tracking_empty_label.setVisible(False)
        table_layout.addWidget(self.tracking_empty_label)

    def _create_table_view(self) -> QTableView:
        S = self._S
        table = QTableView()
        table.setObjectName("TrackingProductsTable")
        table.setModel(self.model)
        configure_responsive_table(table, window_width=self.width(), show_grid=True)
        set_size_policy(table, QSizePolicy.Expanding, QSizePolicy.Expanding)
        table.setMinimumHeight(0)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setMouseTracking(True)
        table.setAlternatingRowColors(True)
        table.setItemDelegateForColumn(6, ProgressBarDelegate(self.db_manager, table))
        table.setItemDelegateForColumn(7, ActionDelegate(self, table))
        header = table.horizontalHeader()
        _layout_rules.set_header_highlight_sections(header, False)
        set_minimum_section_size(header, S(48))
        return table

    def _build_table_title_row(self, parent_layout: QVBoxLayout) -> None:
        self.table_title_row, self.lbl_table_title, self.lbl_table_count = (
            create_table_heading(_("Tracked Items"), scale=self._S)
        )
        parent_layout.addWidget(self.table_title_row)

    def _configure_table(self) -> None:
        self._size_tracking_columns()


from runtime.presentation.widgets import DomainAppStateBindingMixin
from runtime.presentation.widgets import DialogFeedbackMixin
from runtime.presentation.widgets import ControllerLifecycleMixin



class TrackingControllerMixin(
    TrackingDataControllerMixin,
    TrackingFormControllerMixin,
    DomainAppStateBindingMixin,
    ControllerLifecycleMixin,
    DialogFeedbackMixin,
):
    _load_token = 0
    app_state_page_name = "TrackingPage"
    app_state_callback_name = "_on_app_state_tracking_changed"


from runtime.presentation.widgets import create_page_header



class TrackingUiBuilderMixin(TrackingFormBuilderMixin, TrackingTableBuilderMixin):

    def _build_ui(self) -> None:
        self.setObjectName("TrackingPage")
        self.setProperty("layoutMode", "grid")
        self.main_layout = QVBoxLayout(self)
        self._setup_main_layout()
        self._build_header()
        self._build_controls_card()
        self._build_table_card()

    def _setup_main_layout(self) -> None:
        S = self._S
        _layout_rules.set_layout_contents_margins(
            self.main_layout, S(8), S(8), S(8), S(8)
        )
        _layout_rules.set_layout_spacing(self.main_layout, S(18))

    def _build_header(self) -> None:
        self.page_header, self.lbl_page_title, self.lbl_page_subtitle = (
            create_page_header(
                _("Track Products"), scale=self._S, subtitle=_("Tracking Control")
            )
        )
        self.main_layout.addWidget(self.page_header, 0)


from runtime.presentation.layout.interface import polish_interface
from runtime.presentation.layout.scaling import make_scaler
from runtime.presentation.layout.shell import apply_device_properties
from runtime.presentation.layout.tables import ResponsiveDataPageResizeMixin
from runtime.application.services.tracking import build_tracking_completer_suggestions
from runtime.application.services.tracking import TrackingService
from runtime.application.services.tracking import TrackingFormService
from runtime.application.services.catalog import PageVisibleStateService
from PyQt5.QtWidgets import QCompleter
from PyQt5.QtCore import QEvent, pyqtSignal
from runtime.presentation.views.tracking_support import find_selected_branch_index
from runtime.bootstrap.qt.workers import WorkerRegistry, client_thread_pool



class TrackingPage(
    TrackingResponsiveLayoutMixin,
    TrackingUiBuilderMixin,
    ResponsiveDataPageResizeMixin,
    TrackingControllerMixin,
    QWidget,
):
    responsive_resize_callbacks = ("apply_responsive_profile",)
    responsive_table_attr = "table_view"
    responsive_table_size_callback = "_size_tracking_columns"
    responsive_table_min_height = None
    responsive_table_resize_after_callbacks = False
    status_label_attr = "_status_lbl"
    summary_empty_label_attr = "tracking_empty_label"
    summary_loading_text = "Loading..."
    summary_state_method = "tracking_state"
    branch_context_changed = pyqtSignal(str)
    TABLE_COL_RATIOS: ClassVar[tuple[int, ...]] = (5, 11, 40, 5, 10, 10, 14, 5)
    TABLE_COL_MIN_WIDTHS: ClassVar[tuple[int, ...]] = (54, 92, 220, 46, 88, 88, 118, 52)
    TABLET_COL_RATIOS: ClassVar[tuple[int, ...]] = (5, 10, 40, 5, 10, 10, 15, 5)
    TABLET_COL_MIN_WIDTHS: ClassVar[tuple[int, ...]] = (
        50,
        84,
        190,
        44,
        82,
        82,
        108,
        48,
    )
    COMPACT_COL_RATIOS: ClassVar[tuple[int, ...]] = (5, 10, 42, 5, 10, 10, 14, 4)
    COMPACT_COL_MIN_WIDTHS: ClassVar[tuple[int, ...]] = (
        46,
        74,
        150,
        40,
        72,
        72,
        90,
        40,
    )

    def __init__(self, db_manager, parent=None, tracking_service=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.tracking_service = tracking_service or TrackingService(db_manager)
        self.tracking_form_service = TrackingFormService()
        self.page_visible_state_service = PageVisibleStateService()
        self.tracked_products = []
        self._product_catalog_rows: list = []
        self._pool = client_thread_pool()
        self._worker_registry = WorkerRegistry(self._pool)
        self._load_token = 0
        self._action_token = 0
        self._catalog_load_token = 0
        self._completer_cache_size = -1
        self._suppress_state_refresh_until = 0.0
        self._busy = None
        self._busy_depth = 0
        self._loading = False
        self._load_pending = False
        self._load_pending_show_busy = False
        self._catalog_loading = False
        self._catalog_load_pending_force_network = False
        self._action_running = False
        self._pending_state_payload = None
        self._bound_app_state = None
        self._disposed = False
        self._S = make_scaler(QApplication.instance())
        self._init_timers()
        self._build_ui()
        self._connect_signals()
        self._setup_page_state()

    def _init_timers(self) -> None:
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(60 * 1000)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh_tick)
        self._state_refresh_timer = QTimer(self)
        self._state_refresh_timer.setSingleShot(True)
        self._state_refresh_timer.timeout.connect(self._run_state_refresh)

    def _setup_page_state(self) -> None:
        apply_device_properties(self, self.width(), QApplication.instance())
        self._configure_table()
        self.configure_branch_filter()
        self._update_branch_ui_state()
        self.table_view.viewport().installEventFilter(self)
        self.destroyed.connect(self._close_tracking_workers)
        self.destroyed.connect(self._on_destroyed)
        self._set_page_table_summary(0, loading=False)
        polish_interface(self, window_width=self.width())
        self._apply_responsive_toolbar(force=True)

    def _connect_signals(self) -> None:
        self.cmb_view_branch.currentIndexChanged.connect(self.on_view_branch_changed)
        self.btn_add.clicked.connect(self.add_product)
        self.product_entry.textChanged.connect(self._clear_tracking_form_feedback)
        self.qty_entry.textChanged.connect(self._clear_tracking_form_feedback)
        self.prod_edit.dateChanged.connect(self._clear_tracking_form_feedback)
        self.exp_edit.dateChanged.connect(self._clear_tracking_form_feedback)
        self.product_entry.returnPressed.connect(self.qty_entry.setFocus)
        self.qty_entry.returnPressed.connect(self.add_product)

    def _close_tracking_workers(self, *_args) -> None:
        registry = getattr(self, "_worker_registry", None)
        if registry is not None:
            try:
                close = getattr(registry, "close", None)
                if callable(close):
                    close()
                else:
                    registry.cancel_all()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug("Tracking worker registry close failed", exc_info=True)

    def configure_branch_filter(self) -> None:
        state = self.tracking_service.get_branch_filter_state()
        branches = list(state.get("branches") or [])
        items = list(state.get("items") or [])
        show_row = bool(state.get("show_row"))
        if not show_row:
            self._set_branch_selector_visible(True)
            self.cmb_view_branch.blockSignals(True)
            self.cmb_view_branch.clear()
            selected_branch = branches[0] if len(branches) == 1 else ""
            self.cmb_view_branch.addItem(
                selected_branch or _("No branch selected"), selected_branch
            )
            self.cmb_view_branch.setEnabled(False)
            self.cmb_view_branch.blockSignals(False)
            self.tracking_service.apply_view_branch_selection(selected_branch)
            self._update_branch_ui_state()
            return
        self._set_branch_selector_visible(True)
        self._populate_branch_combo(items)
        if bool(state.get("disable_selector")) and branches:
            self._apply_locked_branch(branches[0])
            return
        self._apply_selectable_branch(
            items=items, selected_data=str(state.get("selected_data") or "")
        )

    def _set_branch_selector_visible(self, visible: bool) -> None:
        self.cmb_view_branch.setVisible(visible)
        getattr(self, "branch_field", self.cmb_view_branch).setVisible(visible)

    def _populate_branch_combo(self, items: list) -> None:
        self.cmb_view_branch.blockSignals(True)
        self.cmb_view_branch.clear()
        for label, value in items:
            self.cmb_view_branch.addItem(str(label), str(value))

    def _apply_locked_branch(self, branch: str) -> None:
        self.cmb_view_branch.setEnabled(False)
        self.cmb_view_branch.setCurrentIndex(0)
        self.tracking_service.apply_view_branch_selection(branch)
        self.cmb_view_branch.blockSignals(False)
        self.on_view_branch_changed()
        self._update_branch_ui_state()

    def _apply_selectable_branch(self, *, items: list, selected_data: str) -> None:
        self.cmb_view_branch.setEnabled(True)
        selected_index = find_selected_branch_index(
            items=items, selected_data=selected_data
        )
        self.cmb_view_branch.setCurrentIndex(selected_index)
        self.cmb_view_branch.blockSignals(False)
        self.on_view_branch_changed()

    def on_view_branch_changed(self) -> None:
        data = self.cmb_view_branch.currentData()
        self.tracking_service.apply_view_branch_selection(str(data or ""))
        self._update_branch_ui_state()
        self.load_tracked_products(show_busy=False)
        try:
            self.branch_context_changed.emit(
                self.tracking_service.current_branch_context()
            )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage.on_view_branch_changed failed", exc_info=True)

    def _update_branch_ui_state(self) -> None:
        try:
            state = self.tracking_service.get_branch_ui_state()
            self.btn_add.setEnabled(bool(state.get("can_create")))
            self._set_page_status(str(state.get("branch_text") or ""), role="muted")
            self._status_lbl.setToolTip(str(state.get("action_text") or ""))
            self.btn_add.setToolTip(str(state.get("add_tooltip") or ""))
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage._update_branch_ui_state failed", exc_info=True)

    def update_completer(self, stored_products: list | None = None) -> None:
        is_alive = getattr(self, "_is_alive", None)
        if callable(is_alive) and (not is_alive()):
            return
        if stored_products is None:
            products = list(getattr(self, "_product_catalog_rows", []) or [])
            if not products and (not bool(getattr(self, "_catalog_loading", False))):
                try:
                    QTimer.singleShot(
                        0, lambda: self.load_product_catalog(force_network=False)
                    )
                except UI_OPERATION_EXCEPTIONS:
                    logger.debug(
                        "Deferred tracking catalog load scheduling failed",
                        exc_info=True,
                    )
        else:
            products = list(stored_products)
        self._product_catalog_rows = list(products or [])
        suggestions = build_tracking_completer_suggestions(self._product_catalog_rows)
        completer = QCompleter(suggestions, self.product_entry)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.product_entry.setCompleter(completer)
        self._reconcile_visible_rows_with_catalog(
            list(getattr(self, "_product_catalog_rows", []) or [])
        )

    def eventFilter(self, obj, event):
        if obj is self.table_view.viewport() and event.type() == QEvent.Resize:
            self._size_tracking_columns()
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        try:
            if self.tracking_service.is_cloud_mode():
                self._stop_auto_refresh()
                self._load_cloud_snapshot_or_refresh()
                return
            self._start_auto_refresh()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage.showEvent refresh setup failed", exc_info=True)
        try:
            self.load_tracked_products(show_busy=False)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage.showEvent load failed", exc_info=True)

    def hideEvent(self, event) -> None:
        try:
            self._stop_auto_refresh()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage.hideEvent timer stop failed", exc_info=True)
        try:
            self._load_token += 1
            self._loading = False
            self._hide_busy()
            self._status_lbl.setText("")
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("TrackingPage.hideEvent cleanup failed", exc_info=True)
        super().hideEvent(event)

    def _start_auto_refresh(self) -> None:
        if not self._auto_refresh_timer.isActive():
            self._auto_refresh_timer.start()

    def _stop_auto_refresh(self) -> None:
        if self._auto_refresh_timer.isActive():
            self._auto_refresh_timer.stop()

    def _load_cloud_snapshot_or_refresh(self) -> None:
        try:
            snapshot = tracking_baseline.snapshot()
            if snapshot.ready:
                self.load_tracked_products(show_busy=False)
                self.load_product_catalog(force_network=False)
                return
            self.load_tracked_products(show_busy=False)
        except UI_OPERATION_EXCEPTIONS:
            self.load_tracked_products(show_busy=False)


# --- package exports ---
__all__ = [
    "TrackingControllerMixin",
    "TrackingDataControllerMixin",
    "TrackingFormBuilderMixin",
    "TrackingFormControllerMixin",
    "TrackingPage",
    "TrackingResponsiveLayoutMixin",
    "TrackingTableBuilderMixin",
    "TrackingUiBuilderMixin",
]
