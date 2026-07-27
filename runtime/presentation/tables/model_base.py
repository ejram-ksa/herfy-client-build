from __future__ import annotations
from collections.abc import Callable
from typing import Any
from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt

RowNormalizer = Callable[[dict | None], dict[str, Any]]


class BaseDictTableModel(QAbstractTableModel):
    headers: tuple[str, ...] = ()

    def __init__(
        self,
        rows: list[dict] | None = None,
        parent=None,
        *,
        normalizer: RowNormalizer | None = None,
    ) -> None:
        super().__init__(parent)
        self._normalizer: RowNormalizer = normalizer or self._default_normalizer
        self._rows: list[dict[str, Any]] = self._normalize_rows(rows)

    @staticmethod
    def _default_normalizer(row: dict | None) -> dict[str, Any]:
        return dict(row or {})

    def _normalize_rows(self, rows: list[dict] | None) -> list[dict[str, Any]]:
        return [self._normalizer(row) for row in rows or []]

    def replace_rows(self, rows: list[dict] | None) -> None:
        self.beginResetModel()
        self._rows = self._normalize_rows(rows)
        self.endResetModel()

    def load_data(self, rows: list[dict] | None) -> None:
        self.replace_rows(rows)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ):
        if orientation != Qt.Horizontal:
            return (
                super().headerData(section, orientation, role)
                if role == Qt.DisplayRole
                else None
            )
        if 0 <= section < len(self.headers) and role in (
            Qt.DisplayRole,
            Qt.ToolTipRole,
            Qt.AccessibleTextRole,
        ):
            return self.headers[section]
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignCenter)
        return None

    def row_at(self, row: int) -> dict[str, Any] | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None
