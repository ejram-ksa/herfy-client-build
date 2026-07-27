from __future__ import annotations
from typing import ClassVar
import logging
from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QApplication
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from .metrics import UI_METRICS
from .profiles import profile_for_dimensions
from .scaling import make_scaler
from .screen import primary_screen_geometry, screen_size_tier, tiered_window_ratio

logger = logging.getLogger(__name__)


def fit_window_size(
    width_ratio: float = 0.86,
    height_ratio: float = 0.88,
    *,
    min_width: int = 960,
    min_height: int = 640,
    max_width: int | None = None,
    max_height: int | None = None,
    app: QApplication | None = None,
) -> QSize:
    geometry = primary_screen_geometry(app)
    if geometry is None:
        return QSize(min_width, min_height)
    safe_w_ratio, safe_h_ratio = tiered_window_ratio(width_ratio, height_ratio, app=app)
    screen_safe_width = max(320, int(geometry.width() * 0.96))
    screen_safe_height = max(240, int(geometry.height() * 0.96))
    effective_min_width = min(int(min_width), screen_safe_width)
    effective_min_height = min(int(min_height), screen_safe_height)
    width = int(max(effective_min_width, geometry.width() * safe_w_ratio))
    height = int(max(effective_min_height, geometry.height() * safe_h_ratio))
    if max_width is None:
        max_width = int(geometry.width() * 0.96)
    if max_height is None:
        max_height = int(geometry.height() * 0.96)
    return QSize(min(width, int(max_width)), min(height, int(max_height)))


def clamp_size_to_screen(
    size: QSize, *, padding: int = 24, app: QApplication | None = None
) -> QSize:
    geometry = primary_screen_geometry(app)
    if geometry is None:
        return size
    safe_width = max(320, geometry.width() - int(padding))
    safe_height = max(240, geometry.height() - int(padding))
    return QSize(min(size.width(), safe_width), min(size.height(), safe_height))


def fit_widget_to_screen(
    widget,
    *,
    width_ratio: float = 0.92,
    height_ratio: float = 0.92,
    min_width: int = 320,
    min_height: int = 240,
    padding: int = 24,
) -> QSize:
    size = clamp_size_to_screen(
        fit_window_size(
            width_ratio=width_ratio,
            height_ratio=height_ratio,
            min_width=min_width,
            min_height=min_height,
            app=QApplication.instance(),
        ),
        padding=padding,
        app=QApplication.instance(),
    )
    try:
        widget.resize(size)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("fit_widget_to_screen fallback failed", exc_info=True)
    return size


def fit_widget_once_to_screen(
    widget,
    *,
    state_attr: str = "_fit_once",
    width_ratio: float = 0.92,
    height_ratio: float = 0.92,
    min_width: int = 320,
    min_height: int = 240,
    padding: int = 24,
) -> bool:
    if widget is None or bool(getattr(widget, state_attr, False)):
        return False
    setattr(widget, state_attr, True)
    fit_widget_to_screen(
        widget,
        width_ratio=width_ratio,
        height_ratio=height_ratio,
        min_width=min_width,
        min_height=min_height,
        padding=padding,
    )
    return True


class FitOnceToScreenMixin:
    fit_once_screen_options: ClassVar[dict[str, int | float | str]] = {}

    def showEvent(self, event):
        super().showEvent(event)
        fit_widget_once_to_screen(self, **dict(self.fit_once_screen_options))


def fit_dialog_size(
    width_ratio: float,
    height_ratio: float,
    *,
    min_width: int = 360,
    min_height: int = 240,
    max_width: int | None = None,
    max_height: int | None = None,
    app: QApplication | None = None,
) -> QSize:
    tier = screen_size_tier(app)
    if tier == "small":
        width_ratio = min(width_ratio, 0.82)
        height_ratio = min(height_ratio, 0.78)
    elif tier == "medium":
        width_ratio = min(width_ratio, 0.86)
        height_ratio = min(height_ratio, 0.84)
    return fit_window_size(
        width_ratio=width_ratio,
        height_ratio=height_ratio,
        min_width=min_width,
        min_height=min_height,
        max_width=max_width,
        max_height=max_height,
        app=app,
    )


def adaptive_page_margin(
    window_width: int | None = None, app: QApplication | None = None
) -> int:
    return profile_for_dimensions(window_width, None, app=app).page_margin


def adaptive_dimension(
    window_width: int | None,
    app: QApplication | None,
    *,
    compact: int,
    comfortable: int,
    expanded: int,
) -> int:
    profile = profile_for_dimensions(window_width, None, app=app)
    value = (
        compact if profile.is_narrow else comfortable if profile.is_tablet else expanded
    )
    return make_scaler(app)(value)


def _responsive_profile(
    window_width: int | None = None, app: QApplication | None = None
):
    return profile_for_dimensions(window_width, None, app=app)


def adaptive_sidebar_width(
    window_width: int | None = None, app: QApplication | None = None
) -> int:
    del window_width, app
    return int(UI_METRICS.sidebar_width)


def adaptive_topbar_height(
    window_width: int | None = None, app: QApplication | None = None
) -> int:
    profile = _responsive_profile(window_width, app)
    return {
        "compact": 40,
        "tablet_portrait": 42,
        "tablet_landscape": 40,
        "desktop": 44,
        "wide": 46,
    }[profile.name]


def adaptive_icon_size(
    window_width: int | None = None, app: QApplication | None = None
) -> int:
    profile = _responsive_profile(window_width, app)
    return 22 if profile.touch_mode else 18


def adaptive_control_height(
    window_width: int | None = None, app: QApplication | None = None
) -> int:
    return _responsive_profile(window_width, app).control_height


def adaptive_dialog_padding(
    window_width: int | None = None, app: QApplication | None = None
) -> int:
    return _responsive_profile(window_width, app).dialog_margin


def adaptive_content_margin(window_width: int, app: QApplication | None = None) -> int:
    return _responsive_profile(window_width, app).page_margin
