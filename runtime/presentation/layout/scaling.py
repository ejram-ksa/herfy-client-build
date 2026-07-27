from __future__ import annotations
from collections.abc import Callable
from PyQt5.QtWidgets import QApplication
from runtime.shared.settings.config import DEFAULT_FONT_SIZE_PT
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from .screen import primary_screen_geometry

_BASE_DPI = 96.0
_MIN_SCALE_FACTOR = 0.9
_MAX_SCALE_FACTOR = 1.12
_DEFAULT_SCREEN_WIDTH = 1366
_FONT_SIZE_MIN = 8
_FONT_SIZE_MAX = 11


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _current_app(app: QApplication | None = None) -> QApplication | None:
    return app or QApplication.instance()


def _logical_dpi(app: QApplication | None = None) -> float:
    app = _current_app(app)
    try:
        screen = app.primaryScreen() if app else None
        return float(screen.logicalDotsPerInch()) if screen else _BASE_DPI
    except SERVICE_OPERATION_EXCEPTIONS:
        return _BASE_DPI


def _screen_width(app: QApplication | None = None) -> int:
    geometry = primary_screen_geometry(_current_app(app))
    return int(geometry.width()) if geometry is not None else _DEFAULT_SCREEN_WIDTH


def _safe_int(value, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, *SERVICE_OPERATION_EXCEPTIONS):
        return int(fallback)


def scale_factor(app: QApplication | None = None) -> float:
    return clamp(_logical_dpi(app) / _BASE_DPI, _MIN_SCALE_FACTOR, _MAX_SCALE_FACTOR)


def make_scaler(app: QApplication | None = None) -> Callable[[int], int]:
    factor = scale_factor(app)

    def scale(px: int) -> int:
        try:
            return int(round(float(px) * factor))
        except (TypeError, ValueError, *SERVICE_OPERATION_EXCEPTIONS):
            return _safe_int(px, 0)

    return scale


def adaptive_font_point_size(
    font_size_pt: int = DEFAULT_FONT_SIZE_PT, app: QApplication | None = None
) -> int:
    base = _safe_int(font_size_pt, DEFAULT_FONT_SIZE_PT)
    width = _screen_width(app)
    factor = scale_factor(app)
    bump = 0
    if width >= 2560:
        bump = 2
    elif width >= 1920:
        bump = 1
    if factor >= 1.25 and width >= 1600:
        bump += 1
    return max(_FONT_SIZE_MIN, min(_FONT_SIZE_MAX, base + bump))
