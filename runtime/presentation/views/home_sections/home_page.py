from __future__ import annotations
from typing import ClassVar

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

from runtime.shared.assets import existing_asset_path
from runtime.presentation.widgets import apply_button_icon
from PyQt5.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QSizePolicy
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
from runtime.presentation.layout import helpers as _layout_rules
import logging
from runtime.presentation.layout.helpers import (
    set_grid_column_stretch,
    set_icon_box_size,
    set_minimum_height,
    set_size_policy,
)

logger = logging.getLogger(__name__)


class HomeDashboardComponentsMixin:
    ACTION_ICONS: ClassVar[dict[str, str]] = {
        "tracking": "products.png",
        "usage": "usage.png",
        "admin": "admin.png",
    }
    STAT_ICONS: ClassVar[dict[str, str]] = {
        "branches": "home.png",
        "tracked": "products.png",
        "expiring": "bell.png",
        "expired": "checkmark.png",
        "usage": "usage.png",
        "stored": "admin.png",
    }

    def _make_action_button(self, key: str) -> QPushButton:
        S = self._S
        btn = QPushButton("")
        btn.setObjectName("HomeQuickActionButton")
        btn.setCursor(Qt.PointingHandCursor)
        set_minimum_height(btn, S(54))
        set_size_policy(btn, QSizePolicy.Expanding, QSizePolicy.Fixed)
        apply_button_icon(btn, self.ACTION_ICONS.get(key, ""), size=S(24))
        btn.clicked.connect(
            lambda _=False, value=key: self.navigate_requested.emit(value)
        )
        return btn

    def _set_icon_label(self, label: QLabel, icon_name: str, size: int) -> None:
        """Apply a resource icon to a dashboard label."""
        path = existing_asset_path("resources", "images", icon_name)
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        label.setPixmap(
            pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _create_stat_card(self, key: str) -> dict:
        S = self._S
        card = QFrame()
        card.setObjectName("MetricTile")
        set_minimum_height(card, S(88))
        set_size_policy(card, QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay = QGridLayout(card)
        _layout_rules.set_layout_contents_margins(lay, S(14), S(12), S(14), S(10))
        _layout_rules.set_layout_horizontal_spacing(lay, S(12))
        _layout_rules.set_layout_vertical_spacing(lay, S(3))
        set_grid_column_stretch(lay, 0, 0)
        set_grid_column_stretch(lay, 1, 1)
        icon = QLabel("")
        icon.setObjectName("HomeStatIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon_size = S(34)
        icon_box = S(48)
        set_icon_box_size(icon, icon_box)
        self._set_icon_label(icon, self.STAT_ICONS.get(key, ""), icon_size)
        value = QLabel("0")
        value.setObjectName("HomeStatValue")
        value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        label = QLabel("")
        label.setObjectName("HomeStatLabel")
        label.setWordWrap(True)
        note = QLabel("")
        note.setObjectName("HomeStatNote")
        note.setWordWrap(False)
        note.setVisible(False)
        accent = QFrame()
        accent.setObjectName("HomeStatAccent")
        set_minimum_height(accent, S(3))
        set_size_policy(accent, QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.addWidget(icon, 0, 0, 2, 1, Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(value, 0, 1)
        lay.addWidget(label, 1, 1)
        lay.addWidget(note, 2, 1)
        lay.addWidget(accent, 3, 0, 1, 2)
        return {
            "card": card,
            "icon": icon,
            "value": value,
            "label": label,
            "note": note,
            "accent": accent,
        }

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _chip(self, text: str, *, active: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("chipRole", "active" if active else "default")
        lbl.setObjectName("HomeChip")
        lbl.setAlignment(Qt.AlignCenter)
        set_size_policy(lbl, QSizePolicy.Expanding, QSizePolicy.Fixed)
        return lbl


from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.domain.access import PermissionContext
from runtime.application.services.catalog import HomeDashboardService
from runtime.presentation.widgets import ControllerLifecycleMixin
from runtime.presentation.widgets import (
    disconnect_app_state_callbacks,
    rebind_app_state_callbacks_if_alive,
)



class HomeDashboardControllerMixin(ControllerLifecycleMixin):

    def _app_state_callbacks(self):
        return (
            ("data_changed", self._on_app_state_data_changed),
            ("item_updated", self._on_app_state_data_changed),
            ("item_deleted", self._on_app_state_data_changed),
            ("branch_changed", self._on_app_state_generic_changed),
            ("permissions_changed", self._on_app_state_generic_changed),
            ("user_changed", self._on_app_state_generic_changed),
            ("connection_changed", self._on_app_state_generic_changed),
        )

    def _disconnect_app_state(self) -> None:
        disconnect_app_state_callbacks(
            self,
            self._app_state_callbacks(),
            logger_=logger,
            context="HomeDashboardPage._disconnect_app_state",
        )

    def _on_destroyed(self, *_args) -> None:
        registry = getattr(self, "_worker_registry", None)
        if registry is not None:
            try:
                close = getattr(registry, "close", None)
                if callable(close):
                    close()
                else:
                    registry.cancel_all()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug("Home worker registry close failed", exc_info=True)
        self._disconnect_app_state()
        super()._on_destroyed(*_args)

    def bind_app_state(self, app_state) -> None:
        rebind_app_state_callbacks_if_alive(
            self,
            app_state,
            self._app_state_callbacks(),
            logger_=logger,
            disconnect_context="HomeDashboardPage._disconnect_app_state",
            bind_context="HomeDashboardPage.bind_app_state",
        )

    def _on_app_state_data_changed(self, domain, payload=None) -> None:
        del payload
        if not self._is_alive():
            return
        if str(domain or "").strip().lower() not in {"tracking", "usage", "admin"}:
            return
        if not self._should_refresh_now():
            self._deferred_refresh = True
            return
        self.refresh_dashboard()

    def _on_app_state_generic_changed(self, *_args) -> None:
        if not self._is_alive():
            return
        if not self._should_refresh_now():
            self._deferred_refresh = True
            return
        self.refresh_dashboard()

    def _build_dashboard_snapshot(
        self,
        *,
        profile=None,
        permission_context: PermissionContext | None = None,
        view_branch: str | None = None,
    ) -> dict[str, object]:
        service = getattr(self, "home_dashboard_service", None)
        if service is None:
            service = HomeDashboardService(self.db_manager)
            self.home_dashboard_service = service
        snapshot = service.build_snapshot(
            profile=profile,
            permission_context=permission_context,
            view_branch=view_branch,
            is_ar=self._is_ar(),
        )
        return snapshot.as_dict()

    def _run_pending_refresh(self) -> None:
        if not self._is_alive():
            return
        kwargs = dict(getattr(self, "_pending_refresh_kwargs", {}) or {})
        generation = getattr(self, "_refresh_generation", 0) + 1
        self._refresh_generation = generation

        def _work(progress_callback=None):
            del progress_callback
            return self._build_dashboard_snapshot(**kwargs)

        def _on_result(snapshot):
            if generation != getattr(self, "_refresh_generation", 0):
                return
            self._apply_dashboard_snapshot(snapshot or {})

        self._worker_registry.start(
            _work,
            on_result=_on_result,
            on_error=lambda message: logger.debug(
                "Home dashboard refresh failed: %s", message
            ),
            operation_key="home:dashboard_refresh",
            scope_checker=lambda: generation
            == int(getattr(self, "_refresh_generation", -1) or -1)
            and self._is_alive(),
        )

    def refresh_dashboard(
        self,
        *,
        profile=None,
        permission_context: PermissionContext | None = None,
        view_branch: str | None = None,
    ) -> None:
        if not self._is_alive():
            return
        if not self._should_refresh_now():
            self._deferred_refresh = True
            self._pending_refresh_kwargs = {
                "profile": profile,
                "permission_context": permission_context,
                "view_branch": view_branch,
            }
            return
        self._deferred_refresh = False
        self._pending_refresh_kwargs = {
            "profile": profile,
            "permission_context": permission_context,
            "view_branch": view_branch,
        }
        timer = getattr(self, "_refresh_timer", None)
        if timer is None:
            return
        try:
            timer.start(60)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Failed to start dashboard refresh timer", exc_info=True)


from runtime.presentation.responsive import layout_mode_for_width
from runtime.presentation.layout.profiles import (
    ResponsiveProfile,
    apply_profile_properties,
    fluid_content_width,
    profile_for_widget,
)
from PyQt5.QtWidgets import QApplication
from runtime.presentation.layout.helpers import set_minimum_width



class HomeResponsiveLayoutMixin:

    def _target_stat_columns(
        self, profile: ResponsiveProfile | None = None, mode: str | None = None
    ) -> int:
        """Return metric-card columns from semantic adaptive layout mode."""
        profile = profile or profile_for_widget(self, app=QApplication.instance())
        width = fluid_content_width(
            self, fallback=int(getattr(profile, "width", 0) or self.width() or 0)
        )
        available = max(1, width - int(profile.page_margin) * 2)
        resolved_mode = str(mode or layout_mode_for_width(available)).lower()
        total = max(1, len(getattr(self, "_stat_order", []) or [1]))
        if resolved_mode == "compact":
            return min(total, 3)
        if resolved_mode == "regular":
            return min(total, 3)
        return min(total, 6)

    def _place_action_buttons(self, *, horizontal: bool) -> None:
        buttons = list(getattr(self, "_action_buttons", []))
        for button in buttons:
            try:
                self.actions_grid.removeWidget(button)
            except UI_OPERATION_EXCEPTIONS:
                logger.debug(
                    "HomeDashboardPage._place_action_buttons fallback failed",
                    exc_info=True,
                )
        for col in range(3):
            set_grid_column_stretch(self.actions_grid, col, 0)
        if horizontal:
            for index, button in enumerate(buttons):
                self.actions_grid.addWidget(button, 0, index)
            for col in range(max(1, len(buttons))):
                set_grid_column_stretch(self.actions_grid, col, 1)
        else:
            for index, button in enumerate(buttons):
                self.actions_grid.addWidget(button, index, 0)
            set_grid_column_stretch(self.actions_grid, 0, 1)

    def apply_responsive_profile(
        self, profile: ResponsiveProfile | None = None, mode: str | None = None
    ) -> None:
        self._apply_responsive_layout(force=True, profile=profile, mode=mode)

    def _apply_responsive_layout(
        self,
        *,
        force: bool = False,
        profile: ResponsiveProfile | None = None,
        mode: str | None = None,
    ) -> None:
        profile = profile or profile_for_widget(self, app=QApplication.instance())
        width_for_mode = fluid_content_width(
            self, fallback=int(getattr(profile, "width", 0) or self.width() or 0)
        )
        semantic_mode = str(mode or layout_mode_for_width(width_for_mode)).lower()
        apply_profile_properties(self, profile)
        self.setProperty("layoutMode", semantic_mode)
        root = self.layout()
        if root is not None:
            _layout_rules.set_layout_contents_margins(
                root,
                profile.page_margin,
                profile.page_margin,
                profile.page_margin,
                profile.page_margin,
            )
            _layout_rules.set_layout_horizontal_spacing(root, profile.gap)
            _layout_rules.set_layout_vertical_spacing(root, profile.gap)
        height_limited = getattr(profile, "visual_breakpoint", "") in {
            "small_terminal",
            "hd_720",
            "laptop_768",
        }
        if hasattr(self, "hero_card"):
            set_minimum_height(self.hero_card, 0 if height_limited else self._S(60))
            set_size_policy(self.hero_card, QSizePolicy.Expanding, QSizePolicy.Minimum)
        columns = self._target_stat_columns(profile, semantic_mode)
        if force or columns != getattr(self, "_stat_columns", 0):
            self._stat_columns = columns
            for key in getattr(self, "_stat_order", []):
                self.stats_grid.removeWidget(self.stat_cards[key]["card"])
            for index, key in enumerate(getattr(self, "_stat_order", [])):
                row, col = divmod(index, max(1, columns))
                self.stats_grid.addWidget(self.stat_cards[key]["card"], row, col)
            for col in range(6):
                set_grid_column_stretch(self.stats_grid, col, 1 if col < columns else 0)
        self.lower_grid.removeWidget(self.branch_card)
        self.lower_grid.removeWidget(self.actions_card)
        self.lower_grid.addWidget(self.branch_card, 0, 0, 1, 1)
        self.lower_grid.addWidget(self.actions_card, 0, 1, 1, 1)
        set_minimum_width(self.actions_card, self._S(132 if height_limited else 150))
        set_grid_column_stretch(self.lower_grid, 0, 4)
        set_grid_column_stretch(self.lower_grid, 1, 1)
        self._place_action_buttons(horizontal=False)
        for button in getattr(self, "_action_buttons", []):
            set_minimum_height(
                button,
                (
                    profile.touch_target
                    if profile.touch_mode
                    else 24 if height_limited else 28
                ),
            )
        height_limited = getattr(profile, "visual_breakpoint", "") in {
            "small_terminal",
            "hd_720",
            "laptop_768",
        }
        stat_min_height = (
            48
            if getattr(profile, "visual_breakpoint", "") == "small_terminal"
            else 54 if height_limited else 66 if profile.touch_mode else 58
        )
        for info in getattr(self, "stat_cards", {}).values():
            set_minimum_height(info["card"], stat_min_height)
            set_size_policy(info["card"], QSizePolicy.Expanding, QSizePolicy.Preferred)


from runtime.presentation.widgets import create_page_header
from runtime.presentation.widgets import build_logo_label
from runtime.presentation.layout.shell import apply_device_properties
from runtime.shared.settings.config import _
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from runtime.presentation.layout.helpers import add_stretch, set_grid_row_stretch



class HomeUiBuilderMixin(HomeDashboardComponentsMixin):

    def _build_ui(self) -> None:
        S = self._S
        root = QGridLayout(self)
        _layout_rules.set_layout_contents_margins(root, S(6), S(6), S(6), S(6))
        _layout_rules.set_layout_horizontal_spacing(root, S(6))
        _layout_rules.set_layout_vertical_spacing(root, S(6))
        set_grid_row_stretch(root, 0, 0)
        set_grid_row_stretch(root, 1, 0)
        set_grid_row_stretch(root, 2, 0)
        set_grid_row_stretch(root, 3, 1)
        set_grid_column_stretch(root, 0, 1)
        apply_device_properties(self, self.width(), QApplication.instance())
        self.setProperty("layoutMode", "grid")
        self.page_header, self.lbl_page_title, self.lbl_page_subtitle = (
            create_page_header(
                _("Dashboard"),
                scale=S,
                subtitle=_("Overview of branches, products, and tracking status."),
            )
        )
        root.addWidget(self.page_header, 0, 0)
        self.hero_card = QFrame()
        self.hero_card.setObjectName("DashboardHeader")
        set_size_policy(self.hero_card, QSizePolicy.Expanding, QSizePolicy.Minimum)
        hero_layout = QGridLayout(self.hero_card)
        _layout_rules.set_layout_contents_margins(
            hero_layout, S(18), S(14), S(18), S(14)
        )
        _layout_rules.set_layout_horizontal_spacing(hero_layout, S(20))
        _layout_rules.set_layout_vertical_spacing(hero_layout, S(8))
        set_grid_column_stretch(hero_layout, 0, 0)
        set_grid_column_stretch(hero_layout, 1, 1)
        self.lbl_logo = build_logo_label(
            width=S(72), object_name="HomeLogo", ui_role="logoMissing"
        )
        set_size_policy(self.lbl_logo, QSizePolicy.Fixed, QSizePolicy.Fixed)
        hero_layout.addWidget(self.lbl_logo, 0, 0, 2, 1, Qt.AlignTop | Qt.AlignHCenter)
        hero_right = QVBoxLayout()
        _layout_rules.set_layout_spacing(hero_right, S(2))
        hero_layout.addLayout(hero_right, 0, 1, 2, 1)
        self.lbl_welcome_title = QLabel(_("Welcome"))
        self.lbl_welcome_title.setObjectName("HomeWelcomeTitle")
        self.lbl_welcome_title.setWordWrap(True)
        hero_right.addWidget(self.lbl_welcome_title)
        self.lbl_greeting = QLabel("")
        self.lbl_greeting.setObjectName("HomeGreetingLabel")
        self.lbl_greeting.setWordWrap(True)
        self.lbl_greeting.setVisible(False)
        hero_right.addWidget(self.lbl_greeting)
        self.lbl_subtitle = QLabel("")
        self.lbl_subtitle.setObjectName("HomeHeroSubtitle")
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setVisible(False)
        hero_right.addWidget(self.lbl_subtitle)
        self.chips_wrap = QWidget()
        self.chips_wrap.setObjectName("HomeChipsWrap")
        self.chips_layout = QHBoxLayout(self.chips_wrap)
        _layout_rules.set_layout_contents_margins(self.chips_layout, 0, S(2), 0, 0)
        _layout_rules.set_layout_spacing(self.chips_layout, S(3))
        hero_right.addWidget(self.chips_wrap)
        root.addWidget(self.hero_card, 1, 0)
        self.stats_grid = QGridLayout()
        _layout_rules.set_layout_contents_margins(self.stats_grid, 0, 0, 0, 0)
        _layout_rules.set_layout_horizontal_spacing(self.stats_grid, S(12))
        _layout_rules.set_layout_vertical_spacing(self.stats_grid, S(12))
        root.addLayout(self.stats_grid, 2, 0)
        self.stat_cards = {
            "branches": self._create_stat_card("branches"),
            "tracked": self._create_stat_card("tracked"),
            "expiring": self._create_stat_card("expiring"),
            "expired": self._create_stat_card("expired"),
            "usage": self._create_stat_card("usage"),
            "stored": self._create_stat_card("stored"),
        }
        self._stat_order = [
            "branches",
            "tracked",
            "expiring",
            "expired",
            "usage",
            "stored",
        ]
        self._stat_columns = 0
        self.lower_grid = QGridLayout()
        lower_grid = self.lower_grid
        _layout_rules.set_layout_contents_margins(lower_grid, 0, 0, 0, 0)
        _layout_rules.set_layout_horizontal_spacing(lower_grid, S(16))
        _layout_rules.set_layout_vertical_spacing(lower_grid, S(16))
        set_grid_column_stretch(lower_grid, 0, 4)
        set_grid_column_stretch(lower_grid, 1, 1)
        root.addLayout(lower_grid, 3, 0)
        self.branch_card = QFrame()
        self.branch_card.setObjectName("GridPanel")
        branch_layout = QVBoxLayout(self.branch_card)
        set_size_policy(self.branch_card, QSizePolicy.Expanding, QSizePolicy.Expanding)
        _layout_rules.set_layout_contents_margins(
            branch_layout, S(22), S(18), S(22), S(18)
        )
        _layout_rules.set_layout_spacing(branch_layout, S(12))
        self.lbl_branches_title = QLabel("")
        self.lbl_branches_title.setObjectName("HomeSectionTitle")
        branch_layout.addWidget(self.lbl_branches_title)
        self.lbl_branches_subtitle = QLabel("")
        self.lbl_branches_subtitle.setObjectName("HomeSectionSubtitle")
        self.lbl_branches_subtitle.setWordWrap(True)
        self.lbl_branches_subtitle.setVisible(False)
        branch_layout.addWidget(self.lbl_branches_subtitle)
        self.branches_wrap = QWidget()
        self.branches_wrap.setObjectName("HomeBranchesWrap")
        self.branches_layout = QGridLayout(self.branches_wrap)
        _layout_rules.set_layout_contents_margins(self.branches_layout, 0, 0, 0, 0)
        _layout_rules.set_layout_horizontal_spacing(self.branches_layout, S(12))
        _layout_rules.set_layout_vertical_spacing(self.branches_layout, S(12))
        branch_layout.addWidget(self.branches_wrap, 0, Qt.AlignTop)
        add_stretch(branch_layout, 1)
        lower_grid.addWidget(self.branch_card, 0, 0)
        self.actions_card = QFrame()
        self.actions_card.setObjectName("GridPanel")
        actions_layout = QVBoxLayout(self.actions_card)
        set_size_policy(self.actions_card, QSizePolicy.Expanding, QSizePolicy.Expanding)
        set_minimum_width(self.actions_card, 0)
        _layout_rules.set_layout_contents_margins(
            actions_layout, S(18), S(18), S(18), S(18)
        )
        _layout_rules.set_layout_spacing(actions_layout, S(12))
        self.lbl_actions_title = QLabel("")
        self.lbl_actions_title.setObjectName("HomeSectionTitle")
        actions_layout.addWidget(self.lbl_actions_title)
        self.lbl_actions_subtitle = QLabel("")
        self.lbl_actions_subtitle.setObjectName("HomeSectionSubtitle")
        self.lbl_actions_subtitle.setWordWrap(True)
        self.lbl_actions_subtitle.setVisible(False)
        actions_layout.addWidget(self.lbl_actions_subtitle)
        self.actions_grid = QGridLayout()
        _layout_rules.set_layout_contents_margins(self.actions_grid, 0, 0, 0, 0)
        _layout_rules.set_layout_horizontal_spacing(self.actions_grid, S(10))
        _layout_rules.set_layout_vertical_spacing(self.actions_grid, S(12))
        actions_layout.addLayout(self.actions_grid)
        self.btn_track = self._make_action_button("tracking")
        self.btn_usage = self._make_action_button("usage")
        self.btn_org = self._make_action_button("admin")
        self._action_buttons = [self.btn_track, self.btn_usage, self.btn_org]
        self.actions_grid.addWidget(self.btn_track, 0, 0)
        self.actions_grid.addWidget(self.btn_usage, 1, 0)
        self.actions_grid.addWidget(self.btn_org, 2, 0)
        set_grid_column_stretch(self.actions_grid, 0, 1)
        add_stretch(actions_layout, 1)
        lower_grid.addWidget(self.actions_card, 0, 1)
        self._apply_responsive_layout(force=True)


from runtime.presentation.widgets import ResizeCallbackMixin
from runtime.presentation.layout.scaling import make_scaler
from runtime.application.services.catalog import HomeDashboardPresenter
from runtime.application.services.translations import is_rtl
from PyQt5.QtCore import QTimer, pyqtSignal
from runtime.bootstrap.qt.workers import WorkerRegistry, client_thread_pool



class HomeDashboardPage(
    HomeResponsiveLayoutMixin,
    HomeUiBuilderMixin,
    ResizeCallbackMixin,
    HomeDashboardControllerMixin,
    QWidget,
):
    resize_callback_name = "_apply_responsive_layout"
    navigate_requested = pyqtSignal(str)

    def __init__(self, db_manager):
        super().__init__()
        self.db_manager = db_manager
        self._S = make_scaler(QApplication.instance())
        self.setObjectName("HomePage")
        self.home_dashboard_service = HomeDashboardService(db_manager)
        self._pool = client_thread_pool()
        self._worker_registry = WorkerRegistry(self._pool)
        self._refresh_generation = 0
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._run_pending_refresh)
        self._pending_refresh_kwargs = {}
        self._bound_app_state = None
        self._disposed = False
        self._deferred_refresh = False
        self.destroyed.connect(self._on_destroyed)
        self._build_ui()

    def _is_ar(self) -> bool:
        lang = self.db_manager.get_setting("language", "ar")
        return is_rtl(lang)

    def _apply_dashboard_snapshot(self, snapshot: dict[str, object]) -> None:
        values = dict(snapshot.get("values") or {})
        allowed = list(snapshot.get("allowed") or [])
        active_branch = str(snapshot.get("active_branch") or "").strip()
        presenter_state = HomeDashboardPresenter.build_from_payload(snapshot)
        self.lbl_page_title.setText(presenter_state.page_title)
        self.lbl_page_subtitle.setText(presenter_state.subtitle)
        self.lbl_page_subtitle.setVisible(bool(presenter_state.subtitle))
        self.lbl_welcome_title.setText(presenter_state.greeting)
        self.lbl_greeting.setText("")
        self.lbl_greeting.setVisible(False)
        self.lbl_subtitle.setText("")
        self.lbl_subtitle.setVisible(False)
        self.lbl_branches_title.setText(presenter_state.branches_title)
        self.lbl_branches_subtitle.setText(presenter_state.branches_subtitle)
        self.lbl_branches_subtitle.setVisible(bool(presenter_state.branches_subtitle))
        self.lbl_actions_title.setText(presenter_state.actions_title)
        self.lbl_actions_subtitle.setText(presenter_state.actions_subtitle)
        self.lbl_actions_subtitle.setVisible(bool(presenter_state.actions_subtitle))
        self.btn_track.setText(presenter_state.track_text)
        self.btn_usage.setText(presenter_state.usage_text)
        self.btn_org.setText(presenter_state.admin_text)
        self._clear_layout(self.chips_layout)
        visible_chips = list(presenter_state.top_chips) or ["—"]
        for text in visible_chips:
            self.chips_layout.addWidget(self._chip(text, active=False))
        add_stretch(self.chips_layout, 1)
        for key, info in self.stat_cards.items():
            info["value"].setText(str(values.get(key, 0)))
            info["label"].setText(presenter_state.stat_labels[key])
            info["note"].setText("")
        self._clear_layout(self.branches_layout)
        if allowed:
            active_norm = active_branch.lower() if active_branch else ""
            w = max(0, int(self.width() or 0))
            if w and w < self._S(560):
                column_count = 1
            elif w and w < self._S(760):
                column_count = 2
            elif w and w < self._S(1120):
                column_count = 3
            else:
                column_count = 3 if len(allowed) <= 9 else 4
            for index, branch in enumerate(allowed):
                row, col = divmod(index, column_count)
                self.branches_layout.addWidget(
                    self._chip(
                        branch,
                        active=branch.lower() == active_norm and bool(active_norm),
                    ),
                    row,
                    col,
                )
            for col in range(column_count):
                set_grid_column_stretch(self.branches_layout, col, 1)
        else:
            self.branches_layout.addWidget(
                self._chip(presenter_state.empty_branches_text), 0, 0
            )
            set_grid_column_stretch(self.branches_layout, 0, 1)
        self.btn_track.setEnabled(presenter_state.can_open_tracking)
        self.btn_usage.setEnabled(presenter_state.can_open_usage)
        self.btn_org.setEnabled(presenter_state.can_open_admin)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_deferred_refresh", False):
            self._deferred_refresh = False
            self.refresh_dashboard()


# Backward-compatible public name used by runtime.presentation.views/ui lazy exports.
HomePage = HomeDashboardPage


def create_home_page(db_manager) -> HomeDashboardPage:
    page = HomeDashboardPage(db_manager)
    try:
        page.refresh_dashboard()
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("create_home_page fallback failed", exc_info=True)
    return page


__all__ = ["HomeDashboardPage", "HomePage", "create_home_page"]
