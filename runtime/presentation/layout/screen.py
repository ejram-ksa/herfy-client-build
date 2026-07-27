from __future__ import annotations
import logging
from PyQt5.QtWidgets import QApplication, QWidget
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from .profiles import screen_for_widget

logger = logging.getLogger(__name__)


def primary_screen_geometry(app: QApplication | None = None):
    app = app or QApplication.instance()
    try:
        screen = app.primaryScreen() if app else None
        if screen is not None:
            return screen.availableGeometry()
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("primary_screen_geometry fallback failed", exc_info=True)
    return None


def active_screen_geometry(
    widget: QWidget | None = None, app: QApplication | None = None
):
    """Return available geometry for the screen where the widget currently lives.

    This supports mixed monitor fleets and windows moved between displays.
    """
    try:
        screen = screen_for_widget(widget, app)
        if screen is not None:
            return screen.availableGeometry()
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("active_screen_geometry fallback failed", exc_info=True)
    return primary_screen_geometry(app)


def _screen_scale_factor(app: QApplication | None = None) -> float:
    app = app or QApplication.instance()
    try:
        screen = app.primaryScreen() if app else None
        dpi = float(screen.logicalDotsPerInch()) if screen else 96.0
    except SERVICE_OPERATION_EXCEPTIONS:
        dpi = 96.0
    return max(0.92, min(1.38, dpi / 96.0))


def _scaled_width_threshold(px: int, app: QApplication | None = None) -> int:
    try:
        return int(round(float(px) * _screen_scale_factor(app)))
    except SERVICE_OPERATION_EXCEPTIONS:
        return int(px)


def screen_size_tier(app: QApplication | None = None) -> str:
    geometry = primary_screen_geometry(app)
    if geometry is None:
        return "medium"
    width = geometry.width()
    height = geometry.height()
    if width <= 1366 or height <= 768:
        return "small"
    if width <= 1920 and height <= 1080:
        return "medium"
    if width <= 2560:
        return "large"
    return "ultra"


def tiered_window_ratio(
    width_ratio: float = 0.86,
    height_ratio: float = 0.88,
    *,
    app: QApplication | None = None,
) -> tuple[float, float]:
    tier = screen_size_tier(app)
    if tier == "small":
        return (min(width_ratio, 0.965), min(height_ratio, 0.935))
    if tier == "medium":
        return (min(width_ratio, 0.94), min(height_ratio, 0.92))
    return (width_ratio, height_ratio)


def resolved_window_width(
    window_width: int | None = None,
    app: QApplication | None = None,
    *,
    fallback: int = 1366,
) -> int:
    try:
        width = int(window_width or 0)
    except SERVICE_OPERATION_EXCEPTIONS:
        width = 0
    if width <= 0:
        geometry = primary_screen_geometry(app)
        width = int(geometry.width()) if geometry is not None else int(fallback)
    return width


def device_size_class(
    window_width: int | None = None, app: QApplication | None = None
) -> str:
    width = resolved_window_width(window_width, app)
    if width < _scaled_width_threshold(980, app):
        return "compact"
    if width < _scaled_width_threshold(1320, app):
        return "comfortable"
    return "expanded"
