from __future__ import annotations
import logging
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)
from runtime.shared.settings.config import _
from runtime.application.services.translations import is_rtl
from runtime.presentation.dialogs.helpers import text_value
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.dialogs.update_dialogs import _DialogCardMixin
from runtime.presentation.layout.helpers import add_stretch
from runtime.presentation.layout.interface import polish_interface
from runtime.presentation.widgets import apply_popup_contract
from runtime.presentation.widgets import polish_button, polish_form_layout

logger = logging.getLogger(__name__)


class ConfirmTrackedProductDeleteDialog(QDialog, _DialogCardMixin):

    def __init__(self, db_manager, product: dict, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.product = product or {}
        self.setWindowTitle(_("Delete monitored food item"))
        lang_ = db_manager.get_setting("language", "ar")
        self.setLayoutDirection(Qt.RightToLeft if is_rtl(lang_) else Qt.LeftToRight)
        apply_popup_contract(
            self,
            object_name="ConfirmTrackedProductDeleteDialog",
            modal=True,
            size_grip=False,
            width_ratio=0.36,
            height_ratio=0.42,
            min_width=540,
            min_height=380,
            max_width=720,
            max_height=560,
        )
        self.init_ui()
        polish_interface(self, window_width=self.width())

    def init_ui(self):
        layout = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(layout, 12, 10, 12, 10)
        _layout_rules.set_layout_spacing(layout, 8)
        card, card_layout = self._card(
            "TrackingControlCard",
            _("Delete monitored food item"),
            _(
                "This action removes only this monitored record. Review all details before deleting."
            ),
        )
        form = QFormLayout()
        polish_form_layout(form, horizontal_spacing=12, vertical_spacing=7)
        details = (
            (_("Restaurant branch"), text_value(self.product, "branch")),
            (_("Material number"), text_value(self.product, "material_number")),
            (
                _("Product Name"),
                text_value(self.product, "name", "product_name", "display_product"),
            ),
            (_("On-hand quantity"), text_value(self.product, "quantity")),
            (_("Production date"), text_value(self.product, "production_date")),
            (_("Expiry date"), text_value(self.product, "expiry_date")),
        )
        for label, value in details:
            value_label = QLabel(str(value or "-"))
            value_label.setWordWrap(True)
            value_label.setObjectName("SettingsCardText")
            form.addRow(label, value_label)
        card_layout.addLayout(form)
        layout.addWidget(card)
        buttons = QHBoxLayout()
        add_stretch(buttons)
        btn_cancel = QPushButton(_("Cancel"))
        polish_button(btn_cancel, role="ghost")
        btn_cancel.clicked.connect(self.reject)
        btn_delete = QPushButton(_("Delete"))
        polish_button(btn_delete, role="danger")
        btn_delete.clicked.connect(self.accept)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_delete)
        layout.addLayout(buttons)


def confirm_tracked_product_delete(db_manager, product: dict, parent=None) -> bool:
    dialog = ConfirmTrackedProductDeleteDialog(db_manager, product, parent)
    return bool(dialog.exec_())
