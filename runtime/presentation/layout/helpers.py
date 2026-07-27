from __future__ import annotations
from typing import Any
from PyQt5.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDateEdit,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QTableView,
    QTableWidget,
    QTextEdit,
)


def _is_fluid_content_widget(widget: Any) -> bool:
    """Return true for widgets that should not be hard-clamped by size helpers."""
    return isinstance(
        widget,
        QAbstractButton
        | QLabel
        | QLineEdit
        | QComboBox
        | QDateEdit
        | QSpinBox
        | QTextEdit
        | QTableView
        | QTableWidget,
    )


def set_fluid_minimum_size(widget, width: int = 0, height: int = 0) -> None:
    """Apply a soft minimum to a widget that may still expand with its layout."""
    widget.setMinimumSize(max(0, int(width or 0)), max(0, int(height or 0)))


def set_fluid_control_height(widget, height: int) -> None:
    """Apply a minimum control height without clamping the control width."""
    widget.setMinimumWidth(0)
    widget.setMinimumHeight(max(0, int(height or 0)))
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


def set_fluid_button(widget, min_height: int) -> None:
    """Apply the standard adaptive policy for text buttons."""
    widget.setMinimumWidth(0)
    widget.setMinimumHeight(max(0, int(min_height or 0)))
    widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)


def set_fluid_card(widget, min_width: int = 0) -> None:
    """Apply the standard adaptive policy for cards and content containers."""
    widget.setMinimumWidth(max(0, int(min_width or 0)))
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)


def _set_fixed_square(widget, size: int) -> None:
    px = max(0, int(size or 0))
    widget.setMinimumSize(px, px)
    widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


def set_icon_box_size(widget, size: int) -> None:
    """Set the only fixed square contract used for decorative icon boxes."""
    _set_fixed_square(widget, size)


def set_window_control_size(widget, size: int) -> None:
    """Set the fixed square contract for small window control buttons."""
    set_icon_box_size(widget, size)


def set_badge_size(widget, width: int, height: int) -> None:
    """Set the fixed badge contract for unread counters and compact badges."""
    widget.setMinimumSize(max(0, int(width or 0)), max(0, int(height or 0)))
    widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


def resize_widget(widget, *args) -> None:
    widget.resize(*args)


def set_fixed_height(widget, value: int) -> None:
    """Apply a public height request as a soft minimum."""
    set_minimum_height(widget, value)


def set_fixed_width(widget, value: int) -> None:
    """Apply a public width request as a soft minimum."""
    set_minimum_width(widget, value)


def set_fixed_size(widget, *args) -> None:
    """Apply a public fixed-size request as a soft minimum."""
    set_minimum_size(widget, *args)


def set_minimum_height(widget, value: int) -> None:
    widget.setMinimumHeight(int(value))


def set_minimum_width(widget, value: int) -> None:
    widget.setMinimumWidth(int(value))


def set_minimum_size(widget, *args) -> None:
    widget.setMinimumSize(*args)


def set_maximum_height(widget, value: int) -> None:
    """Treat public maximum-height requests as no-ops for adaptive layouts.

    Hard maximums are the main source of clipped labels/buttons. Exact chrome
    constraints that are still required, such as the sidebar rail width, are set
    directly where the chrome contract is defined instead of through this helper.
    """
    return


def set_maximum_width(widget, value: int) -> None:
    """Treat public maximum-width requests as no-ops for adaptive layouts."""
    return


def set_maximum_size(widget, *args) -> None:
    """Avoid global hard maximum sizes in the fluid/adaptive UI layer."""
    return


def set_size_policy(widget, *args) -> None:
    widget.setSizePolicy(*args)


def set_minimum_section_size(header, value: int) -> None:
    header.setMinimumSectionSize(int(value))


def set_section_resize_mode(header, *args) -> None:
    header.setSectionResizeMode(*args)


def set_column_width(table, *args) -> None:
    table.setColumnWidth(*args)


def set_row_height(table, *args) -> None:
    table.setRowHeight(*args)


def resize_columns_to_contents(table) -> None:
    table.resizeColumnsToContents()


def set_stretch_factor(splitter, *args) -> None:
    splitter.setStretchFactor(*args)


def set_splitter_sizes(splitter, sizes) -> None:
    splitter.setSizes(list(sizes))


def set_layout_stretch(layout, *args) -> None:
    layout.setStretch(*args)


def add_stretch(layout, stretch: int = 0) -> None:
    layout.addStretch(stretch)


def set_stretch_last_section(header, enabled: bool) -> None:
    header.setStretchLastSection(bool(enabled))


def set_grid_column_stretch(layout, column: int, stretch: int) -> None:
    layout.setColumnStretch(int(column), int(stretch))


def set_grid_row_stretch(layout, row: int, stretch: int) -> None:
    layout.setRowStretch(int(row), int(stretch))


def set_box_stretch(layout, index: int, stretch: int) -> None:
    layout.setStretch(int(index), int(stretch))


def set_layout_contents_margins(layout, *args) -> None:
    layout.setContentsMargins(*args)


def set_layout_spacing(layout, value: int) -> None:
    layout.setSpacing(int(value))


def set_layout_horizontal_spacing(layout, value: int) -> None:
    layout.setHorizontalSpacing(int(value))


def set_layout_vertical_spacing(layout, value: int) -> None:
    layout.setVerticalSpacing(int(value))


def set_grid_column_minimum_width(layout, column: int, value: int) -> None:
    layout.setColumnMinimumWidth(int(column), int(value))


def set_grid_row_minimum_height(layout, row: int, value: int) -> None:
    layout.setRowMinimumHeight(int(row), int(value))


def set_header_default_section_size(header, value: int) -> None:
    header.setDefaultSectionSize(int(value))


def set_header_highlight_sections(header, enabled: bool) -> None:
    header.setHighlightSections(bool(enabled))


def set_header_cascading_section_resizes(header, enabled: bool) -> None:
    header.setCascadingSectionResizes(bool(enabled))


def set_splitter_handle_width(splitter, value: int) -> None:
    splitter.setHandleWidth(int(value))


def set_tree_uniform_row_heights(tree, enabled: bool) -> None:
    tree.setUniformRowHeights(bool(enabled))


def set_list_uniform_item_sizes(list_widget, enabled: bool) -> None:
    list_widget.setUniformItemSizes(bool(enabled))


def set_button_icon_size(button, size) -> None:
    button.setIconSize(size)


def set_printer_page_size(printer, page_size) -> None:
    printer.setPageSize(page_size)
