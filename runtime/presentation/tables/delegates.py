from __future__ import annotations
from typing import Any
from PyQt5.QtCore import QEvent, QModelIndex, QRect, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen
from PyQt5.QtWidgets import (
    QAbstractItemDelegate,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
)
from runtime.shared.settings.config import _
from runtime.shared.errors import PARSE_OPERATION_EXCEPTIONS
from runtime.shared.numbers import format_plain_number
from runtime.application.services.expiry_status import ExpiryThresholds
from runtime.presentation.tables.headers import COL_ACTIONS
from runtime.presentation.theme import theme_qcolor
from runtime.presentation.widgets import load_asset_icon


class OnHandDelegate(QStyledItemDelegate):
    ROW_PROPERTY = "_usage_row"
    COLUMN_PROPERTY = "_usage_column"

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setProperty("usageEntry", True)
        editor.setAlignment(Qt.AlignCenter)
        editor.setPlaceholderText(_("Quantity"))
        editor.installEventFilter(self)
        editor.returnPressed.connect(lambda ed=editor: self._commit_and_move_down(ed))
        return editor

    def eventFilter(self, obj, event):
        if (
            isinstance(obj, QLineEdit)
            and event.type() == QEvent.KeyPress
            and (event.key() in (Qt.Key_Return, Qt.Key_Enter))
        ):
            self._commit_and_move_down(obj)
            return True
        return super().eventFilter(obj, event)

    def _commit_and_move_down(self, editor: QLineEdit) -> None:
        row, column = self._editor_position(editor)
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QAbstractItemDelegate.NoHint)
        if row >= 0 and column >= 0:
            QTimer.singleShot(0, lambda: self._focus_cell(row + 1, column))

    @classmethod
    def _set_editor_position(cls, editor: QLineEdit, row: int, column: int) -> None:
        editor.setProperty(cls.ROW_PROPERTY, int(row))
        editor.setProperty(cls.COLUMN_PROPERTY, int(column))

    @classmethod
    def _editor_position(cls, editor: QLineEdit) -> tuple[int, int]:
        return (
            cls._editor_int_property(editor, cls.ROW_PROPERTY),
            cls._editor_int_property(editor, cls.COLUMN_PROPERTY),
        )

    @staticmethod
    def _editor_int_property(editor: QLineEdit, name: str) -> int:
        try:
            return int(editor.property(name))
        except (TypeError, ValueError):
            return -1

    def _focus_cell(self, row: int, column: int) -> None:
        table = self.parent()
        model = table.model() if table is not None and hasattr(table, "model") else None
        if model is None or row >= model.rowCount():
            return
        index = model.index(row, column)
        if not index.isValid():
            return
        table.setCurrentIndex(index)
        table.setFocus(Qt.TabFocusReason)
        table.scrollTo(index)
        table.openPersistentEditor(index)
        table.edit(index)
        self._focus_existing_editor(table, index, attempts=6)

    @staticmethod
    def _focus_existing_editor(table, index, *, attempts: int) -> None:
        target_rect = table.visualRect(index)
        for editor in table.viewport().findChildren(QLineEdit):
            if target_rect.intersects(editor.geometry()):
                editor.setFocus(Qt.TabFocusReason)
                editor.selectAll()
                return
        if attempts <= 0:
            return
        table.openPersistentEditor(index)
        table.edit(index)
        QTimer.singleShot(
            15,
            lambda: OnHandDelegate._focus_existing_editor(
                table, index, attempts=attempts - 1
            ),
        )

    def setEditorData(self, editor: QLineEdit, index):
        self._set_editor_position(editor, index.row(), index.column())
        value = index.model().data(index, Qt.EditRole)
        if value in (None, ""):
            editor.clear()
            return
        try:
            editor.setText(format_plain_number(float(value)))
        except PARSE_OPERATION_EXCEPTIONS:
            editor.setText(str(value or ""))

    def setModelData(self, editor: QLineEdit, model, index):
        model.setData(
            index, str(editor.text() or "").replace(",", "").strip(), Qt.EditRole
        )

    def updateEditorGeometry(self, editor: QLineEdit, option, index):
        self._set_editor_position(editor, index.row(), index.column())
        editor.setGeometry(option.rect.adjusted(6, 5, -6, -5))


class ProgressBarDelegate(QStyledItemDelegate):
    TRACK_COLOR = theme_qcolor("progress_track")
    FALLBACK_COLOR = theme_qcolor("progress_fallback")

    def __init__(self, db_manager: Any | None = None, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        self._draw_panel(painter, option)
        progress_value = self._clamped_progress(index.data(Qt.UserRole + 1))
        label = str(index.data(Qt.DisplayRole) or "")
        color = self._status_color(index, progress_value)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        label_rect = option.rect.adjusted(8, 2, -8, -18)
        bar_rect = QRect(
            option.rect.x() + 8,
            option.rect.bottom() - 13,
            max(1, option.rect.width() - 16),
            7,
        )
        font = QFont(option.font)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QPen(color))
        metrics = QFontMetrics(font)
        painter.drawText(
            label_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            metrics.elidedText(label, Qt.ElideRight, max(20, label_rect.width())),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.TRACK_COLOR)
        painter.drawRoundedRect(bar_rect, 4, 4)
        if progress_value > 0:
            fill_rect = QRect(
                bar_rect.x(),
                bar_rect.y(),
                max(5, int(bar_rect.width() * progress_value / 100.0)),
                bar_rect.height(),
            )
            painter.setBrush(color)
            painter.drawRoundedRect(fill_rect, 4, 4)
        painter.restore()

    @staticmethod
    def _draw_panel(painter: QPainter, option) -> None:
        style = option.widget.style() if option.widget is not None else None
        if style is not None:
            style.drawPrimitive(
                QStyle.PE_PanelItemViewItem, option, painter, option.widget
            )

    @staticmethod
    def _clamped_progress(value: Any) -> int:
        try:
            return max(0, min(100, int(value)))
        except PARSE_OPERATION_EXCEPTIONS:
            return 0

    def _status_color(self, index: QModelIndex, progress_value: int) -> QColor:
        days_left = index.data(Qt.UserRole)
        thresholds = ExpiryThresholds.from_settings(self.db_manager)
        if isinstance(days_left, int):
            if days_left < 0:
                return theme_qcolor("status_danger")
            if days_left == 0:
                return theme_qcolor("status_today")
            if days_left <= thresholds.critical_days:
                return theme_qcolor("status_warning")
            if days_left <= thresholds.soon_days:
                return theme_qcolor("status_soon")
            return theme_qcolor("status_ok")
        if progress_value <= 0:
            return self.FALLBACK_COLOR
        return (
            theme_qcolor("status_warning")
            if progress_value < 50
            else theme_qcolor("status_ok")
        )


class ActionDelegate(QStyledItemDelegate):
    EDIT_FALLBACK_TEXT = "✎"
    DELETE_FALLBACK_TEXT = "×"

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self._edit_icon = load_asset_icon("resources", "images", "edit.png")
        self._delete_icon = load_asset_icon("resources", "images", "delete.png")

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        ProgressBarDelegate._draw_panel(painter, option)
        edit_rect, delete_rect = self._button_rects(option.rect)
        self._draw_button(
            painter, edit_rect, self._edit_icon, self.EDIT_FALLBACK_TEXT, danger=False
        )
        self._draw_button(
            painter,
            delete_rect,
            self._delete_icon,
            self.DELETE_FALLBACK_TEXT,
            danger=True,
        )

    def editorEvent(self, event, model, option, index: QModelIndex):
        if event is None or index.column() != COL_ACTIONS:
            return False
        if getattr(event, "type", lambda: None)() != QEvent.MouseButtonRelease:
            return False
        pos = getattr(event, "pos", lambda: None)()
        if pos is None:
            return False
        edit_rect, delete_rect = self._button_rects(option.rect)
        if edit_rect.contains(pos):
            self.page.edit_tracked_product(index.row())
            return True
        if delete_rect.contains(pos):
            self.page.delete_tracked_product(index.row())
            return True
        return False

    @staticmethod
    def _button_rects(cell_rect: QRect) -> tuple[QRect, QRect]:
        available = max(34, cell_rect.width() - 8)
        spacing = 6 if available >= 62 else 3
        button_size = min(
            30, max(18, min(cell_rect.height() - 8, (available - spacing) // 2))
        )
        total_width = button_size * 2 + spacing
        left = cell_rect.x() + max(4, (cell_rect.width() - total_width) // 2)
        top = cell_rect.y() + max(2, (cell_rect.height() - button_size) // 2)
        return (
            QRect(left, top, button_size, button_size),
            QRect(left + button_size + spacing, top, button_size, button_size),
        )

    @staticmethod
    def _draw_button(
        painter: QPainter, rect: QRect, icon: QIcon, fallback_text: str, *, danger: bool
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        if not icon.isNull():
            icon.paint(painter, rect.adjusted(5, 5, -5, -5), Qt.AlignCenter)
        else:
            painter.setPen(
                QPen(
                    theme_qcolor(
                        "action_danger_text" if danger else "action_normal_text"
                    )
                )
            )
            painter.drawText(rect, Qt.AlignCenter, fallback_text)
        painter.restore()
