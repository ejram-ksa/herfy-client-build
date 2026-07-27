from __future__ import annotations
from PyQt5.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)
from runtime.shared.settings.config import _
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.helpers import add_stretch, set_grid_column_stretch
from runtime.presentation.widgets import polish_button


class UsageProductsFormMixin:

    def _build_catalog_ui(self) -> None:
        root = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(root, 10, 8, 10, 8)
        _layout_rules.set_layout_spacing(root, 6)
        form_card, form_layout = self._card(
            "UsageImportCard", _("Consumption item catalog"), ""
        )
        tools = QGridLayout()
        _layout_rules.set_layout_horizontal_spacing(tools, 6)
        _layout_rules.set_layout_vertical_spacing(tools, 5)
        self.ed_m = self._new_entry(_("Material number"))
        self.ed_n = self._new_entry(_("Material name"))
        self.ed_u = self._new_entry(_("Unit"))
        self.btn_add = QPushButton(_("Save item"))
        polish_button(self.btn_add, role="primary")
        self.btn_add.clicked.connect(self._add)
        self.btn_refresh = QPushButton(_("Refresh"))
        polish_button(self.btn_refresh, role="ghost")
        self.btn_refresh.clicked.connect(self._refresh_remote)
        tools.addWidget(QLabel(_("Material number")), 0, 0)
        tools.addWidget(self.ed_m, 0, 1)
        tools.addWidget(QLabel(_("Material name")), 0, 2)
        tools.addWidget(self.ed_n, 0, 3)
        tools.addWidget(QLabel(_("Unit")), 1, 0)
        tools.addWidget(self.ed_u, 1, 1)
        tools.addWidget(self.btn_add, 1, 2)
        tools.addWidget(self.btn_refresh, 1, 3)
        set_grid_column_stretch(tools, 1, 1)
        set_grid_column_stretch(tools, 3, 2)
        form_layout.addLayout(tools)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("MutedStatusLabel")
        form_layout.addWidget(self.lbl_status)
        root.addWidget(form_card)
        list_card, list_layout = self._card(
            "UsageTableCard", _("Available consumption items"), ""
        )
        self.list = QListWidget()
        list_layout.addWidget(self.list, 1)
        root.addWidget(list_card, 1)
        buttons = QHBoxLayout()
        self.btn_del = QPushButton(_("Delete"))
        polish_button(self.btn_del, role="danger")
        self.btn_del.clicked.connect(self._del)
        buttons.addWidget(self.btn_del)
        add_stretch(buttons)
        root.addLayout(buttons)
        self.list.itemClicked.connect(self._fill_from_item)

    @staticmethod
    def _new_entry(label: str) -> QLineEdit:
        entry = QLineEdit()
        entry.setPlaceholderText(label)
        entry.setAccessibleName(label)
        entry.setClearButtonEnabled(True)
        return entry
