from __future__ import annotations
import logging
from typing import Any
from PyQt5.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDateEdit,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
)
from runtime.shared.settings.config import _
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS

logger = logging.getLogger(__name__)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _tooltip_from_text(widget: Any, value: str | None = None) -> None:
    text = _clean_text(value)
    if not text and hasattr(widget, "text"):
        try:
            text = _clean_text(widget.text())
        except UI_OPERATION_EXCEPTIONS:
            text = ""
    if not text and hasattr(widget, "placeholderText"):
        try:
            text = _clean_text(widget.placeholderText())
        except UI_OPERATION_EXCEPTIONS:
            text = ""
    if not text:
        return
    try:
        if not _clean_text(widget.toolTip()):
            widget.setToolTip(text)
    except UI_OPERATION_EXCEPTIONS:
        return


def polish_text_visibility(root: Any) -> None:
    if root is None:
        return
    try:
        labels = root.findChildren(QLabel) if hasattr(root, "findChildren") else []
        for label in labels:
            text = _clean_text(label.text())
            if text:
                _tooltip_from_text(label, text)
            try:
                label.setMinimumWidth(0)
                label.setSizePolicy(
                    QSizePolicy.Preferred, label.sizePolicy().verticalPolicy()
                )
            except UI_OPERATION_EXCEPTIONS:
                continue
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("polish_text_visibility label pass failed", exc_info=True)
    try:
        for button in root.findChildren(QAbstractButton):
            _tooltip_from_text(button)
            try:
                button.setMinimumHeight(max(button.minimumHeight(), 24))
                button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            except UI_OPERATION_EXCEPTIONS:
                continue
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("polish_text_visibility button pass failed", exc_info=True)
    try:
        input_types = (QLineEdit, QComboBox, QDateEdit, QSpinBox, QTextEdit)
        for widget in root.findChildren(input_types):
            _tooltip_from_text(widget)
            try:
                if not isinstance(widget, QTextEdit):
                    widget.setMinimumHeight(max(widget.minimumHeight(), 24))
                widget.setMinimumWidth(0)
                widget.setSizePolicy(
                    QSizePolicy.Expanding, widget.sizePolicy().verticalPolicy()
                )
            except UI_OPERATION_EXCEPTIONS:
                continue
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("polish_text_visibility input pass failed", exc_info=True)


def result_count_text(
    count: int, *, singular: str | None = None, plural: str | None = None
) -> str:
    total = int(count or 0)
    if total == 1:
        return singular or _("1 item")
    return (plural or _("{count} items")).format(count=total)


def set_empty_state(label: Any, *, is_empty: bool, message: str | None = None) -> None:
    if label is None:
        return
    try:
        label.setVisible(bool(is_empty))
        if message is not None:
            label.setText(str(message))
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("set_empty_state failed", exc_info=True)


def set_table_count_text(label: Any, text: str) -> None:
    if label is None:
        return
    try:
        label.setText(str(text or ""))
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("set_table_count_text failed", exc_info=True)


def set_status_label_text(label: Any, text: str = "", *, role: str = "muted") -> None:
    if label is None:
        return
    try:
        label.setText(str(text or ""))
        label.setProperty("statusRole", str(role or "muted"))
        refresh_qt_style(label)
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("set_status_label_text failed", exc_info=True)


def refresh_qt_style(widget: Any) -> None:
    if widget is None:
        return
    try:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        update = getattr(widget, "update", None)
        if callable(update):
            update()
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("refresh_qt_style failed", exc_info=True)
