from __future__ import annotations
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStyle,
    QToolButton,
)
from runtime.shared.settings.config import _
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.helpers import set_minimum_height, set_minimum_width, set_size_policy
from runtime.presentation.widgets import polish_button, polish_status_label
from runtime.presentation.widgets import apply_button_icon


class UsageControlsBuilderMixin:

    def _build_controls_panel(self) -> QFrame:
        S = self._S
        controls_panel = QFrame()
        self.usage_controls_panel = controls_panel
        controls_panel.setObjectName("UsageControlPanel")
        set_size_policy(controls_panel, QSizePolicy.Expanding, QSizePolicy.Fixed)
        controls_grid = QGridLayout(controls_panel)
        self.usage_controls_grid = controls_grid
        self.import_grid = controls_grid
        self.usage_toolbar_grid = controls_grid
        _layout_rules.set_layout_contents_margins(controls_grid, S(8), S(6), S(8), S(6))
        _layout_rules.set_layout_horizontal_spacing(controls_grid, S(6))
        _layout_rules.set_layout_vertical_spacing(controls_grid, S(4))
        self.lbl_r = QLabel(_("Receipts file"))
        self.lbl_r.setObjectName("FlatFieldLabel")
        self.lbl_r.setWordWrap(False)
        self.lbl_r.setVisible(False)
        self.lbl_b = QLabel(_("Opening stock file"))
        self.lbl_b.setObjectName("FlatFieldLabel")
        self.lbl_b.setWordWrap(False)
        self.lbl_b.setVisible(False)
        self.ed_r = QLineEdit()
        self.ed_r.setReadOnly(True)
        self.ed_r.setVisible(False)
        self.ed_r.setAccessibleName(_("Receipts file"))
        self.ed_b = QLineEdit()
        self.ed_b.setReadOnly(True)
        self.ed_b.setVisible(False)
        self.ed_b.setAccessibleName(_("Opening stock file"))
        self.btn_r = QToolButton()
        self.btn_r.setText(_("Receipts"))
        polish_button(
            self.btn_r,
            role="ghost",
            cursor=Qt.PointingHandCursor,
            min_width=S(78),
            tooltip=_("Import receipts file"),
        )
        set_size_policy(self.btn_r, QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_b = QToolButton()
        self.btn_b.setText(_("Opening"))
        polish_button(
            self.btn_b,
            role="ghost",
            cursor=Qt.PointingHandCursor,
            min_width=S(84),
            tooltip=_("Import opening stock file"),
        )
        set_size_policy(self.btn_b, QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lbl_search = QLabel(_("Search"))
        self.lbl_search.setObjectName("FlatFieldLabel")
        self.lbl_search.setWordWrap(False)
        self.search = QLineEdit()
        self.search.setAccessibleName(_("Search usage rows"))
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText(
            _("Search by material number, material name, or unit")
        )
        set_size_policy(self.search, QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lbl_status_title = QLabel(_("Calculation status"))
        self.lbl_status_title.setObjectName("FlatFieldLabel")
        self.lbl_status_title.setWordWrap(False)
        self.lbl_status_title.setVisible(False)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(False)
        set_size_policy(self.lbl_status, QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lbl_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        polish_status_label(self.lbl_status, role="muted")
        self.chk_hide_total_zero = QCheckBox(_("Hide zero total"))
        self.chk_hide_total_zero.setObjectName("UsageHideZeroTotalCheckBox")
        self.chk_hide_total_zero.setCursor(Qt.PointingHandCursor)
        self.chk_hide_total_zero.setToolTip(
            _(
                "Hide rows whose total usage is zero without recalculating the worksheet."
            )
        )
        self.chk_hide_total_zero.setAccessibleName(_("Hide zero total usage rows"))
        self.chk_hide_total_zero.setChecked(
            self.usage_workspace_service.hide_total_zero_enabled(self.db)
        )
        set_size_policy(self.chk_hide_total_zero, QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_print = QToolButton()
        self.btn_print.setObjectName("IconToolButton")
        self.btn_print.setCursor(Qt.PointingHandCursor)
        self.btn_print.setToolTip(_("Print Preview"))
        self.btn_print.setAccessibleName(_("Print Preview"))
        self.btn_print.setShortcut("Ctrl+P")
        self.btn_print.setAutoRaise(True)
        self._configure_print_button()
        self._usage_import_widgets = [self.lbl_r, self.btn_r, self.lbl_b, self.btn_b]
        self._usage_toolbar_widgets = [
            self.lbl_search,
            self.search,
            self.lbl_status_title,
            self.lbl_status,
            self.chk_hide_total_zero,
            self.btn_print,
        ]
        self._usage_controls_widgets = [
            self.btn_r,
            self.btn_b,
            self.lbl_search,
            self.search,
            self.lbl_status_title,
            self.lbl_status,
            self.chk_hide_total_zero,
            self.btn_print,
        ]
        self._usage_import_mode = ""
        self._usage_toolbar_mode = ""
        self._usage_controls_mode = ""
        self._apply_responsive_usage_controls(force=True)
        return controls_panel

    def _configure_print_button(self):
        self.btn_print.setText("")
        set_minimum_width(self.btn_print, self._S(34))
        set_minimum_height(self.btn_print, self._S(34))
        apply_button_icon(
            self.btn_print,
            "print.png",
            size=self._print_icon_size(),
            fallback_standard_icon=QStyle.SP_DialogApplyButton,
        )
        if self.btn_print.icon().isNull():
            self.btn_print.setText("🖨")

    def _apply_theme(self):
        S = self._S
        f = self.font()
        f.setPointSize(max(8, min(10, S(9))))
        self.setFont(f)
        _layout_rules.set_button_icon_size(self.btn_print, self._print_icon_size())
