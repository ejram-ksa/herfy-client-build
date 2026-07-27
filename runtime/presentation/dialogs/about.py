from __future__ import annotations
import sys
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from runtime.shared.settings.config import _, APP_DISPLAY_NAME, get_updates_base_url
from runtime.presentation.layout import helpers as _layout_rules
from runtime.presentation.layout.helpers import add_stretch
from runtime.presentation.layout.profiles import (
    ResponsiveProfile,
    apply_profile_properties,
    profile_for_widget,
)
from runtime.presentation.layout.scaling import make_scaler
from runtime.presentation.widgets import build_logo_label
from runtime.presentation.widgets import polish_button
from runtime.presentation.widgets import ResizeCallbackMixin
from runtime.shared.settings.version import APP_VERSION


class AboutPage(ResizeCallbackMixin, QWidget):
    resize_callback_name = "_apply_centered_profile"

    def __init__(self, db_manager):
        super().__init__()
        self.db_manager = db_manager
        self._S = make_scaler(QApplication.instance())
        self._build_ui()

    def _build_ui(self) -> None:
        S = self._S
        self.setObjectName("AboutPage")
        root = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(root, 0, 0, 0, 0)
        _layout_rules.set_layout_spacing(root, 0)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)
        shell = QWidget()
        shell.setObjectName("AboutPlainShell")
        scroll.setWidget(shell)
        self._content_layout = QVBoxLayout(shell)
        _layout_rules.set_layout_contents_margins(
            self._content_layout, S(18), S(18), S(18), S(18)
        )
        _layout_rules.set_layout_spacing(self._content_layout, S(8))
        add_stretch(self._content_layout, 1)
        logo = build_logo_label(
            width=S(132),
            height=S(82),
            object_name="AboutCenteredLogo",
            ui_role="logoMissing",
        )
        self._content_layout.addWidget(logo, alignment=Qt.AlignCenter)
        self.app_name_label = QLabel(_(APP_DISPLAY_NAME))
        self.app_name_label.setObjectName("AboutPlainAppName")
        self.app_name_label.setAlignment(Qt.AlignCenter)
        self.app_name_label.setWordWrap(True)
        self._content_layout.addWidget(self.app_name_label)
        self.product_label = QLabel(_("Desktop operations client"))
        self.product_label.setObjectName("AboutPlainSubtitle")
        self.product_label.setAlignment(Qt.AlignCenter)
        self.product_label.setWordWrap(True)
        self._content_layout.addWidget(self.product_label)
        self.version_label = QLabel(_("Version {version}").format(version=APP_VERSION))
        self.version_label.setObjectName("AboutPlainVersion")
        self.version_label.setAlignment(Qt.AlignCenter)
        self.version_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._content_layout.addWidget(self.version_label)
        self.developer_label = QLabel(_("Developer: Hussam ALFIFA"))
        self.developer_label.setObjectName("AboutPlainDeveloper")
        self.developer_label.setAlignment(Qt.AlignCenter)
        self.developer_label.setWordWrap(True)
        self.developer_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._content_layout.addWidget(self.developer_label)
        self.idea_label = QLabel(
            _(
                "Idea: track product shelf life, expiry risk, branch activity, and daily usage from one controlled desktop workspace."
            )
        )
        self.idea_label.setObjectName("AboutPlainIdea")
        self.idea_label.setAlignment(Qt.AlignCenter)
        self.idea_label.setWordWrap(True)
        self.idea_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._content_layout.addWidget(self.idea_label)
        runtime_mode = (
            _("Packaged EXE") if getattr(sys, "frozen", False) else _("Source mode")
        )
        update_server = get_updates_base_url()
        self.update_info_label = QLabel(
            _("Update channel: {server}\nRuntime: {runtime}").format(
                server=update_server, runtime=runtime_mode
            )
        )
        self.update_info_label.setObjectName("AboutPlainUpdateInfo")
        self.update_info_label.setAlignment(Qt.AlignCenter)
        self.update_info_label.setWordWrap(True)
        self.update_info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._content_layout.addWidget(self.update_info_label)
        self.update_status_label = QLabel(
            _(
                "This build uses the same remote update endpoint used by the installed EXE."
            )
        )
        self.update_status_label.setObjectName("AboutPlainStatus")
        self.update_status_label.setAlignment(Qt.AlignCenter)
        self.update_status_label.setWordWrap(True)
        self._content_layout.addWidget(self.update_status_label)
        self.check_update_button = QPushButton(_("Check for Updates"))
        self.check_update_button.setObjectName("PrimaryActionButton")
        self.check_update_button.clicked.connect(self._request_real_update_check)
        polish_button(self.check_update_button, min_height=S(30))
        self.check_update_button.hide()
        add_stretch(self._content_layout, 2)

    def _request_real_update_check(self) -> None:
        self.update_status_label.setText(_("Checking the real update endpoint..."))
        main_window = self.window()
        checker = getattr(main_window, "check_for_updates_now", None)
        if callable(checker):
            checker()
            self.update_status_label.setText(
                _(
                    "Update check started. Follow the update dialog if a newer EXE is available."
                )
            )
            return
        self.update_status_label.setText(
            _("Update check is available after opening the main application window.")
        )

    def _apply_centered_profile(self) -> None:
        self.apply_responsive_profile()

    def apply_responsive_profile(
        self, profile: ResponsiveProfile | None = None
    ) -> None:
        profile = profile or profile_for_widget(self)
        apply_profile_properties(self, profile)
        margin = max(profile.page_margin, self._S(14))
        _layout_rules.set_layout_contents_margins(
            self._content_layout, margin, margin, margin, margin
        )
        _layout_rules.set_layout_spacing(
            self._content_layout, max(profile.gap, self._S(7))
        )


def create_about_page(db_manager) -> QWidget:
    return AboutPage(db_manager)
