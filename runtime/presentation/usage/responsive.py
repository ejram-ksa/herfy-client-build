from __future__ import annotations
import logging
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QAbstractItemView
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.helpers import (
    set_grid_column_stretch,
    set_minimum_height,
    set_minimum_width,
)
from runtime.presentation.layout.profiles import (
    ResponsiveProfile,
    apply_profile_properties,
    fluid_content_width,
    profile_for_widget,
    resolve_fluid_toolbar_mode,
)
from runtime.presentation.tables.metrics import fit_table_columns, fit_table_height_to_rows
from runtime.presentation.widgets import refresh_widget_style

logger = logging.getLogger(__name__)


class UsageResponsiveLayoutMixin:

    def apply_responsive_profile(
        self, profile: ResponsiveProfile | None = None, mode: str | None = None
    ) -> None:
        del mode
        profile = profile or profile_for_widget(self)
        apply_profile_properties(self, profile)
        layout = self.layout()
        if layout is not None:
            _layout_rules.set_layout_contents_margins(
                layout,
                profile.page_margin,
                profile.page_margin,
                profile.page_margin,
                profile.page_margin,
            )
            _layout_rules.set_layout_spacing(layout, profile.gap)
        self._apply_responsive_usage_controls(force=True, profile=profile)
        self._size_columns()

    def _apply_responsive_usage_controls(
        self, *, force: bool = False, profile: ResponsiveProfile | None = None
    ):
        try:
            profile = profile or profile_for_widget(self)
            available_width = max(
                1,
                fluid_content_width(
                    getattr(self, "usage_controls_panel", None),
                    fallback=int(profile.width or self.width() or 0),
                )
                - int(profile.dialog_margin * 2),
            )
            wide_required = (
                sum((self._S(value) for value in (96, 96, 68, 260, 120, 112, 42)))
                + profile.gap * 6
            )
            compact_required = (
                sum((self._S(value) for value in (84, 84, 60, 220, 96, 42)))
                + profile.gap * 5
            )
            resolved = resolve_fluid_toolbar_mode(
                width=available_width,
                wide_required_width=wide_required,
                compact_required_width=compact_required,
            )
            mode = "single_row" if resolved == "wide" else "compact"
            if not force and mode == getattr(self, "_usage_controls_mode", ""):
                return
            self._usage_controls_mode = mode
            self._usage_import_mode = mode
            self._usage_toolbar_mode = mode
            apply_profile_properties(self, profile)
            self.setProperty("toolbarMode", mode)
            refresh_widget_style(self)
            for widget in self._usage_controls_widgets:
                set_minimum_height(widget, profile.control_height)
            set_minimum_width(self.btn_print, profile.touch_target)
            set_minimum_height(self.btn_print, profile.touch_target)
            set_minimum_width(self.search, 0)
            set_minimum_width(self.lbl_status, 0)
            grid = self.usage_controls_grid
            for widget in self._usage_controls_widgets:
                grid.removeWidget(widget)
            for col in range(10):
                set_grid_column_stretch(grid, col, 0)
                _layout_rules.set_grid_column_minimum_width(grid, col, 0)
            if mode == "compact":
                grid.addWidget(self.btn_r, 0, 0)
                grid.addWidget(self.btn_b, 0, 1)
                grid.addWidget(self.lbl_search, 0, 2)
                grid.addWidget(self.search, 0, 3)
                grid.addWidget(self.lbl_status, 0, 4)
                grid.addWidget(self.chk_hide_total_zero, 0, 5)
                grid.addWidget(self.btn_print, 0, 6)
                set_grid_column_stretch(grid, 3, 2)
                set_grid_column_stretch(grid, 4, 1)
            else:
                grid.addWidget(self.btn_r, 0, 0)
                grid.addWidget(self.btn_b, 0, 1)
                grid.addWidget(self.lbl_search, 0, 2)
                grid.addWidget(self.search, 0, 3)
                grid.addWidget(self.lbl_status, 0, 4)
                grid.addWidget(self.chk_hide_total_zero, 0, 5)
                grid.addWidget(self.btn_print, 0, 6)
                set_grid_column_stretch(grid, 3, 2)
                set_grid_column_stretch(grid, 4, 1)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("UsagePage responsive controls failed", exc_info=True)

    def _apply_responsive_imports(self, *, force: bool = False):
        self.apply_responsive_profile(profile_for_widget(self))

    def _print_icon_size(self):
        size = max(20, self._S(22))
        return QSize(size, size)

    def _size_columns(self):
        for column in range(
            self.proxy.columnCount()
            if getattr(self, "proxy", None) is not None
            else len(self.COL_RATIOS)
        ):
            self.table.setColumnHidden(column, False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        fit_table_height_to_rows(self.table, min_rows=5, max_rows=20)
        fit_table_columns(
            self.table,
            self.COL_RATIOS,
            min_widths=[self._S(value) for value in self.COL_MIN_WIDTHS],
            stretch_columns=(1,),
            allow_overflow=False,
        )
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
