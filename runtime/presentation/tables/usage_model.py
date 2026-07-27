from __future__ import annotations
import math
from typing import ClassVar, Any
from PyQt5.QtCore import QModelIndex, QSortFilterProxyModel, Qt
from runtime.shared.booleans import parse_bool
from runtime.shared.errors import PARSE_OPERATION_EXCEPTIONS
from runtime.shared.numbers import format_plain_number, parse_plain_number
from runtime.presentation.tables.headers import (
    COL_B,
    COL_H,
    COL_R,
    COL_T,
    COL_U,
    COL_UOM,
    HEADERS_USAGE,
    usage_headers,
)
from runtime.presentation.tables.model_base import BaseDictTableModel


class UsageModel(BaseDictTableModel):
    headers = HEADERS_USAGE
    NUMERIC_COLUMNS = (COL_R, COL_B, COL_T, COL_H, COL_U)
    READONLY_NUMERIC_COLUMNS = (COL_R, COL_B, COL_T)
    USER_INPUT_COLUMNS = (COL_H, COL_U)
    CHANGE_ROLES: ClassVar[tuple[int, ...]] = (
        Qt.DisplayRole,
        Qt.EditRole,
        Qt.UserRole,
    )

    def __init__(self, rows: list[dict] | None = None, parent=None):
        self.headers = usage_headers()
        super().__init__(rows, parent, normalizer=self._normalize_row)

    @staticmethod
    def _to_float(value: Any) -> float:
        return parse_plain_number(value)

    @classmethod
    def _normalize_row(cls, row: dict | None) -> dict[str, Any]:
        source = dict(row or {})
        total = cls._to_float(source.get("total"))
        user_set = parse_bool(source.get("user_set"), False)
        raw_onhand = source.get("onhand")
        if raw_onhand in (None, "") and (not user_set):
            onhand = None
            usage = None
        else:
            onhand = cls._to_float(raw_onhand)
            usage = (
                cls._to_float(source.get("usage", total - onhand)) if user_set else None
            )
        source.update(
            {
                "receipts": cls._to_float(source.get("receipts")),
                "begin": cls._to_float(source.get("begin")),
                "total": total,
                "onhand": onhand,
                "usage": usage,
                "user_set": user_set,
                "material": str(source.get("material", "") or ""),
                "name": str(source.get("name", "") or ""),
                "uom": str(source.get("uom", "") or ""),
            }
        )
        return source

    @staticmethod
    def _entry_key(row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row.get("material", "") or "").strip().lower(),
            str(row.get("name", "") or "").strip().lower(),
            str(row.get("uom", "") or "").strip().lower(),
        )

    def _user_entry_map(self) -> dict[tuple[str, str, str], Any]:
        entries: dict[tuple[str, str, str], Any] = {}
        for row in self._rows:
            if not parse_bool(row.get("user_set"), False):
                continue
            key = self._entry_key(row)
            if key[0] or key[1]:
                entries[key] = row.get("onhand")
        return entries

    def replace_rows_preserving_user_inputs(self, rows: list[dict] | None) -> None:
        previous_entries = self._user_entry_map()
        normalized_rows = [
            self._merge_previous_user_input(
                self._normalize_row(source), previous_entries
            )
            for source in rows or []
        ]
        self.beginResetModel()
        self._rows = normalized_rows
        self.endResetModel()

    def _merge_previous_user_input(
        self, row: dict[str, Any], previous_entries: dict[tuple[str, str, str], Any]
    ) -> dict[str, Any]:
        key = self._entry_key(row)
        if key not in previous_entries:
            return row
        onhand = self._to_float(previous_entries[key])
        total = self._to_float(row.get("total"))
        row["onhand"] = onhand
        row["usage"] = max(0.0, total - onhand)
        row["user_set"] = True
        return row

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == COL_H:
            flags |= Qt.ItemIsEditable
        return flags

    @staticmethod
    def _value(row: dict[str, Any], column: int):
        return {
            0: row.get("material", ""),
            1: row.get("name", ""),
            COL_R: row.get("receipts", 0.0),
            COL_B: row.get("begin", 0.0),
            COL_T: row.get("total", 0.0),
            COL_H: row.get("onhand", 0.0),
            COL_UOM: row.get("uom", ""),
            COL_U: row.get("usage", 0.0),
        }.get(column, "")

    @staticmethod
    def _user_value_visible(row: dict[str, Any]) -> bool:
        return parse_bool(row.get("user_set"), False)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        column = index.column()
        value = self._value(row, column)
        user_value_visible = self._user_value_visible(row)
        if role == Qt.DisplayRole:
            if column in self.READONLY_NUMERIC_COLUMNS:
                return format_plain_number(value)
            if column in self.USER_INPUT_COLUMNS:
                return format_plain_number(value) if user_value_visible else ""
            return str(value or "")
        if role == Qt.EditRole:
            if column == COL_UOM:
                return ""
            if column in self.USER_INPUT_COLUMNS and (not user_value_visible):
                return ""
            return value
        if role == Qt.UserRole:
            if column in self.USER_INPUT_COLUMNS and (not user_value_visible):
                return None
            return value
        if role == Qt.TextAlignmentRole:
            if column in self.NUMERIC_COLUMNS or column in (0, COL_UOM):
                return int(Qt.AlignCenter)
            if column == 1:
                return int(Qt.AlignVCenter | Qt.AlignLeft)
            return int(Qt.AlignCenter)
        if role == Qt.ToolTipRole:
            return None
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if role != Qt.EditRole or not index.isValid() or index.column() != COL_H:
            return False
        row = self._rows[index.row()]
        text = str(value or "").replace(",", "").strip()
        if text == "":
            row["onhand"] = None
            row["usage"] = None
            row["user_set"] = False
            self._emit_onhand_usage_changed(index.row())
            return True
        try:
            onhand = float(text)
        except PARSE_OPERATION_EXCEPTIONS:
            return False
        if not math.isfinite(onhand):
            return False
        onhand = max(0.0, onhand)
        total = self._to_float(row.get("total"))
        row["onhand"] = onhand
        row["usage"] = max(0.0, total - onhand)
        row["user_set"] = True
        self._emit_onhand_usage_changed(index.row())
        return True

    def _emit_onhand_usage_changed(self, row: int) -> None:
        self.dataChanged.emit(
            self.index(row, COL_H), self.index(row, COL_U), self.CHANGE_ROLES
        )


class UsageProxy(QSortFilterProxyModel):
    SEARCH_COLUMNS = (0, 1, COL_UOM)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search = ""
        self._hide_total_zero = False
        self.setDynamicSortFilter(True)

    def set_search(self, value: str) -> None:
        self._search = str(value or "").strip().lower()
        self.invalidateFilter()

    def set_hide_total_zero(self, enabled: bool) -> None:
        self._hide_total_zero = bool(enabled)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return True
        if self._hide_total_zero and self._row_total_is_zero(
            model, source_row, source_parent
        ):
            return False
        return (
            True
            if not self._search
            else self._row_matches_search(model, source_row, source_parent)
        )

    @staticmethod
    def _row_total_is_zero(model, source_row: int, source_parent: QModelIndex) -> bool:
        total_index = model.index(source_row, COL_T, source_parent)
        total = parse_plain_number(model.data(total_index, Qt.UserRole))
        return abs(total) < 1e-09

    def _row_matches_search(
        self, model, source_row: int, source_parent: QModelIndex
    ) -> bool:
        haystack = []
        for column in self.SEARCH_COLUMNS:
            value = model.data(
                model.index(source_row, column, source_parent), Qt.DisplayRole
            )
            haystack.append(str(value or "").lower())
        return self._search in " | ".join(haystack)
