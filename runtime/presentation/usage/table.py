from __future__ import annotations
import logging
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
)
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.helpers import (
    set_minimum_section_size,
    set_section_resize_mode,
    set_size_policy,
)
from runtime.presentation.tables.delegates import OnHandDelegate
from runtime.presentation.tables.headers import COL_H
from runtime.presentation.tables.metrics import configure_responsive_table
from runtime.presentation.tables.usage_model import UsageModel, UsageProxy
from runtime.presentation.widgets import create_table_heading

logger = logging.getLogger(__name__)


class UsageTableBuilderMixin:

    def _build_table_card(self) -> QFrame:
        S = self._S
        table_card = QFrame()
        table_card.setObjectName("GridPanel")
        table_layout = QVBoxLayout(table_card)
        _layout_rules.set_layout_contents_margins(table_layout, S(8), S(7), S(8), S(8))
        _layout_rules.set_layout_spacing(table_layout, S(4))
        self.table_title_row, self.lbl_table_title, self.lbl_table_count = (
            create_table_heading(_("Usage Results"), scale=self._S)
        )
        table_layout.addWidget(self.table_title_row)
        self.lbl_usage_hint = None
        self.table = QTableView()
        self.table.setObjectName("UsageTable")
        self.table.setToolTip("")
        self.table.setWhatsThis("")
        try:
            self.table.viewport().setToolTip("")
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Usage table viewport tooltip cleanup failed", exc_info=True)
        configure_responsive_table(
            self.table, window_width=self.width(), show_grid=True
        )
        set_size_policy(self.table, QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setMinimumHeight(0)
        self.table.setSelectionBehavior(QTableView.SelectItems)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        head = self.table.horizontalHeader()
        try:
            head.setToolTip("")
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Usage table header tooltip cleanup failed", exc_info=True)
        set_minimum_section_size(head, self._S(48))
        set_section_resize_mode(head, QHeaderView.Interactive)
        self.model = UsageModel([])
        self._usage_workspace_active = False
        self._usage_input_dirty = False
        self._usage_server_refresh_pending = False
        self._model_replace_in_progress = False
        self.proxy = UsageProxy()
        self.proxy.setSourceModel(self.model)
        self.proxy.set_hide_total_zero(
            self.usage_workspace_service.hide_total_zero_enabled(self.db)
        )
        self.proxy.setSortRole(Qt.UserRole)
        self.table.setModel(self.proxy)
        self.delegate = OnHandDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_H, self.delegate)
        table_layout.addWidget(self.table)
        self.usage_empty_label = QLabel(_("No usage rows to show."))
        self.usage_empty_label.setObjectName("TableEmptyStateLabel")
        self.usage_empty_label.setAlignment(Qt.AlignCenter)
        self.usage_empty_label.setWordWrap(True)
        self.usage_empty_label.setVisible(False)
        table_layout.addWidget(self.usage_empty_label)
        return table_card
