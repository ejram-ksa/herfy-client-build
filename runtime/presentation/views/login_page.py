from __future__ import annotations
from runtime.presentation.widgets import polish_button, polish_form_layout, polish_line_edits
from runtime.presentation.widgets import build_logo_label
from runtime.presentation.responsive import ensure_layout_mode_controller
from runtime.presentation.layout.interface import polish_interface
from runtime.presentation.layout.scaling import make_scaler
from runtime.presentation.layout.helpers import (
    add_stretch,
    set_minimum_height,
    set_minimum_width,
    set_size_policy,
)
from runtime.presentation.layout.fitting import adaptive_page_margin
from runtime.presentation.layout.profiles import (
    ResponsiveProfile,
    apply_profile_properties,
    profile_for_widget,
)
from runtime.presentation.layout.metrics import UI_METRICS
from PyQt5.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt, QTimer
from runtime.presentation.layout import helpers as _layout_rules
import logging
from PyQt5.QtWidgets import QApplication
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.presentation.auth import LoginControllerMixin
from runtime.bootstrap.qt.workers import WorkerRegistry, client_thread_pool

logger = logging.getLogger(__name__)


class LoginPage(LoginControllerMixin, QWidget):

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._pool = client_thread_pool()
        self._worker_registry = WorkerRegistry(self._pool)
        self._login_worker = None
        self._login_token = 0
        self._session_store = getattr(main_window, "session_store", None)
        self._draft_save_timer = QTimer(self)
        self._draft_save_timer.setSingleShot(True)
        self._draft_save_timer.setInterval(250)
        self._draft_save_timer.timeout.connect(self._flush_login_draft)
        self.destroyed.connect(self._close_login_workers)
        S = make_scaler(QApplication.instance())
        root = QVBoxLayout(self)
        _layout_rules.set_layout_contents_margins(root, 0, 0, 0, 0)
        _layout_rules.set_layout_spacing(root, 0)
        shell = QWidget()
        shell.setObjectName("LoginShell")
        root.addWidget(shell)
        shell_layout = QVBoxLayout(shell)
        _layout_rules.set_layout_contents_margins(
            shell_layout,
            S(adaptive_page_margin()),
            S(adaptive_page_margin()),
            S(adaptive_page_margin()),
            S(adaptive_page_margin()),
        )
        _layout_rules.set_layout_spacing(shell_layout, S(UI_METRICS.page_section_gap))
        add_stretch(shell_layout, 1)
        body = QWidget()
        body.setObjectName("LoginBody")
        self._body = body
        body_layout = QBoxLayout(QBoxLayout.LeftToRight, body)
        _layout_rules.set_layout_contents_margins(body_layout, 0, 0, 0, 0)
        _layout_rules.set_layout_spacing(body_layout, S(UI_METRICS.page_section_gap))
        shell_layout.addWidget(body, 0, Qt.AlignCenter)
        set_size_policy(body, QSizePolicy.Expanding, QSizePolicy.Preferred)
        set_minimum_width(body, 0)
        set_size_policy(body, QSizePolicy.Expanding, QSizePolicy.Preferred)
        add_stretch(shell_layout, 1)
        intro_card = QFrame()
        intro_card.setObjectName("LoginIntroCard")
        set_size_policy(intro_card, QSizePolicy.Expanding, QSizePolicy.Preferred)
        intro_layout = QVBoxLayout(intro_card)
        _layout_rules.set_layout_contents_margins(
            intro_layout,
            S(UI_METRICS.card_padding + 4),
            S(UI_METRICS.card_padding + 6),
            S(UI_METRICS.card_padding + 4),
            S(UI_METRICS.card_padding + 6),
        )
        _layout_rules.set_layout_spacing(intro_layout, S(10))
        logo = build_logo_label(
            width=S(132), height=S(72), object_name="LoginLogo", ui_role="logoMissing"
        )
        intro_layout.addWidget(logo, 0, Qt.AlignLeft)
        intro_title = QLabel(_("Welcome back"))
        intro_title.setProperty("uiRole", "pageTitle")
        intro_title.setWordWrap(True)
        intro_layout.addWidget(intro_title)
        intro_sub = QLabel(_("Sign in to manage branch operations."))
        intro_sub.setProperty("uiRole", "pageSubTitle")
        intro_sub.setWordWrap(True)
        intro_layout.addWidget(intro_sub)
        self.lbl_scope = QLabel(
            _(
                "Access is limited according to your assigned role and branch permissions."
            )
        )
        self.lbl_scope.setObjectName("LoginInfoText")
        self.lbl_scope.setWordWrap(True)
        intro_layout.addWidget(self.lbl_scope)
        tips_title = QLabel(_("Before you sign in"))
        tips_title.setObjectName("LoginSectionTitle")
        intro_layout.addWidget(tips_title)
        tips_text = QLabel(_("Branch access follows your role."))
        tips_text.setObjectName("LoginTipItem")
        tips_text.setWordWrap(True)
        intro_layout.addWidget(tips_text)
        add_stretch(intro_layout, 1)
        form_card = QFrame()
        form_card.setObjectName("Card")
        set_size_policy(form_card, QSizePolicy.Expanding, QSizePolicy.Preferred)
        form_layout = QVBoxLayout(form_card)
        _layout_rules.set_layout_contents_margins(
            form_layout,
            S(UI_METRICS.card_padding + 4),
            S(UI_METRICS.card_padding + 6),
            S(UI_METRICS.card_padding + 4),
            S(UI_METRICS.card_padding + 6),
        )
        _layout_rules.set_layout_spacing(form_layout, S(10))
        set_minimum_width(form_card, S(UI_METRICS.login_card_min_width))
        title = QLabel(_("Sign in"))
        title.setProperty("uiRole", "pageTitle")
        form_layout.addWidget(title)
        sub = QLabel(_("Enter your credentials."))
        sub.setProperty("uiRole", "pageSubTitle")
        sub.setWordWrap(True)
        form_layout.addWidget(sub)
        self.lbl_remote_notice = QLabel("")
        self.lbl_remote_notice.setObjectName("RemoteLoginNotice")
        self.lbl_remote_notice.setWordWrap(True)
        self.lbl_remote_notice.hide()
        form_layout.addWidget(self.lbl_remote_notice)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignTop)
        polish_form_layout(form, horizontal_spacing=S(10), vertical_spacing=S(10))
        self.ed_user = QLineEdit()
        self.ed_user.setPlaceholderText(_("Username or email"))
        self.ed_pass = QLineEdit()
        self.ed_pass.setPlaceholderText(_("Password"))
        self.ed_pass.setEchoMode(QLineEdit.Password)
        self._credential_inputs = (self.ed_user, self.ed_pass)
        polish_line_edits(
            (self.ed_user, self.ed_pass), min_height=S(UI_METRICS.control_min_height)
        )
        form.addRow(_("Username or email"), self.ed_user)
        form.addRow(_("Password"), self.ed_pass)
        form_layout.addLayout(form)
        self.chk_remember = QCheckBox(_("Remember me"))
        form_layout.addWidget(self.chk_remember)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        set_minimum_height(self.progress, S(UI_METRICS.progress_thin_height))
        form_layout.addWidget(self.progress)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("LoginStatusLabel")
        self.lbl_status.setWordWrap(True)
        form_layout.addWidget(self.lbl_status)
        btn_row = QHBoxLayout()
        add_stretch(btn_row)
        self.btn_login = QPushButton(_("Sign in"))
        polish_button(
            self.btn_login,
            role="primary",
            min_width=S(UI_METRICS.action_button_min_width),
            min_height=S(UI_METRICS.action_button_min_height),
            cursor=Qt.PointingHandCursor,
        )
        self.btn_login.clicked.connect(self.do_login)
        btn_row.addWidget(self.btn_login)
        form_layout.addLayout(btn_row)
        self._intro_card = intro_card
        self._form_card = form_card
        body_layout.addWidget(intro_card)
        body_layout.addWidget(form_card)
        self.ed_pass.returnPressed.connect(self.do_login)
        self.ed_user.returnPressed.connect(self.ed_pass.setFocus)
        self.ed_user.textChanged.connect(self._schedule_login_draft_save)
        self.chk_remember.toggled.connect(self._schedule_login_draft_save)
        self.restore_cached_input(clear_password=True)
        QTimer.singleShot(650, self.refresh_remote_notice)
        self._apply_login_layout()
        polish_interface(self, window_width=self.width())

    def apply_responsive_profile(
        self, profile: ResponsiveProfile | None = None
    ) -> None:
        self._apply_login_layout(profile=profile)

    def _apply_login_layout(self, profile: ResponsiveProfile | None = None):
        try:
            profile = profile or profile_for_widget(self, app=QApplication.instance())
            apply_profile_properties(self, profile)
            narrow = False
            body = getattr(self, "_body", None)
            intro = getattr(self, "_intro_card", None)
            form = getattr(self, "_form_card", None)
            if body is None or intro is None or form is None:
                return
            layout = body.layout()
            if not isinstance(layout, QBoxLayout):
                return
            layout.setDirection(QBoxLayout.LeftToRight)
            _layout_rules.set_layout_spacing(layout, profile.gap)
            set_minimum_width(form, 0 if narrow else UI_METRICS.login_card_min_width)
            set_size_policy(form, QSizePolicy.Expanding, QSizePolicy.Preferred)
            set_minimum_width(intro, 0)
            set_size_policy(intro, QSizePolicy.Expanding, QSizePolicy.Preferred)
            set_size_policy(body, QSizePolicy.Expanding, QSizePolicy.Preferred)
            for field in getattr(self, "_credential_inputs", ()):
                set_minimum_height(field, profile.control_height)
                set_size_policy(field, QSizePolicy.Expanding, QSizePolicy.Fixed)
            set_minimum_height(
                self.btn_login,
                (
                    profile.touch_target
                    if profile.touch_mode
                    else UI_METRICS.action_button_min_height
                ),
            )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("LoginPage responsive layout failed", exc_info=True)

    def resizeEvent(self, event):
        """Debounce login reflow and skip unchanged layout modes."""
        super().resizeEvent(event)
        try:
            controller = ensure_layout_mode_controller(
                self, attr_name="_login_layout_mode_controller", interval_ms=60
            )
            if not bool(getattr(self, "_login_layout_mode_connected", False)):
                controller.reflowRequested.connect(
                    self._on_login_layout_reflow_requested
                )
                self._login_layout_mode_connected = True
            controller.schedule()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("LoginPage resize debounce failed", exc_info=True)
            self._on_login_layout_reflow_requested("", None)

    def _on_login_layout_reflow_requested(self, _mode=None, _profile=None) -> None:
        """Apply the login layout after a debounced mode transition."""
        self._apply_login_layout()
        polish_interface(self, window_width=self.width())


__all__ = ["LoginPage"]
