from __future__ import annotations
import logging
from typing import Any
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QSizePolicy,
    QTableView,
    QTableWidget,
)
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.presentation.responsive import dispatch_reflow_callback
from .helpers import (
    set_minimum_height,
    set_minimum_section_size,
    set_minimum_width,
    set_section_resize_mode,
    set_size_policy,
    set_stretch_last_section,
)
from .profiles import (
    ResponsiveProfile,
    apply_profile_properties,
    profile_for_dimensions,
    profile_for_widget,
)
from .text import (
    polish_text_visibility,
    refresh_qt_style,
    result_count_text,
    set_empty_state,
    set_status_label_text,
    set_table_count_text,
)

logger = logging.getLogger(__name__)


def polish_tables(root: Any, *, window_width: int | None = None) -> None:
    if root is None or not hasattr(root, "findChildren"):
        return
    try:
        for table in root.findChildren((QTableView, QTableWidget)):
            configure_table_layout(
                table,
                window_width=window_width,
                show_grid=table.showGrid() if hasattr(table, "showGrid") else True,
            )
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("polish_tables failed", exc_info=True)


def apply_responsive_table_resize(
    owner: Any,
    table: Any,
    *,
    width: int,
    min_height: int | None = None,
    size_columns,
    logger_=None,
    context: str = "responsive table resize",
    app=None,
) -> None:
    try:
        profile = profile_for_dimensions(
            width, getattr(owner, "height", lambda: None)(), app=app
        )
        apply_profile_properties(owner, profile)
        refresh_qt_style(owner)
    except UI_OPERATION_EXCEPTIONS:
        if logger_ is not None:
            logger_.debug("%s device polish failed", context, exc_info=True)
    if table is None:
        return
    configure_table_layout(
        table, window_width=width, show_grid=True, min_height=min_height
    )
    if callable(size_columns):
        size_columns()
    polish_text_visibility(owner)


def configure_table_layout(
    table: Any,
    *,
    window_width: int | None = None,
    show_grid: bool = True,
    min_height: int | None = None,
) -> dict[str, int | str | bool]:
    profile = profile_for_dimensions(
        window_width, getattr(table, "height", lambda: None)()
    )
    height_constrained = profile.visual_breakpoint in {
        "small_terminal",
        "hd_720",
        "laptop_768",
    }
    row_height = max(
        30 if height_constrained else 38,
        profile.control_height
        + (4 if height_constrained else 6 if profile.touch_mode else 4),
    )
    header_height = max(
        34 if height_constrained else 42,
        profile.control_height + (2 if height_constrained else 4),
    )
    metrics: dict[str, int | str | bool] = {
        "device_class": (
            "compact"
            if profile.is_narrow
            else "comfortable" if profile.is_tablet else "expanded"
        ),
        "row_height": row_height,
        "header_height": header_height,
        "show_grid": bool(show_grid),
        "alternating_rows": True,
    }
    try:
        apply_profile_properties(table, profile)
        table.setAlternatingRowColors(True)
        table.setShowGrid(bool(show_grid))
        table.setMouseTracking(True)
        table.setWordWrap(False)
        if hasattr(table, "setTextElideMode"):
            table.setTextElideMode(Qt.ElideRight)
        if hasattr(table, "setHorizontalScrollMode"):
            table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        if hasattr(table, "setVerticalScrollMode"):
            table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        if hasattr(table, "setHorizontalScrollBarPolicy"):
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        if hasattr(table, "setVerticalScrollBarPolicy"):
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        if hasattr(table, "setSizeAdjustPolicy"):
            table.setSizeAdjustPolicy(QAbstractItemView.AdjustIgnored)
        set_size_policy(table, QSizePolicy.Expanding, QSizePolicy.Expanding)
        set_minimum_width(table, 0)
        if min_height is not None:
            set_minimum_height(table, int(min_height))
        header = table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionsMovable(False)
        set_stretch_last_section(header, False)
        header.setCascadingSectionResizes(True)
        set_minimum_section_size(header, 48)
        set_section_resize_mode(header, QHeaderView.Interactive)
        set_minimum_height(header, header_height)
        try:
            header.setDefaultAlignment(Qt.AlignCenter)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("table header alignment fallback failed", exc_info=True)
        vertical = table.verticalHeader()
        vertical.setVisible(False)
        vertical.setDefaultSectionSize(row_height)
        set_minimum_section_size(vertical, max(24, row_height - 6))
        refresh = getattr(table, "updateGeometries", None)
        if callable(refresh):
            refresh()
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("configure_table_layout fallback failed", exc_info=True)
    return metrics


class ResponsiveDataPageResizeMixin:
    responsive_resize_callbacks: tuple[str, ...] = ()
    responsive_table_attr = ""
    responsive_table_size_callback = ""
    responsive_table_min_height = 300
    status_label_attr = ""
    summary_count_label_attr = "lbl_table_count"
    summary_empty_label_attr = ""
    summary_loading_text = "Loading..."
    summary_state_method = ""

    def _set_page_status(self, text: str = "", *, role: str = "muted") -> None:
        label = getattr(self, str(self.status_label_attr or ""), None)
        set_status_label_text(label, text, role=role)

    def _apply_table_summary_state(
        self,
        *,
        count_label: Any,
        empty_label: Any,
        count_text: str,
        status_text: str,
        status_role: str,
        empty_visible: bool,
        empty_message: str,
    ) -> None:
        set_table_count_text(count_label, count_text)
        self._set_page_status(status_text, role=status_role)
        set_empty_state(empty_label, is_empty=empty_visible, message=empty_message)

    def _summary_state_kwargs(self, state_kwargs: dict[str, Any]) -> dict[str, Any]:
        return dict(state_kwargs)

    def _set_page_table_summary(
        self, total: int, *, loading: bool = False, **state_kwargs: Any
    ) -> None:
        try:
            state_factory = getattr(
                self.page_visible_state_service, str(self.summary_state_method or "")
            )
            state = state_factory(
                total=int(total or 0),
                loading=bool(loading),
                **self._summary_state_kwargs(state_kwargs),
            )
            count_text = (
                _(str(self.summary_loading_text or "Loading..."))
                if loading
                else result_count_text(total)
            )
            self._apply_table_summary_state(
                count_label=getattr(
                    self, str(self.summary_count_label_attr or ""), None
                ),
                empty_label=getattr(
                    self, str(self.summary_empty_label_attr or ""), None
                ),
                count_text=count_text,
                status_text=state.status_text,
                status_role=state.status_role,
                empty_visible=state.empty_visible,
                empty_message=state.empty_message,
            )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "%s._set_page_table_summary failed",
                self.__class__.__name__,
                exc_info=True,
            )

    def _safe_set_page_table_summary(
        self, total: int, *, loading: bool = False, **state_kwargs: Any
    ) -> None:
        setter = getattr(self, "_set_page_table_summary", None)
        if not callable(setter):
            return
        try:
            setter(total, loading=loading, **state_kwargs)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "%s._safe_set_page_table_summary failed",
                self.__class__.__name__,
                exc_info=True,
            )

    def resizeEvent(self, event):
        """Schedule responsive table/page reflow only when layout mode changes."""
        super().resizeEvent(event)
        try:
            from runtime.presentation.responsive import ensure_layout_mode_controller

            controller = ensure_layout_mode_controller(
                self, attr_name="_data_page_layout_mode_controller", interval_ms=60
            )
            if not bool(getattr(self, "_data_page_layout_mode_connected", False)):
                controller.reflowRequested.connect(self._on_data_page_reflow_requested)
                self._data_page_layout_mode_connected = True
            controller.schedule()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "%s.resizeEvent debounce fallback failed",
                self.__class__.__name__,
                exc_info=True,
            )
            self._on_data_page_reflow_requested("", profile_for_widget(self))

    def _on_data_page_reflow_requested(
        self, mode: str, profile: ResponsiveProfile
    ) -> None:
        """Apply deferred page/table reflow after a semantic mode transition.

        Callbacks now receive the resolved semantic mode and profile when their
        signature supports them. Pages that already perform full table sizing in
        their own responsive callback can disable the generic resize pass with
        ``responsive_table_resize_after_callbacks = False``.
        """
        page_logger = logging.getLogger(self.__class__.__module__)
        for callback_name in self.responsive_resize_callbacks:
            try:
                dispatch_reflow_callback(
                    self,
                    str(callback_name or ""),
                    mode=str(mode or ""),
                    profile=profile,
                    force=True,
                )
            except UI_OPERATION_EXCEPTIONS:
                page_logger.debug(
                    "%s responsive callback failed",
                    self.__class__.__name__,
                    exc_info=True,
                )
        if not bool(getattr(self, "responsive_table_resize_after_callbacks", True)):
            return
        apply_responsive_table_resize(
            self,
            getattr(self, str(self.responsive_table_attr or ""), None),
            width=self.width(),
            min_height=None,
            size_columns=getattr(
                self, str(self.responsive_table_size_callback or ""), None
            ),
            logger_=page_logger,
            context=f"{self.__class__.__name__}.resizeEvent",
        )
