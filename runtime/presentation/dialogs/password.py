from __future__ import annotations
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)
from runtime.shared.settings.config import _
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.helpers import add_stretch
from runtime.presentation.layout.interface import polish_interface
from runtime.presentation.layout.metrics import UI_METRICS
from runtime.presentation.widgets import apply_popup_contract
from runtime.presentation.widgets import (
    polish_dialog_action_buttons,
    polish_form_layout,
    polish_line_edits,
)


class ChangePasswordDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Change Password"))
        apply_popup_contract(
            self,
            object_name="ChangePasswordDialog",
            modal=True,
            size_grip=False,
            width_ratio=0.28,
            height_ratio=0.24,
            min_width=UI_METRICS.edit_product_dialog_min_width,
            min_height=220,
            max_width=560,
            max_height=420,
        )
        self._build_ui()
        polish_interface(self, window_width=self.width())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(root, 12, 10, 12, 10)
        _layout_rules.set_layout_spacing(root, 8)
        subtitle = QLabel(_("Change your password."))
        subtitle.setObjectName("MutedStatusLabel")
        subtitle.setWordWrap(True)
        subtitle.setVisible(False)
        form = QFormLayout()
        polish_form_layout(form, horizontal_spacing=10, vertical_spacing=8)
        self.old_password_input = QLineEdit()
        self.old_password_input.setEchoMode(QLineEdit.Password)
        self.new_password_input = QLineEdit()
        self.new_password_input.setEchoMode(QLineEdit.Password)
        polish_line_edits(
            (self.old_password_input, self.new_password_input),
            min_height=UI_METRICS.control_min_height,
        )
        self.new_password_input.returnPressed.connect(self.accept)
        form.addRow(_("Current Password:"), self.old_password_input)
        form.addRow(_("New Password:"), self.new_password_input)
        root.addLayout(form)
        self.status_label = QLabel("")
        self.status_label.setObjectName("MutedStatusLabel")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        buttons = QHBoxLayout()
        add_stretch(buttons, 1)
        self.cancel_button = QPushButton(_("Cancel"))
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button = QPushButton(_("Save"))
        self.ok_button.clicked.connect(self.accept)
        polish_dialog_action_buttons(
            self.ok_button,
            self.cancel_button,
            min_height=UI_METRICS.action_button_min_height,
        )
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.ok_button)
        root.addLayout(buttons)

    def set_busy(self, busy: bool, message: str = "") -> None:
        for widget in (
            self.old_password_input,
            self.new_password_input,
            self.cancel_button,
            self.ok_button,
        ):
            widget.setEnabled(not busy)
        self.status_label.setText(str(message or ""))

    def values(self) -> tuple[str, str]:
        return (
            self.old_password_input.text().strip(),
            self.new_password_input.text().strip(),
        )

    def accept(self) -> None:
        old_password, new_password = self.values()
        if not old_password or not new_password:
            self.status_label.setText(_("Current and new passwords are required."))
            self.new_password_input.setFocus()
            return
        if old_password == new_password:
            self.status_label.setText(
                _("The new password must be different from the current password.")
            )
            self.new_password_input.setFocus()
            return
        super().accept()
