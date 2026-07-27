from __future__ import annotations
import logging
from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)
from runtime.shared.settings.config import _
from runtime.application.services.translations import is_rtl
from runtime.shared.objects import safe_get
from runtime.presentation.dialogs.helpers import text_value
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.dialogs.update_dialogs import _DialogCardMixin
from runtime.presentation.layout.metrics import UI_METRICS
from runtime.presentation.layout.helpers import add_stretch
from runtime.presentation.layout.interface import polish_interface
from runtime.presentation.widgets import apply_popup_contract
from runtime.presentation.widgets import polish_button, polish_form_layout

logger = logging.getLogger(__name__)


class EditTrackedProductDialog(QDialog, _DialogCardMixin):

    def __init__(self, db_manager, product: dict, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.product = product or {}
        self.setWindowTitle(_("Edit monitored food item"))
        lang_ = db_manager.get_setting("language", "ar")
        self.setLayoutDirection(Qt.RightToLeft if is_rtl(lang_) else Qt.LeftToRight)
        apply_popup_contract(
            self,
            object_name="EditTrackedProductDialog",
            modal=True,
            size_grip=False,
            width_ratio=0.38,
            height_ratio=0.46,
            min_width=max(UI_METRICS.edit_product_dialog_min_width, 560),
            min_height=max(UI_METRICS.edit_product_dialog_min_height, 410),
            max_width=780,
            max_height=640,
        )
        self.init_ui()
        polish_interface(self, window_width=self.width())

    def _readonly_line(self, value: str) -> QLineEdit:
        line = QLineEdit(str(value or "-"))
        line.setReadOnly(True)
        line.setClearButtonEnabled(False)
        line.setProperty("readOnlyInfo", True)
        line.setFocusPolicy(Qt.NoFocus)
        return line

    def init_ui(self):
        lay_main = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(lay_main, 12, 10, 12, 10)
        _layout_rules.set_layout_spacing(lay_main, 8)
        details_card, details_layout = self._card(
            "TrackingControlCard",
            _("Food item details"),
            _(
                "Branch, material number, and name are locked to protect the original record."
            ),
        )
        details_form = QFormLayout()
        polish_form_layout(details_form, horizontal_spacing=12, vertical_spacing=7)
        self.branch_view = self._readonly_line(text_value(self.product, "branch"))
        self.material_view = self._readonly_line(
            text_value(self.product, "material_number")
        )
        self.name_view = self._readonly_line(
            text_value(self.product, "name", "product_name", "display_product")
        )
        details_form.addRow(_("Restaurant branch"), self.branch_view)
        details_form.addRow(_("Material number"), self.material_view)
        details_form.addRow(_("Product Name"), self.name_view)
        details_layout.addLayout(details_form)
        lay_main.addWidget(details_card)
        edit_card, edit_layout = self._card(
            "TrackingControlCard",
            _("Editable values"),
            _("Update quantity and dates only."),
        )
        form_layout = QFormLayout()
        polish_form_layout(form_layout, horizontal_spacing=12, vertical_spacing=7)
        self.qty_edit = QLineEdit(str(safe_get(self.product, "quantity", 0) or 0))
        self.qty_edit.setValidator(QIntValidator(1, 999999, self))
        self.qty_edit.setAccessibleName(_("On-hand quantity"))
        self.qty_edit.setClearButtonEnabled(True)
        dformat = self.db_manager.get_setting("date_format", "yyyy-MM-dd")
        self.prod_edit = QDateEdit()
        self.prod_edit.setCalendarPopup(True)
        self.prod_edit.setDisplayFormat(dformat)
        self.prod_edit.setAccessibleName(_("Production date"))
        self.prod_edit.setToolTip(_("Production date"))
        pd_ = QDate.fromString(
            str(safe_get(self.product, "production_date", "") or ""), "yyyy-MM-dd"
        )
        self.prod_edit.setDate(pd_ if pd_.isValid() else QDate.currentDate())
        self.exp_edit = QDateEdit()
        self.exp_edit.setCalendarPopup(True)
        self.exp_edit.setDisplayFormat(dformat)
        self.exp_edit.setAccessibleName(_("Expiry date"))
        self.exp_edit.setToolTip(_("Expiry date"))
        ed_ = QDate.fromString(
            str(safe_get(self.product, "expiry_date", "") or ""), "yyyy-MM-dd"
        )
        self.exp_edit.setDate(ed_ if ed_.isValid() else QDate.currentDate())
        form_layout.addRow(_("On-hand quantity"), self.qty_edit)
        form_layout.addRow(_("Production date"), self.prod_edit)
        form_layout.addRow(_("Expiry date"), self.exp_edit)
        edit_layout.addLayout(form_layout)
        lay_main.addWidget(edit_card)
        btn_layout = QHBoxLayout()
        add_stretch(btn_layout)
        btn_ok = QPushButton(_("Save"))
        polish_button(btn_ok, role="primary")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton(_("Cancel"))
        polish_button(btn_cancel, role="ghost")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        lay_main.addLayout(btn_layout)
