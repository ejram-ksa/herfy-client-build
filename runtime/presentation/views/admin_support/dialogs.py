from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

from typing import Any
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidgetItem
from runtime.domain.access import normalize_role


def _text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def _first(row: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return _text(value)
    return default


def _item(value: Any) -> QTableWidgetItem:
    item = QTableWidgetItem(_text(value, "—") or "—")
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    return item


def _role_key(row: dict[str, Any]) -> str:
    return normalize_role(row.get("role") or row.get("role_key"))


def _server_role_key(row: dict[str, Any]) -> str:
    raw = _first(row, "role_key", "role")
    return raw or _role_key(row)


def _list_values(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = []
    return [str(item or "").strip() for item in raw if str(item or "").strip()]


def _row_values(row: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        values = _list_values(row.get(key))
        if values:
            return values
    scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
    for key in keys:
        values = _list_values(scope.get(key))
        if values:
            return values
    return []


def _branch_code(row: dict[str, Any]) -> str:
    return _first(row, "branch_id", "branch_code", "code", "id")


def _area_code(row: dict[str, Any]) -> str:
    return _first(row, "area_id", "area_code", "area_name", "id")


def _region_code(row: dict[str, Any]) -> str:
    return _first(row, "region_id", "region_code", "region_name", "id")


def _branch_manager(row: dict[str, Any]) -> str:
    return _first(
        row,
        "branch_manager_id",
        "branch_manager_user_id",
        "manager_username",
        "manager_id",
        "area_manager_id",
    )


from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
)
from runtime.shared.settings.config import _
from runtime.application.services.admin import parse_bulk_branch_lines


class _AdminMetricCard(QFrame):

    def __init__(self, title: str, value: str = "0", hint: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("AdminMetricCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("AdminMetricValue")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("AdminMetricTitle")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("AdminMetricHint")
        self.hint_label.setWordWrap(True)
        lay.addWidget(self.value_label)
        lay.addWidget(self.title_label)
        lay.addWidget(self.hint_label)

    def set_value(self, value: Any) -> None:
        self.value_label.setText(_text(value, "0") or "0")


class _AdminFormDialog(QDialog):

    def __init__(self, title: str, fields: list[tuple[str, str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("AdminFormDialog")
        self.setWindowTitle(_(title))
        self._inputs: dict[str, QLineEdit] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        heading = QLabel(_(title))
        heading.setObjectName("AdminFormTitle")
        root.addWidget(heading)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        for key, label, value in fields:
            edit = QLineEdit(_text(value))
            edit.setObjectName("AdminInput")
            edit.setMinimumHeight(32)
            self._inputs[key] = edit
            form.addRow(_(label), edit)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict[str, str]:
        return {key: _text(widget.text()) for key, widget in self._inputs.items()}


class _AdminPasswordDialog(QDialog):

    def __init__(self, username: str, parent=None):
        super().__init__(parent)
        self.setObjectName("AdminFormDialog")
        self.setWindowTitle(_("Reset password"))
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        title = QLabel(_("Reset password"))
        title.setObjectName("AdminFormTitle")
        hint = QLabel(
            _("Set a temporary password for {username}.").format(username=username)
        )
        hint.setObjectName("AdminHintText")
        hint.setWordWrap(True)
        self.password = QLineEdit()
        self.password.setObjectName("AdminInput")
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setMinimumHeight(32)
        form = QFormLayout()
        form.addRow(_("Temporary password"), self.password)
        root.addWidget(title)
        root.addWidget(hint)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def value(self) -> str:
        return _text(self.password.text())


class _AdminStructureWizardDialog(QDialog):

    def __init__(
        self,
        kind: str,
        snapshot: dict[str, Any],
        *,
        existing: dict[str, Any] | None = None,
        default_parent: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.kind = _text(kind, "region")
        self.snapshot = dict(snapshot or {})
        self.existing = dict(existing or {})
        self.setObjectName("AdminFormDialog")
        self.setWindowTitle(_(self._title()))
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        heading = QLabel(_(self._title()))
        heading.setObjectName("AdminFormTitle")
        root.addWidget(heading)
        hint = QLabel(_(self._hint()))
        hint.setObjectName("AdminHintText")
        hint.setWordWrap(True)
        root.addWidget(hint)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.code = QLineEdit(self._existing_code())
        self.code.setObjectName("AdminInput")
        self.name = QLineEdit(
            _first(self.existing, "name", default=self._existing_code())
        )
        self.name.setObjectName("AdminInput")
        form.addRow(_(self._code_label()), self.code)
        form.addRow(_("Name"), self.name)
        self.parent_combo: QComboBox | None = None
        parent_value = default_parent or self._existing_parent()
        if self.kind in {"area", "branch"}:
            self.parent_combo = QComboBox()
            self.parent_combo.setObjectName("AdminFilterCombo")
            self.parent_combo.setEditable(True)
            rows = (
                self.snapshot.get("regions") or []
                if self.kind == "area"
                else self.snapshot.get("areas") or []
            )
            key_fn = _region_code if self.kind == "area" else _area_code
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = key_fn(row)
                if code:
                    self.parent_combo.addItem(
                        f"{code} - {row.get('name') or code}", code
                    )
            if parent_value:
                self._set_combo_value(self.parent_combo, parent_value)
            form.addRow(_(self._parent_label()), self.parent_combo)
        self.manager_combo = QComboBox()
        self.manager_combo.setObjectName("AdminFilterCombo")
        self.manager_combo.setEditable(True)
        self.manager_combo.addItem("", "")
        current_manager = self._existing_manager()
        for user in self._manager_candidates():
            username = _first(user, "username", "user_id", "uid")
            if not username:
                continue
            role = _server_role_key(user)
            self.manager_combo.addItem(f"{username} - {role}", username)
        if current_manager:
            self._set_combo_value(self.manager_combo, current_manager)
        form.addRow(_(self._manager_label()), self.manager_combo)
        root.addLayout(form)
        self.bulk_branches: QPlainTextEdit | None = None
        if self.kind == "area" and (not self.existing):
            self.bulk_branches = QPlainTextEdit()
            self.bulk_branches.setObjectName("AdminBulkBranchesInput")
            self.bulk_branches.setPlaceholderText(
                _("Optional branches, one per line: H1026, Branch name")
            )
            self.bulk_branches.setMinimumHeight(90)
            root.addWidget(QLabel(_("Branches under this area")))
            root.addWidget(self.bulk_branches)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _title(self) -> str:
        return {
            "region": "Region setup",
            "area": "Area setup",
            "branch": "Branch setup",
        }.get(self.kind, "Structure setup")

    def _hint(self) -> str:
        return {
            "region": "Create the Region and assign its Regional Manager.",
            "area": "Create the Area under a Region, assign its Area Manager, and optionally add its branches.",
            "branch": "Create the Branch under an Area and assign its Branch Manager.",
        }.get(self.kind, "")

    def _code_label(self) -> str:
        return {
            "region": "Region code",
            "area": "Area code",
            "branch": "Branch code",
        }.get(self.kind, "Code")

    def _parent_label(self) -> str:
        return "Parent region" if self.kind == "area" else "Parent area"

    def _manager_label(self) -> str:
        return {
            "region": "Regional Manager",
            "area": "Area Manager",
            "branch": "Branch Manager",
        }.get(self.kind, "Manager")

    def _existing_code(self) -> str:
        if self.kind == "region":
            return _region_code(self.existing)
        if self.kind == "area":
            return _area_code(self.existing)
        if self.kind == "branch":
            return _branch_code(self.existing)
        return _first(self.existing, "id", "code")

    def _existing_parent(self) -> str:
        if self.kind == "area":
            return _region_code(self.existing)
        if self.kind == "branch":
            return _area_code(self.existing)
        return ""

    def _existing_manager(self) -> str:
        if self.kind == "branch":
            return _branch_manager(self.existing)
        return _first(
            self.existing,
            f"{self.kind}_manager_id",
            f"{self.kind}_manager_user_id",
            "manager_username",
            "manager_id",
        )

    def _manager_candidates(self) -> list[dict[str, Any]]:
        desired = {
            "region": "region_manager",
            "area": "area_manager",
            "branch": "branch_manager",
        }.get(self.kind, "")
        users = [
            row for row in self.snapshot.get("users") or [] if isinstance(row, dict)
        ]
        filtered = [row for row in users if _role_key(row) == desired]
        return filtered or users

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        value = _text(value)
        idx = combo.findData(value)
        if idx < 0:
            idx = combo.findText(value)
        if idx < 0 and value:
            combo.addItem(value, value)
            idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    @staticmethod
    def _combo_value(combo: QComboBox | None) -> str:
        if combo is None:
            return ""
        return _text(combo.currentData() or combo.currentText())

    def values(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "code": _text(self.code.text()),
            "name": _text(self.name.text()),
            "parent": self._combo_value(self.parent_combo),
            "manager": self._combo_value(self.manager_combo),
            "bulk_branches": parse_bulk_branch_lines(
                self.bulk_branches.toPlainText().splitlines()
                if self.bulk_branches
                else []
            ),
        }


# --- package exports ---
__all__ = [
    "_AdminFormDialog",
    "_AdminMetricCard",
    "_AdminPasswordDialog",
    "_AdminStructureWizardDialog",
    "_area_code",
    "_branch_code",
    "_branch_manager",
    "_first",
    "_item",
    "_list_values",
    "_region_code",
    "_role_key",
    "_row_values",
    "_server_role_key",
    "_text",
]
