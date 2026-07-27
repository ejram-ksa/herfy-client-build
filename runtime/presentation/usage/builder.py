from __future__ import annotations
from PyQt5.QtWidgets import QVBoxLayout
from runtime.shared.settings.config import _
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.shell import apply_device_properties
from runtime.presentation.usage.controls import UsageControlsBuilderMixin
from runtime.presentation.usage.table import UsageTableBuilderMixin
from runtime.presentation.widgets import create_page_header


class UsageUiBuilderMixin(UsageControlsBuilderMixin, UsageTableBuilderMixin):

    def _build_usage_ui(self) -> None:
        scale = self._S
        apply_device_properties(self, self.width())
        self._receipts_path = ""
        self._beginning_path = ""
        controls_panel = self._build_controls_panel()
        table_card = self._build_table_card()
        layout = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(
            layout, scale(6), scale(6), scale(6), scale(6)
        )
        _layout_rules.set_layout_spacing(layout, scale(5))
        self.setProperty("layoutMode", "grid")
        self.page_header, self.lbl_page_title, self.lbl_page_subtitle = (
            create_page_header(
                _("Usage"),
                scale=scale,
                subtitle=_(
                    "View and analyze product usage based on receipts and beginning stock."
                ),
            )
        )
        layout.addWidget(self.page_header, 0)
        layout.addWidget(controls_panel)
        layout.addWidget(table_card, 1)
