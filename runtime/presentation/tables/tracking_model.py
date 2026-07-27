from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar, Any
from PyQt5.QtCore import QModelIndex, QSize, Qt
from PyQt5.QtGui import QColor
from runtime.shared.settings.config import _
from runtime.shared.objects import normalize_int, safe_get
from runtime.domain.tracking_models import TrackingKey
from runtime.domain.tracking_rows import tracking_key_from_row, tracking_key_sort_value
from runtime.application.services.expiry_status import ExpiryThresholds, classify_tracking_row
from runtime.application.services.tracking import canonical_tracking_row
from runtime.presentation.tables.headers import (
    COL_ACTIONS,
    COL_BRANCH,
    COL_EXPIRY,
    COL_MATERIAL,
    COL_NAME,
    COL_PRODUCTION,
    COL_QTY,
    COL_STATUS,
    TRACKING_HEADERS,
    tracking_headers,
)
from runtime.presentation.tables.model_base import BaseDictTableModel
from runtime.presentation.theme import theme_color, theme_qcolor


@dataclass(frozen=True, slots=True)
class TrackingTableDiff:
    inserted: tuple[dict[str, Any], ...] = ()
    updated: tuple[dict[str, Any], ...] = ()
    deleted: tuple[TrackingKey, ...] = ()


class TrackedProductsTableModel(BaseDictTableModel):
    headers = TRACKING_HEADERS
    BRANCH_PALETTE = tuple((theme_color(f"branch_{idx:02d}") for idx in range(1, 13)))
    STATUS_COLORS: ClassVar[dict[str, object]] = {
        "expired": theme_qcolor("table_status_expired"),
        "expires_today": theme_qcolor("table_status_today"),
        "expires_tomorrow": theme_qcolor("table_status_after"),
        "expiring_high": theme_qcolor("status_warning"),
        "expiring_soon": theme_qcolor("table_status_soon"),
        "valid": theme_qcolor("table_status_valid"),
        "missing_expiry": theme_qcolor("branch_empty"),
    }

    def __init__(
        self, rows: list[dict] | None = None, db_manager: Any | None = None, parent=None
    ):
        self.headers = tracking_headers()
        super().__init__(rows, parent, normalizer=self._normalize_row)
        self.db_manager = db_manager

    @staticmethod
    def _normalize_row(row: dict | None) -> dict[str, Any]:
        return canonical_tracking_row(row)

    def flags(self, index: QModelIndex):
        return (
            Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if index.isValid()
            else Qt.NoItemFlags
        )

    def get_product_id(self, row: int) -> str | None:
        if not 0 <= row < len(self._rows):
            return None
        text = str(safe_get(self._rows[row], "id", "") or "").strip()
        return text or None

    def key_at(self, row: int) -> TrackingKey | None:
        if not 0 <= row < len(self._rows):
            return None
        return tracking_key_from_row(self._rows[row])

    def row_for_key(self, key: TrackingKey) -> int | None:
        for index, row in enumerate(self._rows):
            if tracking_key_from_row(row) == key:
                return index
        return None

    def replace_snapshot(self, snapshot: Any) -> None:
        records = getattr(snapshot, "records", snapshot)
        rows = [
            self._row_from_record(record) if hasattr(record, "key") else dict(record)
            for record in records or ()
        ]
        self._replace_by_stable_diff(rows)

    def apply_diff(self, diff: TrackingTableDiff | Any) -> None:
        deleted = tuple(getattr(diff, "deleted", ()) or ())
        updated = tuple(getattr(diff, "updated", ()) or ())
        inserted = tuple(getattr(diff, "inserted", ()) or ())
        for key in sorted(deleted, key=tracking_key_sort_value, reverse=True):
            row = self.row_for_key(key)
            if row is None:
                continue
            self.beginRemoveRows(QModelIndex(), row, row)
            self._rows.pop(row)
            self.endRemoveRows()
        for record in updated:
            row_data = (
                self._row_from_record(record)
                if hasattr(record, "key")
                else dict(record)
            )
            key = tracking_key_from_row(row_data)
            row = self.row_for_key(key) if key is not None else None
            if row is None:
                inserted = (*inserted, row_data)
                continue
            self._rows[row] = self._normalizer(row_data)
            top_left = self.index(row, 0)
            bottom_right = self.index(row, max(0, self.columnCount() - 1))
            self.dataChanged.emit(top_left, bottom_right, [])
        for record in inserted:
            row_data = (
                self._row_from_record(record)
                if hasattr(record, "key")
                else dict(record)
            )
            normalized = self._normalizer(row_data)
            row = len(self._rows)
            self.beginInsertRows(QModelIndex(), row, row)
            self._rows.append(normalized)
            self.endInsertRows()

    def _replace_by_stable_diff(self, rows: list[dict[str, Any]]) -> None:
        old_by_key = {
            key: row
            for row in self._rows
            for key in (tracking_key_from_row(row),)
            if key is not None
        }
        new_by_key = {
            key: self._normalizer(row)
            for row in rows
            for key in (tracking_key_from_row(row),)
            if key is not None
        }
        if len(new_by_key) != len(rows) or len(old_by_key) != len(self._rows):
            self.beginResetModel()
            self._rows = self._normalize_rows(rows)
            self.endResetModel()
            return
        old_keys = set(old_by_key)
        new_keys = set(new_by_key)
        for key in sorted(old_keys - new_keys, key=tracking_key_sort_value, reverse=True):
            row = self.row_for_key(key)
            if row is None:
                continue
            self.beginRemoveRows(QModelIndex(), row, row)
            self._rows.pop(row)
            self.endRemoveRows()
        for key in sorted(new_keys - old_keys, key=tracking_key_sort_value):
            row = len(self._rows)
            self.beginInsertRows(QModelIndex(), row, row)
            self._rows.append(new_by_key[key])
            self.endInsertRows()
        for key in sorted(old_keys & new_keys, key=tracking_key_sort_value):
            if old_by_key[key] == new_by_key[key]:
                continue
            row = self.row_for_key(key)
            if row is None:
                continue
            self._rows[row] = new_by_key[key]
            self.dataChanged.emit(
                self.index(row, 0),
                self.index(row, max(0, self.columnCount() - 1)),
                [],
            )

    @staticmethod
    def _row_from_record(record: Any) -> dict[str, Any]:
        key = record.key
        return {
            "id": getattr(record.remote_id, "value", ""),
            "doc_id": getattr(record.remote_id, "value", ""),
            "branch": key.branch_code,
            "branch_code": key.branch_code,
            "material_number": key.material_number,
            "name": record.product_name,
            "quantity": record.quantity,
            "production_date": (
                key.production_date.isoformat() if key.production_date else ""
            ),
            "expiry_date": key.expiry_date.isoformat(),
            "revision": record.revision,
            "updated_at": record.updated_at.isoformat(),
        }

    def _thresholds(self) -> ExpiryThresholds:
        return ExpiryThresholds.from_settings(self.db_manager)

    @classmethod
    def _branch_color(cls, branch: str) -> QColor:
        key = str(branch or "").strip().upper()
        if not key:
            return theme_qcolor("branch_empty")
        return QColor(
            cls.BRANCH_PALETTE[sum((ord(ch) for ch in key)) % len(cls.BRANCH_PALETTE)]
        )

    def _status_payload(self, row: dict[str, Any]) -> tuple[str, int, int | None, str]:
        status = classify_tracking_row(row, self._thresholds())
        return (status.display_text, status.progress, status.days_left, status.key)

    @staticmethod
    def _display_mapping(row: dict[str, Any], status_text: str = "") -> dict[int, Any]:
        return {
            COL_BRANCH: str(safe_get(row, "branch", "") or ""),
            COL_MATERIAL: str(safe_get(row, "material_number", "") or ""),
            COL_NAME: str(safe_get(row, "name", "") or ""),
            COL_QTY: normalize_int(safe_get(row, "quantity", 0), 0),
            COL_PRODUCTION: str(safe_get(row, "production_date", "") or ""),
            COL_EXPIRY: str(safe_get(row, "expiry_date", "") or ""),
            COL_STATUS: status_text,
            COL_ACTIONS: "",
        }

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        column = index.column()
        status_text = ""
        progress = 0
        days_left = None
        status_key = ""
        if column == COL_STATUS:
            status_text, progress, days_left, status_key = self._status_payload(row)
        mapping = self._display_mapping(row, status_text)
        if role == Qt.DisplayRole:
            value = mapping.get(column, "")
            return str(value) if column == COL_QTY else value
        if role == Qt.UserRole:
            return days_left if column == COL_STATUS else mapping.get(column, "")
        if role == Qt.ToolTipRole:
            if column == COL_STATUS:
                parts = [
                    f"{_('Product Name')}: {safe_get(row, 'name', '')}",
                    f"{_('Restaurant branch')}: {safe_get(row, 'branch', '')}",
                    f"{_('Expiry Date')}: {safe_get(row, 'expiry_date', '')}",
                    str(status_text),
                ]
                return "\n".join(
                    (str(part) for part in parts if str(part or "").strip())
                )
            if column == COL_ACTIONS:
                return _("Edit or delete this food item.")
            return str(mapping.get(column, "") or "")
        if role == Qt.TextAlignmentRole:
            if column in {
                COL_BRANCH,
                COL_MATERIAL,
                COL_QTY,
                COL_PRODUCTION,
                COL_EXPIRY,
                COL_STATUS,
                COL_ACTIONS,
            }:
                return int(Qt.AlignCenter)
            if column == COL_NAME:
                return int(Qt.AlignVCenter | Qt.AlignLeft)
            return int(Qt.AlignCenter)
        if role == Qt.SizeHintRole and column == COL_ACTIONS:
            return QSize(88, 34)
        if role == Qt.ForegroundRole and column == COL_BRANCH:
            return self._branch_color(str(safe_get(row, "branch", "") or ""))
        if role == Qt.ForegroundRole and column == COL_STATUS:
            return self.STATUS_COLORS.get(status_key)
        if role == Qt.UserRole + 1 and column == COL_STATUS:
            return progress
        return None
