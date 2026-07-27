from __future__ import annotations
from runtime.presentation.layout import helpers as _layout_rules
import logging
from typing import Any
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QAbstractItemView, QHeaderView, QSizePolicy
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.presentation.layout.fitting import adaptive_control_height, adaptive_dimension
from runtime.presentation.layout.profiles import apply_profile_properties, profile_for_dimensions
from runtime.presentation.layout.screen import device_size_class
from runtime.presentation.layout.helpers import (
    set_column_width,
    set_minimum_height,
    set_minimum_section_size,
    set_minimum_width,
    set_section_resize_mode,
    set_size_policy,
    set_stretch_last_section,
)

logger = logging.getLogger(__name__)
TableMetrics = dict[str, int | str | bool]


def adaptive_table_row_height(window_width: int | None = None, app: Any = None) -> int:
    return adaptive_dimension(
        window_width, app, compact=21, comfortable=22, expanded=23
    )


def adaptive_table_header_height(
    window_width: int | None = None, app: Any = None
) -> int:
    return max(24, min(28, adaptive_control_height(window_width, app)))


def adaptive_table_icon_size(window_width: int | None = None, app: Any = None) -> int:
    return adaptive_dimension(
        window_width, app, compact=18, comfortable=20, expanded=22
    )


def adaptive_table_metrics(
    window_width: int | None = None, app: Any = None
) -> TableMetrics:
    size_class = device_size_class(window_width, app)
    return {
        "device_class": size_class,
        "row_height": adaptive_table_row_height(window_width, app),
        "header_height": adaptive_table_header_height(window_width, app),
        "icon_size": adaptive_table_icon_size(window_width, app),
        "alternating_rows": True,
        "show_grid": False,
    }


def _is_rtl(widget: Any) -> bool:
    try:
        return widget.layoutDirection() == Qt.RightToLeft
    except SERVICE_OPERATION_EXCEPTIONS:
        return False


def _default_header_alignment(widget: Any) -> Qt.Alignment:
    return Qt.AlignCenter


def _apply_vertical_header_metrics(table: Any, metrics: TableMetrics) -> None:
    try:
        row_height = int(metrics["row_height"])
        vertical_header = table.verticalHeader()
        _layout_rules.set_header_default_section_size(vertical_header, row_height)
        set_minimum_section_size(vertical_header, max(20, row_height - 5))
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("apply_table_metrics vertical header failed", exc_info=True)


def _apply_horizontal_header_metrics(table: Any, metrics: TableMetrics) -> None:
    try:
        horizontal_header = table.horizontalHeader()
        set_minimum_height(horizontal_header, int(metrics["header_height"]))
        horizontal_header.setDefaultAlignment(_default_header_alignment(table))
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("apply_table_metrics horizontal header failed", exc_info=True)


def apply_table_metrics(
    table: Any, window_width: int | None = None, app: Any = None
) -> TableMetrics:
    metrics = adaptive_table_metrics(window_width, app)
    try:
        apply_profile_properties(
            table,
            profile_for_dimensions(
                window_width, getattr(table, "height", lambda: None)(), app=app
            ),
        )
        table.setProperty(
            "tableDensity",
            "compact" if metrics["device_class"] == "compact" else "regular",
        )
        table.setAlternatingRowColors(bool(metrics["alternating_rows"]))
        table.setShowGrid(bool(metrics["show_grid"]))
        table.setMouseTracking(True)
        table.setWordWrap(False)
        if hasattr(table, "isSortingEnabled"):
            table.setSortingEnabled(table.isSortingEnabled())
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("apply_table_metrics fallback failed", exc_info=True)
    _apply_vertical_header_metrics(table, metrics)
    _apply_horizontal_header_metrics(table, metrics)
    return metrics


def _configure_table_header(table: Any) -> None:
    try:
        table.setLayoutDirection(Qt.LeftToRight)
        table.viewport().setLayoutDirection(Qt.LeftToRight)
        table.horizontalHeader().setLayoutDirection(Qt.LeftToRight)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("stable LTR table direction setup failed", exc_info=True)
    header = table.horizontalHeader()
    _layout_rules.set_header_highlight_sections(header, False)
    header.setSectionsMovable(False)
    set_stretch_last_section(header, False)
    _layout_rules.set_header_cascading_section_resizes(header, True)
    set_minimum_section_size(header, 28)
    set_section_resize_mode(header, QHeaderView.Interactive)
    header.setDefaultAlignment(_default_header_alignment(table))


def _configure_table_scroll_and_size(table: Any, min_height: int | None) -> None:
    set_size_policy(table, QSizePolicy.Expanding, QSizePolicy.Expanding)
    table.setTextElideMode(Qt.ElideRight)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    try:
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setWordWrap(False)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("table scroll safety setup failed", exc_info=True)
    set_minimum_width(table, 0)
    table.setSizeAdjustPolicy(QAbstractItemView.AdjustIgnored)
    if min_height is not None:
        set_minimum_height(table, int(min_height))


def configure_responsive_table(
    table: Any,
    *,
    window_width: int | None = None,
    show_grid: bool = True,
    min_height: int | None = None,
) -> TableMetrics:
    metrics = apply_table_metrics(table, window_width)
    try:
        _configure_table_scroll_and_size(table, min_height)
        table.setAlternatingRowColors(True)
        table.setShowGrid(bool(show_grid))
        table.setWordWrap(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        _configure_table_header(table)
        vertical_header = table.verticalHeader()
        vertical_header.setVisible(False)
        _layout_rules.set_header_default_section_size(
            vertical_header, int(metrics["row_height"])
        )
        set_minimum_section_size(
            vertical_header, max(24, int(metrics["row_height"]) - 6)
        )
        refresh = getattr(table, "updateGeometries", None)
        if callable(refresh):
            refresh()
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("configure_responsive_table fallback failed", exc_info=True)
    return metrics


def _normalized_int_list(
    values: list[int] | tuple[int, ...] | None,
    *,
    count: int,
    default: int,
    minimum: int,
) -> list[int]:
    result = [
        max(minimum, int(value or default)) for value in list(values or [])[:count]
    ]
    if len(result) < count:
        result.extend([max(minimum, int(default))] * (count - len(result)))
    return result


def _available_table_width(table: Any) -> int:
    viewport = table.viewport()
    viewport_width = int(viewport.width() if viewport is not None else table.width())
    try:
        scrollbar_width = table.verticalScrollBar().sizeHint().width()
    except SERVICE_OPERATION_EXCEPTIONS:
        scrollbar_width = 0
    return max(1, viewport_width - max(6, min(18, int(scrollbar_width or 0))))


def _distribute_surplus(widths: list[int], targets: list[int], surplus: int) -> None:
    if not targets:
        return
    index = 0
    while surplus > 0:
        widths[targets[index % len(targets)]] += 1
        surplus -= 1
        index += 1


def _shrink_to_available(
    widths: list[int], *, targets: list[int], available: int
) -> None:
    if not targets:
        return
    index = 0
    count = len(widths)
    while sum(widths) > available:
        column = targets[index % len(targets)]
        if widths[column] > 1:
            widths[column] -= 1
        index += 1
        if index > count * 4 and sum(widths) > available:
            widest = max(range(count), key=lambda idx: widths[idx])
            widths[widest] = max(1, widths[widest] - 1)


def _header_aware_min_widths(table: Any, minimums: list[int]) -> list[int]:
    """Raise column minimums enough to keep table headers readable."""
    try:
        model = table.model()
        font_metrics = table.fontMetrics()
        adjusted: list[int] = []
        for column, minimum in enumerate(minimums):
            header_text = ""
            if model is not None:
                value = model.headerData(column, Qt.Horizontal, Qt.DisplayRole)
                header_text = str(value or "")
            text_width = (
                int(font_metrics.horizontalAdvance(header_text)) if header_text else 0
            )
            adjusted.append(max(int(minimum), text_width + 32))
        return adjusted
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("header-aware minimum width fallback failed", exc_info=True)
        return list(minimums)


def _calculate_column_widths(
    *, ratios: list[int], min_widths: list[int], available: int, allow_overflow: bool
) -> tuple[list[int], int]:
    ratio_total = max(1, sum(ratios))
    total_min = sum(min_widths)
    if total_min <= available:
        return (list(min_widths), available - total_min)
    if allow_overflow:
        return (list(min_widths), 0)
    count = len(ratios)
    hard_floor = max(18, min(38, available // max(1, count)))
    floors = [hard_floor] * count
    floor_total = sum(floors)
    if floor_total >= available:
        widths = [
            max(1, int(available * ratios[index] / ratio_total))
            for index in range(count)
        ]
        return (widths, available - sum(widths))
    compressible = available - floor_total
    preferred_extra = [
        max(0, min_widths[index] - floors[index]) for index in range(count)
    ]
    preferred_extra_total = max(1, sum(preferred_extra))
    widths = [
        floors[index]
        + int(compressible * preferred_extra[index] / preferred_extra_total)
        for index in range(count)
    ]
    return (widths, available - sum(widths))


def fit_table_height_to_rows(
    table: Any, *, min_rows: int = 8, max_rows: int = 18, extra_pixels: int = 18
) -> None:
    """Fit common row counts inside the current window without fullscreen.

    The contract is visual-acceptance driven: small/medium result sets should be
    fully visible in the default window, while large result sets keep a clean
    vertical scrollbar instead of forcing the whole window taller.
    """
    try:
        model = table.model()
        row_count = int(model.rowCount()) if model is not None else 0
        minimum_rows = max(5, int(min_rows or 5))
        maximum_rows = max(minimum_rows, int(max_rows or minimum_rows))
        rows_to_show = min(max(int(row_count or 0), minimum_rows), maximum_rows)
        header = table.horizontalHeader()
        vertical = table.verticalHeader()
        row_height = max(
            19, int(vertical.defaultSectionSize() or table.fontMetrics().height() + 7)
        )
        header_height = max(
            22, int(header.height() or header.defaultSectionSize() or 24)
        )
        target = header_height + rows_to_show * row_height + int(extra_pixels)
        table.setMinimumHeight(max(160, target))
        set_size_policy(table, QSizePolicy.Expanding, QSizePolicy.Expanding)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setProperty("visualAcceptanceRows", rows_to_show)
        table.setProperty("tableHeightMode", "flexible")
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("fit_table_height_to_rows failed", exc_info=True)


def fit_table_columns(
    table: Any,
    ratios: list[int] | tuple[int, ...],
    *,
    min_widths: list[int] | tuple[int, ...] | None = None,
    stretch_columns: list[int] | tuple[int, ...] | None = None,
    allow_overflow: bool = True,
) -> None:
    try:
        model = table.model()
        count = int(model.columnCount()) if model is not None else len(ratios)
        if count <= 0:
            return
        header = table.horizontalHeader()
        for column in range(count):
            set_section_resize_mode(header, column, QHeaderView.Interactive)
        normalized_ratios = _normalized_int_list(
            ratios, count=count, default=1, minimum=1
        )
        normalized_min_widths = _header_aware_min_widths(
            table, _normalized_int_list(min_widths, count=count, default=64, minimum=32)
        )
        for column in range(count):
            try:
                table.setColumnHidden(column, False)
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug("table column unhide failed", exc_info=True)
        visible_columns = list(range(count))
        visible_ratios = [normalized_ratios[column] for column in visible_columns]
        visible_minimums = [normalized_min_widths[column] for column in visible_columns]
        available = _available_table_width(table)
        visible_widths, surplus = _calculate_column_widths(
            ratios=visible_ratios,
            min_widths=visible_minimums,
            available=available,
            allow_overflow=allow_overflow,
        )
        table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if allow_overflow else Qt.ScrollBarAlwaysOff
        )
        if allow_overflow and sum(visible_widths) > available:
            table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        else:
            table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        target_columns = [
            int(column)
            for column in list(stretch_columns or [])
            if int(column) in visible_columns
        ]
        if not target_columns:
            target_columns = [
                max(visible_columns, key=lambda column: normalized_ratios[column])
            ]
        target_positions = [visible_columns.index(column) for column in target_columns]
        _distribute_surplus(visible_widths, target_positions, surplus)
        if not allow_overflow:
            _shrink_to_available(
                visible_widths, targets=target_positions, available=available
            )
        widths = [1] * count
        for position, column in enumerate(visible_columns):
            if allow_overflow:
                width = max(normalized_min_widths[column], visible_widths[position])
            else:
                width = max(1, visible_widths[position])
            widths[column] = int(width)
        set_minimum_section_size(header, 32 if not allow_overflow else 48)
        total_width = sum((widths[column] for column in visible_columns))
        for column, width in enumerate(widths):
            set_column_width(table, column, width)
            set_section_resize_mode(header, column, QHeaderView.Interactive)
        if total_width <= available:
            for column in target_columns:
                set_section_resize_mode(header, column, QHeaderView.Stretch)
        set_stretch_last_section(header, False)
        table.setProperty(
            "stretchColumns", ",".join((str(column) for column in target_columns))
        )
        set_minimum_width(table, 0)
        try:
            hbar = table.horizontalScrollBar()
            if allow_overflow:
                hbar.setDisabled(False)
                if sum(visible_widths) <= available:
                    hbar.setValue(0)
            else:
                hbar.setValue(0)
                hbar.setDisabled(True)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("table scrollbar normalization failed", exc_info=True)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("fit_table_columns fallback failed", exc_info=True)
