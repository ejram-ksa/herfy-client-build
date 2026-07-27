from __future__ import annotations
import logging
from typing import Any
from PyQt5.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSplitter,
    QTableView,
    QTableWidget,
    QTextEdit,
    QWidget,
)
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from .profiles import ResponsiveProfile
from .tables import configure_table_layout

logger = logging.getLogger(__name__)
_ICON_BUTTON_OBJECTS = {
    "NotifWrap",
    "NotificationsButton",
    "NotifBadge",
    "TopBarActionButton",
    "TopMainMenuButton",
}
_FIXED_WIDTH_OBJECTS = {"Sidebar"}
_FIXED_HEIGHT_OBJECTS = {"ShellStatusBar", "TopBar"}


def _object_name(widget: Any) -> str:
    try:
        return str(widget.objectName() or "")
    except UI_OPERATION_EXCEPTIONS:
        return ""


def _safe_set_policy(widget: QWidget, horizontal, vertical) -> None:
    try:
        widget.setSizePolicy(horizontal, vertical)
    except UI_OPERATION_EXCEPTIONS:
        logger.debug(
            "set size policy failed for %s", _object_name(widget), exc_info=True
        )


def _clear_conflicting_width_limits(widget: QWidget) -> None:
    name = _object_name(widget)
    if name in _FIXED_WIDTH_OBJECTS or name in _ICON_BUTTON_OBJECTS:
        return
    try:
        if widget.minimumWidth() > 0:
            widget.setMinimumWidth(0)
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("clear width limits failed for %s", name, exc_info=True)


def _normalise_labels(root: QWidget) -> None:
    for label in root.findChildren(QLabel):
        name = _object_name(label)
        if name in _ICON_BUTTON_OBJECTS:
            continue
        try:
            text = " ".join(str(label.text() or "").split())
            if text and (not str(label.toolTip() or "").strip()):
                label.setToolTip(text)
            label.setWordWrap(False)
            _clear_conflicting_width_limits(label)
            _safe_set_policy(
                label, QSizePolicy.Preferred, label.sizePolicy().verticalPolicy()
            )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("label layout normalization failed", exc_info=True)


def _normalise_inputs(root: QWidget, profile: ResponsiveProfile) -> None:
    input_types = (QLineEdit, QComboBox, QTextEdit)
    min_height = (
        profile.control_height if not profile.touch_mode else profile.touch_target
    )
    for widget in root.findChildren(input_types):
        try:
            _clear_conflicting_width_limits(widget)
            if not isinstance(widget, QTextEdit):
                widget.setMinimumHeight(max(widget.minimumHeight(), min_height))
            _safe_set_policy(
                widget, QSizePolicy.Expanding, widget.sizePolicy().verticalPolicy()
            )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("input layout normalization failed", exc_info=True)


def _normalise_buttons(root: QWidget, profile: ResponsiveProfile) -> None:
    min_height = (
        profile.control_height if not profile.touch_mode else profile.touch_target
    )
    for button in root.findChildren(QAbstractButton):
        name = _object_name(button)
        try:
            if name not in _ICON_BUTTON_OBJECTS:
                _clear_conflicting_width_limits(button)
            if name not in _ICON_BUTTON_OBJECTS:
                button.setMinimumHeight(max(button.minimumHeight(), min_height))
            if name not in _ICON_BUTTON_OBJECTS and name != "SidebarButton":
                _safe_set_policy(button, QSizePolicy.Preferred, QSizePolicy.Fixed)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("button layout normalization failed", exc_info=True)


def _normalise_tables(root: QWidget, profile: ResponsiveProfile) -> None:
    if profile.visual_breakpoint == "small_terminal":
        min_height = 160
    elif profile.visual_breakpoint == "hd_720":
        min_height = 180
    elif profile.visual_breakpoint == "laptop_768":
        min_height = 210
    else:
        min_height = 230 if profile.is_narrow else 280 if profile.is_tablet else 320
    for table in root.findChildren((QTableView, QTableWidget)):
        try:
            configure_table_layout(
                table, window_width=profile.width, show_grid=True, min_height=min_height
            )
            _safe_set_policy(table, QSizePolicy.Expanding, QSizePolicy.Expanding)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("table layout normalization failed", exc_info=True)


def _normalise_frames(root: QWidget) -> None:
    for frame in root.findChildren(QFrame):
        name = _object_name(frame)
        if name in _FIXED_WIDTH_OBJECTS or name in _FIXED_HEIGHT_OBJECTS:
            continue
        try:
            _clear_conflicting_width_limits(frame)
            _safe_set_policy(
                frame, QSizePolicy.Preferred, frame.sizePolicy().verticalPolicy()
            )
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("frame layout normalization failed", exc_info=True)


def _normalise_splitters(root: QWidget, profile: ResponsiveProfile) -> None:
    for splitter in root.findChildren(QSplitter):
        try:
            splitter.setChildrenCollapsible(False)
            if profile.supports_split_admin_workspace:
                splitter.setHandleWidth(max(6, profile.gap))
            else:
                splitter.setHandleWidth(max(8, profile.gap + 2))
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("splitter layout normalization failed", exc_info=True)


def enforce_layout_contract(root: QWidget | None, profile: ResponsiveProfile) -> None:
    if root is None:
        return
    try:
        _normalise_frames(root)
        _normalise_labels(root)
        _normalise_inputs(root, profile)
        _normalise_buttons(root, profile)
        _normalise_tables(root, profile)
        _normalise_splitters(root, profile)
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("global layout contract failed", exc_info=True)
