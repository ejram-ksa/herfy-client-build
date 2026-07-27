from __future__ import annotations
import logging
import re
from functools import lru_cache
from pathlib import Path
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import QApplication
from runtime.shared.settings.config import (
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_SIZE_PT,
    THEME_QSS_RELATIVE_PATH,
    resource_path,
)
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.presentation.layout.scaling import adaptive_font_point_size

logger = logging.getLogger(__name__)
DEFAULT_COLOR_TOKENS: dict[str, str] = {
    "app_background": "#F6F8FC",
    "surface": "#FFFFFF",
    "surface_soft": "#F2F6FD",
    "text": "#0B1B36",
    "text_muted": "#64748B",
    "primary": "#1F6BFF",
    "progress_track": "#DDE5F0",
    "progress_fallback": "#94A3B8",
    "status_ok": "#138A43",
    "status_soon": "#B7791F",
    "status_warning": "#DD6B20",
    "status_today": "#D62828",
    "status_danger": "#8B1E1E",
    "table_status_valid": "#138A43",
    "table_status_soon": "#B7791F",
    "table_status_after": "#C05621",
    "table_status_today": "#D62828",
    "table_status_expired": "#8B1E1E",
    "branch_empty": "#7A869A",
    "action_normal_text": "#0F5BFF",
    "action_danger_text": "#D62828",
    "action_normal_bg": "#EAF2FF",
    "action_danger_bg": "#FDECEC",
    "branch_01": "#0F5BFF",
    "branch_02": "#138A43",
    "branch_03": "#B7791F",
    "branch_04": "#7C3AED",
    "branch_05": "#D62828",
    "branch_06": "#0E7490",
    "branch_07": "#C05621",
    "branch_08": "#2F855A",
    "branch_09": "#805AD5",
    "branch_10": "#B83280",
    "branch_11": "#2B6CB0",
    "branch_12": "#4A5568",
    "usage_title": "#0B1B36",
    "usage_muted_text": "#64748B",
    "usage_grid": "#D7DFEA",
    "usage_header_bg": "#EAF2FF",
    "usage_header_text": "#1E3A8A",
    "usage_alt_row_bg": "#F8FAFC",
}


def default_theme_path() -> str:
    return resource_path(*THEME_QSS_RELATIVE_PATH)


@lru_cache(maxsize=1)
def theme_color_tokens() -> dict[str, str]:
    path = Path(default_theme_path())
    try:
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
    except SERVICE_OPERATION_EXCEPTIONS:
        raw = ""
    tokens = dict(DEFAULT_COLOR_TOKENS)
    tokens.update(
        {
            match.group(1).strip(): match.group(2).strip()
            for match in re.finditer(
                "@color\\s+([A-Za-z0-9_\\-]+)\\s*:\\s*(#[0-9A-Fa-f]{3,8})\\s*;", raw
            )
        }
    )
    return tokens


def theme_color(name: str, fallback: str = "text") -> str:
    tokens = theme_color_tokens()
    return tokens.get(
        str(name).strip(),
        tokens.get(str(fallback).strip(), DEFAULT_COLOR_TOKENS.get("text", "black")),
    )


def theme_qcolor(name: str, fallback: str = "text") -> QColor:
    return QColor(theme_color(name, fallback))


APP_BACKGROUND = theme_color("app_background")
SURFACE = theme_color("surface")
TEXT = theme_color("text")
TEXT_MUTED = theme_color("text_muted")
PRIMARY = theme_color("primary")


def qss_url(*parts: str) -> str:
    return resource_path(*parts).replace("\\", "/")


def get_qss_map() -> dict[str, str]:
    return {
        "@ASSET_CHECKMARK@": qss_url("resources", "images", "checkmark.png"),
        "@ASSET_LOGO@": qss_url("resources", "images", "logo.png"),
        "@ASSET_SIDEBAR_BG@": qss_url("resources", "images", "sidebar_bg.png"),
    }


def resolve_qss_placeholders(css: str) -> str:
    for key, value in get_qss_map().items():
        css = css.replace(key, value)
    return css


def load_stylesheet(
    theme_path: str | None = None,
    font_name: str = DEFAULT_FONT_FAMILY,
    font_size_pt: int = DEFAULT_FONT_SIZE_PT,
) -> str:
    css = ""
    packaged_path = Path(default_theme_path())
    requested_path = Path(theme_path) if theme_path else packaged_path
    path = requested_path if requested_path.exists() else packaged_path
    try:
        if path.exists():
            css = path.read_text(encoding="utf-8")
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.exception("Failed to read application stylesheet: %s", path)
        css = ""
    font_size = adaptive_font_point_size(font_size_pt, QApplication.instance())
    css = resolve_qss_placeholders(css)
    prefix = f'* {{ font-family: "{font_name}"; font-size: {font_size}pt; }}\n'
    return prefix + css


def _apply_app_palette(app: QApplication) -> None:
    try:
        palette = app.palette()
        palette.setColor(QPalette.Window, QColor(APP_BACKGROUND))
        palette.setColor(QPalette.Base, QColor(SURFACE))
        palette.setColor(QPalette.AlternateBase, QColor(APP_BACKGROUND))
        palette.setColor(QPalette.Text, QColor(TEXT))
        palette.setColor(QPalette.WindowText, QColor(TEXT))
        palette.setColor(QPalette.ButtonText, QColor(TEXT))
        palette.setColor(QPalette.ToolTipText, QColor(TEXT))
        palette.setColor(QPalette.Highlight, QColor(PRIMARY))
        palette.setColor(QPalette.HighlightedText, QColor(SURFACE))
        palette.setColor(QPalette.PlaceholderText, QColor(TEXT_MUTED))
        app.setPalette(palette)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("app.setPalette failed", exc_info=True)


def apply_app_theme(
    app: QApplication,
    theme_path: str | None = None,
    font_name: str = DEFAULT_FONT_FAMILY,
    font_size_pt: int = DEFAULT_FONT_SIZE_PT,
) -> None:
    try:
        app.setStyle("Fusion")
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("app.setStyle failed", exc_info=True)
    try:
        app.setFont(QFont(font_name, adaptive_font_point_size(font_size_pt, app)))
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("app.setFont failed", exc_info=True)
    _apply_app_palette(app)
    try:
        app.setStyleSheet(load_stylesheet(theme_path, font_name, font_size_pt))
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug("app.setStyleSheet failed", exc_info=True)


def apply_packaged_theme(app: QApplication) -> None:
    try:
        apply_app_theme(app)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.exception("Failed to apply packaged theme")
