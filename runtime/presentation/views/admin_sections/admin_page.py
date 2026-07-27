from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

import logging
from typing import Any
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from runtime.shared.settings.config import _
from runtime.shared.booleans import parse_bool
from runtime.presentation.views.admin_support import (
    _AdminFormDialog,
    _AdminStructureWizardDialog,
    _area_code,
    _branch_code,
    _branch_manager,
    _first,
    _item,
    _region_code,
    _row_values,
    _server_role_key,
    _text,
)

logger = logging.getLogger(__name__)


class AdminHierarchyMixin:

    def _panel(self, title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setObjectName("AdminPanel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        heading = QLabel(_(title))
        heading.setObjectName("AdminPanelTitle")
        lay.addWidget(heading)
        if hint:
            help_label = QLabel(_(hint))
            help_label.setObjectName("AdminHintText")
            help_label.setWordWrap(True)
            lay.addWidget(help_label)
        return (panel, lay)

    def _build_hierarchy_page(self) -> QWidget:
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        left, left_lay = self._panel(
            _("Administrative hierarchy"),
            _("Region, area, branch, manager, and user scope from the server."),
        )
        self.hierarchy_search = QLineEdit()
        self.hierarchy_search.setObjectName("AdminSearchInput")
        self.hierarchy_search.setPlaceholderText(
            _("Search region, area, branch, or manager...")
        )
        self.hierarchy_search.textChanged.connect(self._render_hierarchy)
        left_lay.addWidget(self.hierarchy_search)
        self.hierarchy_tree = QTreeWidget()
        self.hierarchy_tree.setObjectName("AdminHierarchyTree")
        self.hierarchy_tree.setHeaderLabels([_("Hierarchy"), _("Manager / Count")])
        self.hierarchy_tree.setAlternatingRowColors(True)
        self.hierarchy_tree.setRootIsDecorated(True)
        self.hierarchy_tree.setUniformRowHeights(True)
        self.hierarchy_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.hierarchy_tree.itemSelectionChanged.connect(self._render_hierarchy_detail)
        left_lay.addWidget(self.hierarchy_tree, 1)
        create_bar = QHBoxLayout()
        self.new_region_button = QPushButton(_("New region"))
        self.new_area_button = QPushButton(_("New area"))
        self.new_branch_button = QPushButton(_("New branch"))
        for button in (
            self.new_region_button,
            self.new_area_button,
            self.new_branch_button,
        ):
            button.setObjectName("AdminActionButton")
        self.new_region_button.clicked.connect(
            lambda: self._open_structure_wizard("region")
        )
        self.new_area_button.clicked.connect(
            lambda: self._open_structure_wizard(
                "area", default_parent=self._default_parent_for("area")
            )
        )
        self.new_branch_button.clicked.connect(
            lambda: self._open_structure_wizard(
                "branch", default_parent=self._default_parent_for("branch")
            )
        )
        create_bar.addWidget(self.new_region_button)
        create_bar.addWidget(self.new_area_button)
        create_bar.addWidget(self.new_branch_button)
        left_lay.addLayout(create_bar)
        right, right_lay = self._panel(
            _("Selected scope"),
            _(
                "Inspect branches and users linked to the selected administrative level."
            ),
        )
        self.hierarchy_title = QLabel(_("Select a scope"))
        self.hierarchy_title.setObjectName("AdminHierarchyTitle")
        self.hierarchy_meta = QLabel("")
        self.hierarchy_meta.setObjectName("AdminHintText")
        self.hierarchy_meta.setWordWrap(True)
        right_lay.addWidget(self.hierarchy_title)
        right_lay.addWidget(self.hierarchy_meta)
        self.hierarchy_branch_table = self._table(
            [
                _("Region"),
                _("Area"),
                _("Branch"),
                _("Branch manager"),
                _("Branch user"),
                _("User role"),
            ]
        )
        right_lay.addWidget(self.hierarchy_branch_table, 2)
        self.hierarchy_user_table = self._table(
            [_("User"), _("Role"), _("Active branch"), _("Scope"), _("Status")]
        )
        right_lay.addWidget(self.hierarchy_user_table, 1)
        actions = QHBoxLayout()
        self.hierarchy_assign_manager_button = QPushButton(_("Assign manager"))
        self.hierarchy_edit_button = QPushButton(_("Edit selected scope"))
        self.hierarchy_open_structure_button = QPushButton(_("Open Structure"))
        for button in (
            self.hierarchy_assign_manager_button,
            self.hierarchy_edit_button,
            self.hierarchy_open_structure_button,
        ):
            button.setObjectName("AdminActionButton")
        self.hierarchy_assign_manager_button.clicked.connect(
            self._assign_selected_hierarchy_manager
        )
        self.hierarchy_edit_button.clicked.connect(self._edit_selected_hierarchy_scope)
        self.hierarchy_open_structure_button.clicked.connect(
            lambda: self._show_route("structure")
        )
        actions.addWidget(self.hierarchy_assign_manager_button)
        actions.addWidget(self.hierarchy_edit_button)
        actions.addStretch(1)
        actions.addWidget(self.hierarchy_open_structure_button)
        right_lay.addLayout(actions)
        root.addWidget(left, 1)
        root.addWidget(right, 2)
        return page

    def _hierarchy_rows(
        self,
    ) -> tuple[
        dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]
    ]:
        regions: dict[str, dict[str, Any]] = {}
        areas: dict[str, dict[str, Any]] = {}
        branches: list[dict[str, Any]] = []
        for row in self._snapshot.get("regions") or []:
            if not isinstance(row, dict):
                continue
            region_id = _region_code(row)
            if region_id:
                regions[region_id] = dict(row, region_id=region_id)
        for row in self._snapshot.get("areas") or []:
            if not isinstance(row, dict):
                continue
            area_id = _area_code(row)
            if not area_id:
                continue
            region_id = _region_code(row)
            areas[area_id] = dict(row, area_id=area_id, region_id=region_id)
            if region_id and region_id not in regions:
                regions[region_id] = {"region_id": region_id, "name": region_id}
        for row in self._snapshot.get("branches") or []:
            if not isinstance(row, dict):
                continue
            branch_id = _branch_code(row)
            if not branch_id:
                continue
            area_id = _area_code(row)
            region_id = _region_code(row)
            if area_id and area_id in areas and (not region_id):
                region_id = _region_code(areas[area_id])
            normalized = dict(
                row,
                branch_id=branch_id,
                area_id=area_id,
                region_id=region_id,
                branch_manager_id=_branch_manager(row),
            )
            branches.append(normalized)
            if region_id and region_id not in regions:
                regions[region_id] = {"region_id": region_id, "name": region_id}
            if area_id and area_id not in areas:
                areas[area_id] = {
                    "area_id": area_id,
                    "region_id": region_id,
                    "name": area_id,
                }
        return (regions, areas, branches)

    def _users_for_scope(
        self, kind: str, scope_id: str, branches: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        scope_id = _text(scope_id).lower()
        branch_ids = {
            _branch_code(row).lower()
            for row in branches
            if kind in {"region", "area"} or _branch_code(row).lower() == scope_id
        }
        out: list[dict[str, Any]] = []
        for row in self._snapshot.get("users") or []:
            if not isinstance(row, dict):
                continue
            username = _first(row, "username", "user_id", "uid").lower()
            active_branch = _first(row, "active_branch", "branch_id").lower()
            region_values = {
                v.lower()
                for v in _row_values(row, "regions", "region_scope", "region_ids")
            }
            area_values = {
                v.lower() for v in _row_values(row, "areas", "area_scope", "area_ids")
            }
            branch_values = {
                v.lower()
                for v in _row_values(
                    row, "branches", "branch_scope", "branch_ids", "assigned_branch_ids"
                )
            }
            direct_branch_match = (
                username in branch_ids
                or active_branch in branch_ids
                or bool(branch_values & branch_ids)
            )
            matched = False
            if kind == "region":
                matched = scope_id in region_values or direct_branch_match
            elif kind == "area":
                matched = scope_id in area_values or direct_branch_match
            elif kind == "branch":
                matched = scope_id in {username, active_branch, *branch_values}
            if matched:
                out.append(row)
        return out

    def _branch_user_row(self, branch_id: str) -> dict[str, Any] | None:
        branch_id_l = _text(branch_id).lower()
        fallback = None
        for row in self._snapshot.get("users") or []:
            if not isinstance(row, dict):
                continue
            username = _first(row, "username", "user_id", "uid").lower()
            active_branch = _first(row, "active_branch", "branch_id").lower()
            branches = {
                value.lower()
                for value in _row_values(
                    row, "branches", "branch_scope", "branch_ids", "assigned_branch_ids"
                )
            }
            if username == branch_id_l:
                return row
            if active_branch == branch_id_l or branch_id_l in branches:
                fallback = fallback or row
        return fallback

    def _branches_for_selection(
        self, kind: str, scope_id: str, branches: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        scope_id_l = _text(scope_id).lower()
        if kind == "region":
            return [row for row in branches if _region_code(row).lower() == scope_id_l]
        if kind == "area":
            return [row for row in branches if _area_code(row).lower() == scope_id_l]
        if kind == "branch":
            return [row for row in branches if _branch_code(row).lower() == scope_id_l]
        return branches

    def _render_hierarchy(self) -> None:
        if not hasattr(self, "hierarchy_tree"):
            return
        regions, areas, branches = self._hierarchy_rows()
        needle = _text(self.hierarchy_search.text()).lower()
        self.hierarchy_tree.clear()
        for region_id in sorted(regions):
            region = regions[region_id]
            region_branches = [
                row
                for row in branches
                if _region_code(row).lower() == region_id.lower()
            ]
            area_ids = sorted(
                {_area_code(row) for row in region_branches if _area_code(row)}
                | {
                    area_id
                    for area_id, row in areas.items()
                    if _region_code(row).lower() == region_id.lower()
                }
            )
            region_text = f"{region_id}  {region.get('name') or ''}".strip()
            if (
                needle
                and needle not in region_text.lower()
                and (
                    not any(
                        (
                            needle
                            in " ".join((str(v or "") for v in row.values())).lower()
                            for row in region_branches
                        )
                    )
                )
            ):
                continue
            region_item = QTreeWidgetItem(
                [region_text, _("{count} branches").format(count=len(region_branches))]
            )
            region_item.setData(
                0, Qt.UserRole, {"kind": "region", "id": region_id, "row": region}
            )
            self.hierarchy_tree.addTopLevelItem(region_item)
            for area_id in area_ids:
                area = areas.get(area_id, {"area_id": area_id, "name": area_id})
                area_branches = [
                    row
                    for row in region_branches
                    if _area_code(row).lower() == area_id.lower()
                ]
                area_item = QTreeWidgetItem(
                    [
                        f"{area_id}  {area.get('name') or ''}".strip(),
                        _("{count} branches").format(count=len(area_branches)),
                    ]
                )
                area_item.setData(
                    0, Qt.UserRole, {"kind": "area", "id": area_id, "row": area}
                )
                region_item.addChild(area_item)
                for branch in sorted(area_branches, key=_branch_code):
                    manager = _branch_manager(branch) or _("No manager")
                    branch_item = QTreeWidgetItem([_branch_code(branch), manager])
                    branch_item.setData(
                        0,
                        Qt.UserRole,
                        {"kind": "branch", "id": _branch_code(branch), "row": branch},
                    )
                    area_item.addChild(branch_item)
            region_item.setExpanded(True)
        self.hierarchy_tree.resizeColumnToContents(0)
        if self.hierarchy_tree.topLevelItemCount() and (
            not self.hierarchy_tree.selectedItems()
        ):
            self.hierarchy_tree.setCurrentItem(self.hierarchy_tree.topLevelItem(0))
        self._render_hierarchy_detail()

    def _selected_hierarchy_payload(self) -> dict[str, Any]:
        items = (
            self.hierarchy_tree.selectedItems()
            if hasattr(self, "hierarchy_tree")
            else []
        )
        if not items:
            return {}
        data = items[0].data(0, Qt.UserRole)
        return dict(data) if isinstance(data, dict) else {}

    def _render_hierarchy_detail(self) -> None:
        if not hasattr(self, "hierarchy_branch_table"):
            return
        _regions, _areas, all_branches = self._hierarchy_rows()
        selected = self._selected_hierarchy_payload()
        kind = _text(selected.get("kind"), "all")
        scope_id = _text(selected.get("id"))
        row = selected.get("row") if isinstance(selected.get("row"), dict) else {}
        branches = self._branches_for_selection(kind, scope_id, all_branches)
        users = self._users_for_scope(kind, scope_id, branches)
        self._selected_hierarchy = {"kind": kind, "id": scope_id, "row": row}
        title = _("All administration")
        if scope_id:
            title = f"{_(kind.title())}: {scope_id}"
        self.hierarchy_title.setText(title)
        managers = sorted(
            {_branch_manager(branch) for branch in branches if _branch_manager(branch)}
        )
        self.hierarchy_meta.setText(
            _("Branches: {branches} | Users: {users} | Managers: {managers}").format(
                branches=len(branches),
                users=len(users),
                managers=", ".join(managers) if managers else _("No manager"),
            )
        )
        self.hierarchy_branch_table.setRowCount(0)
        for branch in branches:
            user = self._branch_user_row(_branch_code(branch)) or {}
            values = [
                _region_code(branch),
                _area_code(branch),
                _branch_code(branch),
                _branch_manager(branch) or "—",
                _first(user, "username", "user_id", "uid", default="—"),
                _(_server_role_key(user) or "—") if user else "—",
            ]
            r = self.hierarchy_branch_table.rowCount()
            self.hierarchy_branch_table.insertRow(r)
            for col, value in enumerate(values):
                item = _item(value)
                item.setData(Qt.UserRole, branch)
                self.hierarchy_branch_table.setItem(r, col, item)
        self.hierarchy_branch_table.resizeColumnsToContents()
        self.hierarchy_user_table.setRowCount(0)
        for user in users:
            values = [
                _first(user, "username", "user_id", "uid"),
                _(_server_role_key(user)),
                _first(user, "active_branch", "branch_id", default="—"),
                self._user_scope_text(user),
                (
                    _("Active")
                    if parse_bool(user.get("is_active"), True)
                    else _("Disabled")
                ),
            ]
            r = self.hierarchy_user_table.rowCount()
            self.hierarchy_user_table.insertRow(r)
            for col, value in enumerate(values):
                item = _item(value)
                item.setData(Qt.UserRole, user)
                self.hierarchy_user_table.setItem(r, col, item)
        self.hierarchy_user_table.resizeColumnsToContents()

    def _assign_selected_hierarchy_manager(self) -> None:
        selected = self._selected_hierarchy or self._selected_hierarchy_payload()
        kind = _text(selected.get("kind"))
        scope_id = _text(selected.get("id"))
        if kind not in {"region", "area", "branch"} or not scope_id:
            QMessageBox.information(
                self, _("Hierarchy"), _("Select a region, area, or branch first.")
            )
            return
        row = selected.get("row") if isinstance(selected.get("row"), dict) else {}
        current = (
            _branch_manager(row)
            if kind == "branch"
            else _first(row, f"{kind}_manager_id", "manager_username", "manager_id")
        )
        dialog = _AdminFormDialog(
            "Assign manager", [("manager", "Manager username", current)], self
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        manager = dialog.values().get("manager", "")
        self._run_worker(
            lambda: self.admin_service.structure.assign_manager(
                kind=kind, scope_id=scope_id, user_id=manager
            ),
            lambda _r: self.refresh_all_async(),
            busy_text="Assigning manager...",
            success_text="Manager assigned",
        )

    def _default_parent_for(self, kind: str) -> str:
        selected = self._selected_hierarchy or self._selected_hierarchy_payload()
        selected_kind = _text(selected.get("kind"))
        row = selected.get("row") if isinstance(selected.get("row"), dict) else {}
        if kind == "area":
            if selected_kind == "region":
                return _text(selected.get("id"))
            return _region_code(row)
        if kind == "branch":
            if selected_kind == "area":
                return _text(selected.get("id"))
            if selected_kind == "branch":
                return _area_code(row)
        return ""

    def _kind_from_structure_key(self) -> str:
        return {"regions": "region", "areas": "area", "branches": "branch"}.get(
            self._current_structure_key(), "region"
        )

    def _structure_key_from_kind(self, kind: str) -> str:
        return {"region": "regions", "area": "areas", "branch": "branches"}.get(
            kind, "regions"
        )

    def _open_structure_wizard(
        self, kind: str, row: dict[str, Any] | None = None, *, default_parent: str = ""
    ) -> None:
        kind = _text(kind, "region")
        dialog = _AdminStructureWizardDialog(
            kind,
            self._snapshot,
            existing=row,
            default_parent=default_parent,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        values = dialog.values()
        self._run_worker(
            lambda: self._save_structure_wizard(values),
            lambda _r: self.refresh_all_async(),
            busy_text="Saving hierarchy...",
            success_text="Hierarchy saved",
        )

    def _save_structure_wizard(self, values: dict[str, Any]) -> dict[str, Any]:
        kind = _text(values.get("kind"))
        code = _text(values.get("code"))
        name = _text(values.get("name"), code)
        parent = _text(values.get("parent"))
        manager = _text(values.get("manager"))
        if not code:
            raise ValueError("Code is required.")
        result: dict[str, Any] = {"kind": kind, "code": code}
        if kind == "region":
            result["scope"] = self.admin_service.structure.upsert_region(code, name)
            if manager:
                result["manager"] = self.admin_service.structure.assign_region_manager(
                    code, manager
                )
            return result
        if kind == "area":
            if not parent:
                raise ValueError("Parent region is required.")
            result["scope"] = self.admin_service.structure.upsert_area(
                code, name, region_id=parent
            )
            if manager:
                result["manager"] = self.admin_service.structure.assign_area_manager(
                    code, manager
                )
            bulk_rows = list(values.get("bulk_branches") or [])
            if bulk_rows:
                result["branches"] = self.admin_service.structure.bulk_upsert_branches(
                    code, bulk_rows
                )
            return result
        if kind == "branch":
            if not parent:
                raise ValueError("Parent area is required.")
            result["scope"] = self.admin_service.structure.upsert_branch(
                code, parent, name, manager_username=manager
            )
            if manager:
                result["manager"] = self.admin_service.structure.assign_branch_manager(
                    code, manager
                )
            return result
        raise ValueError("Unsupported structure type.")

    def _edit_selected_hierarchy_scope(self) -> None:
        selected = self._selected_hierarchy or self._selected_hierarchy_payload()
        kind = _text(selected.get("kind"))
        row = selected.get("row") if isinstance(selected.get("row"), dict) else {}
        if kind == "region":
            self.structure_type.setCurrentIndex(self.structure_type.findData("regions"))
        elif kind == "area":
            self.structure_type.setCurrentIndex(self.structure_type.findData("areas"))
        elif kind == "branch":
            self.structure_type.setCurrentIndex(
                self.structure_type.findData("branches")
            )
        else:
            QMessageBox.information(self, _("Hierarchy"), _("Select a scope first."))
            return
        self._show_route("structure")
        self._open_structure_wizard(kind, row)


from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
)
from runtime.presentation.views.admin_support import _AdminMetricCard



class AdminPagesMixin:

    def _build_overview_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.metric_regions = _AdminMetricCard(
            _("Regions"), "0", _("Operational regions returned by the server.")
        )
        self.metric_areas = _AdminMetricCard(
            _("Areas"), "0", _("Areas linked to regions.")
        )
        self.metric_branches = _AdminMetricCard(
            _("Branches"), "0", _("Restaurant branches in scope.")
        )
        self.metric_users = _AdminMetricCard(
            _("Users"), "0", _("Visible users in your server-controlled scope.")
        )
        metric_cards = (
            self.metric_regions,
            self.metric_areas,
            self.metric_branches,
            self.metric_users,
        )
        for idx, card in enumerate(metric_cards):
            grid.addWidget(card, idx // 2, idx % 2)
        root.addLayout(grid)
        panel, lay = self._panel(
            _("Server status"),
            _("This summary is read from the server administration snapshot."),
        )
        self.server_notes = QLabel("")
        self.server_notes.setObjectName("AdminHintText")
        self.server_notes.setWordWrap(True)
        lay.addWidget(self.server_notes)
        lay.addStretch(1)
        root.addWidget(panel, 1)
        return page

    def _table(self, columns: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setObjectName("AdminTable")
        table.setHorizontalHeaderLabels([_(c) for c in columns])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return table

    def _build_users_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        panel, lay = self._panel(
            _("Users"),
            _("Create, review, and maintain user access using the server API."),
        )
        toolbar = QHBoxLayout()
        self.user_search = QLineEdit()
        self.user_search.setObjectName("AdminSearchInput")
        self.user_search.setPlaceholderText(_("Search users, roles, or scope..."))
        self.user_search.textChanged.connect(self._render_users)
        self.user_role_filter = QComboBox()
        self.user_role_filter.setObjectName("AdminFilterCombo")
        self.user_role_filter.addItem(_("All roles"), "")
        self.user_role_filter.currentIndexChanged.connect(self._render_users)
        toolbar.addWidget(self.user_search, 1)
        toolbar.addWidget(self.user_role_filter)
        lay.addLayout(toolbar)
        self.users_table = self._table([_("User"), _("Role"), _("Scope"), _("Status")])
        lay.addWidget(self.users_table, 1)
        buttons = QHBoxLayout()
        self.add_user_button = QPushButton(_("New user"))
        self.edit_user_button = QPushButton(_("Edit user"))
        self.reset_password_button = QPushButton(_("Reset password"))
        self.delete_user_button = QPushButton(_("Delete user"))
        for btn in (
            self.add_user_button,
            self.edit_user_button,
            self.reset_password_button,
        ):
            btn.setObjectName("AdminActionButton")
        self.delete_user_button.setObjectName("AdminDangerButton")
        self.add_user_button.clicked.connect(lambda: self._open_user_editor(None))
        self.edit_user_button.clicked.connect(self._edit_selected_user)
        self.reset_password_button.clicked.connect(self._reset_selected_password)
        self.delete_user_button.clicked.connect(self._delete_selected_user)
        buttons.addWidget(self.add_user_button)
        buttons.addStretch(1)
        buttons.addWidget(self.edit_user_button)
        buttons.addWidget(self.reset_password_button)
        buttons.addWidget(self.delete_user_button)
        lay.addLayout(buttons)
        root.addWidget(panel, 1)
        return page

    def _build_structure_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        panel, lay = self._panel(
            _("Structure"),
            _(
                "Maintain regions, areas, and branches through server-side administration APIs."
            ),
        )
        self.structure_type = QComboBox()
        self.structure_type.setObjectName("AdminFilterCombo")
        self.structure_type.addItem(_("Regions"), "regions")
        self.structure_type.addItem(_("Areas"), "areas")
        self.structure_type.addItem(_("Branches"), "branches")
        self.structure_type.currentIndexChanged.connect(self._render_structure)
        lay.addWidget(self.structure_type)
        self.structure_table = self._table(
            [_("Code"), _("Name"), _("Parent"), _("Manager")]
        )
        lay.addWidget(self.structure_table, 1)
        buttons = QHBoxLayout()
        self.add_structure_button = QPushButton(_("New"))
        self.add_region_button = QPushButton(_("New region"))
        self.add_area_button = QPushButton(_("New area"))
        self.add_branch_button = QPushButton(_("New branch"))
        self.edit_structure_button = QPushButton(_("Edit"))
        self.delete_structure_button = QPushButton(_("Delete"))
        for button in (
            self.add_structure_button,
            self.add_region_button,
            self.add_area_button,
            self.add_branch_button,
            self.edit_structure_button,
        ):
            button.setObjectName("AdminActionButton")
        self.delete_structure_button.setObjectName("AdminDangerButton")
        self.add_structure_button.clicked.connect(
            lambda: self._open_structure_wizard(self._kind_from_structure_key())
        )
        self.add_region_button.clicked.connect(
            lambda: self._open_structure_wizard("region")
        )
        self.add_area_button.clicked.connect(
            lambda: self._open_structure_wizard(
                "area", default_parent=self._default_parent_for("area")
            )
        )
        self.add_branch_button.clicked.connect(
            lambda: self._open_structure_wizard(
                "branch", default_parent=self._default_parent_for("branch")
            )
        )
        self.edit_structure_button.clicked.connect(self._edit_selected_structure)
        self.delete_structure_button.clicked.connect(self._delete_selected_structure)
        buttons.addWidget(self.add_structure_button)
        buttons.addWidget(self.add_region_button)
        buttons.addWidget(self.add_area_button)
        buttons.addWidget(self.add_branch_button)
        buttons.addWidget(self.edit_structure_button)
        buttons.addStretch(1)
        buttons.addWidget(self.delete_structure_button)
        lay.addLayout(buttons)
        root.addWidget(panel, 1)
        return page

    def _build_permissions_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        panel, lay = self._panel(
            _("Permissions"),
            _("Review and update role permission templates from the server."),
        )
        self.permission_role = QComboBox()
        self.permission_role.setObjectName("AdminFilterCombo")
        self.permission_role.currentIndexChanged.connect(self._render_permissions)
        lay.addWidget(self.permission_role)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.permission_layout = QVBoxLayout(body)
        self.permission_layout.setContentsMargins(0, 0, 0, 0)
        self.permission_layout.setSpacing(8)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        self.save_permissions_button = QPushButton(_("Save permissions"))
        self.save_permissions_button.setObjectName("AdminActionButton")
        self.save_permissions_button.clicked.connect(self._save_permissions)
        buttons.addStretch(1)
        buttons.addWidget(self.save_permissions_button)
        lay.addLayout(buttons)
        root.addWidget(panel, 1)
        return page


from contextlib import suppress
from PyQt5.QtWidgets import QCheckBox
from runtime.domain.access import normalize_role
from runtime.shared.errors import UI_OPERATION_EXCEPTIONS
from runtime.shared.settings.messages import user_error_message
from runtime.bootstrap.qt.workers import WorkerRegistry
from runtime.presentation.views.admin_support import _AdminPasswordDialog, _list_values, _role_key



class AdminStateMixin:

    def _show_route(self, route: str) -> None:
        self._current_route = route
        for key, btn in self.nav_buttons.items():
            btn.setChecked(key == route)
        page = self.pages.get(route)
        if page is not None:
            self.stack.setCurrentWidget(page)

    def _set_admin_mutation_buttons_busy(self, busy: bool) -> None:
        for name in (
            "new_region_button",
            "new_area_button",
            "new_branch_button",
            "hierarchy_assign_manager_button",
            "hierarchy_edit_button",
            "add_structure_button",
            "add_region_button",
            "add_area_button",
            "add_branch_button",
            "edit_structure_button",
            "delete_structure_button",
            "add_user_button",
            "edit_user_button",
            "reset_password_button",
            "delete_user_button",
            "save_permissions_button",
        ):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(not bool(busy))

    def _run_worker(
        self, fn, on_result, *, busy_text: str = "", success_text: str = ""
    ) -> None:
        operation_key = (
            "admin:"
            + str(busy_text or getattr(fn, "__name__", "admin_operation")).strip()
        )
        registry = getattr(self, "_worker_registry", None)
        if registry is None:
            registry = WorkerRegistry(self._pool)
            self._worker_registry = registry
        if registry.has_active_key(operation_key):
            self.status_label.setText(_("Operation already running…"))
            return
        if busy_text:
            self.status_label.setText(_(busy_text))
        self.refresh_button.setEnabled(False)
        self._set_admin_mutation_buttons_busy(True)

        def _cleanup():
            self.refresh_button.setEnabled(True)
            if self._snapshot:
                self._apply_server_authorization()
            else:
                self._set_admin_mutation_buttons_busy(False)

        worker = registry.start(
            fn,
            on_result=lambda result: self._handle_worker_result(
                result, on_result, success_text
            ),
            on_error=self._handle_worker_error,
            on_finished=_cleanup,
            operation_key=operation_key,
            scope_checker=lambda: not bool(getattr(self, "_closed", False)),
        )
        if worker is None:
            self.refresh_button.setEnabled(True)
            if self._snapshot:
                self._apply_server_authorization()
            else:
                self._set_admin_mutation_buttons_busy(False)
            self.status_label.setText(_("Operation already running…"))

    def _handle_worker_result(self, result: Any, on_result, success_text: str) -> None:
        try:
            on_result(result)
            self.status_label.setText(_(success_text or "Server: connected"))
        except UI_OPERATION_EXCEPTIONS as exc:
            self._handle_worker_error(str(exc))

    def _handle_worker_error(self, error: str) -> None:
        message = user_error_message(error)
        self.status_label.setText(_("Server error"))
        self.status_label.setToolTip(message)
        logger.warning("Admin operation failed: %s", message)

    def refresh_all_async(
        self,
        busy_text: str = "Refreshing administration...",
        success_text: str = "Administration synchronized",
    ) -> None:
        self._run_worker(
            self.admin_service.fetch_dashboard_snapshot,
            self._apply_snapshot,
            busy_text=busy_text,
            success_text=success_text,
        )

    def _apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = dict(snapshot or {})
        self._render_all()

    def _snapshot_capabilities(self) -> set[str]:
        return {
            str(item or "").strip()
            for item in self._snapshot.get("capabilities") or []
            if str(item or "").strip()
        }

    def _server_allows(self, *capabilities: str) -> bool:
        if self._snapshot.get("read_only"):
            return False
        available = self._snapshot_capabilities()
        if "*" in available:
            return True
        return any((str(cap or "").strip() in available for cap in capabilities))

    def _set_button_authorization(
        self, button: QPushButton, allowed: bool, reason: str = ""
    ) -> None:
        button.setEnabled(bool(allowed))
        if reason:
            button.setToolTip(_(reason))
        else:
            button.setToolTip("")

    def _sync_permission_roles_from_snapshot(self) -> None:
        roles = _list_values(self._snapshot.get("allowed_role_keys"))
        current = normalize_role(self.permission_role.currentData() or "")
        with suppress(UI_OPERATION_EXCEPTIONS):
            self.permission_role.blockSignals(True)
            self.permission_role.clear()
            for role in roles:
                normalized = normalize_role(role)
                if normalized:
                    self.permission_role.addItem(_(normalized), normalized)
            index = self.permission_role.findData(current) if current else -1
            if index >= 0:
                self.permission_role.setCurrentIndex(index)
        with suppress(UI_OPERATION_EXCEPTIONS):
            self.permission_role.blockSignals(False)

    def _sync_user_role_filter_from_snapshot(self) -> None:
        roles = _list_values(self._snapshot.get("allowed_role_keys"))
        if not roles:
            roles = sorted(
                {
                    normalize_role(row.get("role"))
                    for row in self._snapshot.get("users") or []
                    if isinstance(row, dict) and normalize_role(row.get("role"))
                }
            )
        current = _text(self.user_role_filter.currentData() or "")
        with suppress(UI_OPERATION_EXCEPTIONS):
            self.user_role_filter.blockSignals(True)
            self.user_role_filter.clear()
            self.user_role_filter.addItem(_("All roles"), "")
            for role in roles:
                normalized = normalize_role(role)
                if normalized:
                    self.user_role_filter.addItem(_(normalized), normalized)
            index = self.user_role_filter.findData(current) if current else 0
            self.user_role_filter.setCurrentIndex(index if index >= 0 else 0)
        with suppress(UI_OPERATION_EXCEPTIONS):
            self.user_role_filter.blockSignals(False)

    def _apply_server_authorization(self) -> None:
        reason = "This action is disabled by the server permission contract."
        structure_write = self._server_allows("structure.write")
        self._set_button_authorization(
            self.new_region_button,
            self._server_allows("structure.create.region", "structure.write"),
            reason,
        )
        self._set_button_authorization(
            self.new_area_button,
            self._server_allows("structure.create.area", "structure.write"),
            reason,
        )
        self._set_button_authorization(
            self.new_branch_button,
            self._server_allows("structure.create.branch", "structure.write"),
            reason,
        )
        self._set_button_authorization(
            self.hierarchy_assign_manager_button, structure_write, reason
        )
        self._set_button_authorization(
            self.hierarchy_edit_button, structure_write, reason
        )
        self._set_button_authorization(
            self.add_structure_button, structure_write, reason
        )
        self._set_button_authorization(
            self.add_region_button,
            self._server_allows("structure.create.region", "structure.write"),
            reason,
        )
        self._set_button_authorization(
            self.add_area_button,
            self._server_allows("structure.create.area", "structure.write"),
            reason,
        )
        self._set_button_authorization(
            self.add_branch_button,
            self._server_allows("structure.create.branch", "structure.write"),
            reason,
        )
        self._set_button_authorization(
            self.edit_structure_button, structure_write, reason
        )
        self._set_button_authorization(
            self.delete_structure_button,
            self._server_allows("structure.delete"),
            reason,
        )
        self._set_button_authorization(
            self.add_user_button,
            self._server_allows("users.create", "users.write"),
            reason,
        )
        self._set_button_authorization(
            self.edit_user_button,
            self._server_allows("users.create", "users.write"),
            reason,
        )
        self._set_button_authorization(
            self.reset_password_button,
            self._server_allows("users.reset_password"),
            reason,
        )
        self._set_button_authorization(
            self.delete_user_button, self._server_allows("users.delete"), reason
        )
        self._set_button_authorization(
            self.save_permissions_button,
            self._server_allows("permissions.edit"),
            reason,
        )

    def _render_all(self) -> None:
        self.metric_regions.set_value(len(self._snapshot.get("regions") or []))
        self.metric_areas.set_value(len(self._snapshot.get("areas") or []))
        self.metric_branches.set_value(len(self._snapshot.get("branches") or []))
        self.metric_users.set_value(len(self._snapshot.get("users") or []))
        notes = []
        if self._snapshot.get("read_only"):
            notes.append(
                _("Read-only mode: {reason}").format(
                    reason=_text(self._snapshot.get("read_only_reason"), "—")
                )
            )
        warnings = self._snapshot.get("server_contract_warnings") or []
        notes.extend((str(item) for item in warnings if str(item).strip()))
        if not notes:
            notes.append(_("Server administration contract is available."))
        self.server_notes.setText("\n".join(notes))
        self._sync_user_role_filter_from_snapshot()
        self._sync_permission_roles_from_snapshot()
        self._apply_server_authorization()
        self._render_hierarchy()
        self._render_users()
        self._render_structure()
        self._render_permissions()

    def _render_users(self) -> None:
        rows = list(self._snapshot.get("users") or [])
        needle = (
            _text(self.user_search.text()).lower()
            if hasattr(self, "user_search")
            else ""
        )
        role_filter = (
            _text(self.user_role_filter.currentData())
            if hasattr(self, "user_role_filter")
            else ""
        )
        filtered = []
        for row in rows:
            haystack = " ".join((str(v or "") for v in row.values())).lower()
            role = _role_key(row)
            if needle and needle not in haystack:
                continue
            if role_filter and role != role_filter:
                continue
            filtered.append(row)
        self.users_table.setRowCount(0)
        for row in filtered:
            r = self.users_table.rowCount()
            self.users_table.insertRow(r)
            username = _first(row, "username", "user_id", "uid", default="—")
            role = _role_key(row)
            scope = self._user_scope_text(row)
            active = row.get("is_active", True)
            status = _("Active") if bool(active) else _("Disabled")
            values = [username, _(_server_role_key(row) or role or "—"), scope, status]
            for col, value in enumerate(values):
                item = _item(value)
                item.setData(Qt.UserRole, row)
                self.users_table.setItem(r, col, item)
        self.users_table.resizeColumnsToContents()

    @staticmethod
    def _user_scope_text(row: dict[str, Any]) -> str:
        for key in (
            "active_branch",
            "branch_scope",
            "area_scope",
            "region_scope",
            "assigned_branch_ids",
            "branches",
            "areas",
            "regions",
        ):
            value = row.get(key)
            if isinstance(value, (list, tuple, set)):
                return (
                    ", ".join((str(item) for item in value if str(item).strip())) or "—"
                )
            if value:
                return str(value)
        scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
        if scope:
            return ", ".join((f"{k}:{v}" for k, v in scope.items() if v)) or "—"
        return "—"

    def _selected_table_row(self, table: QTableWidget) -> dict[str, Any] | None:
        items = table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        first = table.item(row, 0)
        data = first.data(Qt.UserRole) if first is not None else None
        return dict(data) if isinstance(data, dict) else None

    def _selected_username(self) -> str:
        row = self._selected_table_row(self.users_table) or {}
        return _first(row, "username", "user_id", "uid")

    def _open_user_editor(self, row: dict[str, Any] | None) -> None:
        existing = dict(row or {})
        fields = [
            ("username", "Username", _first(existing, "username", "user_id")),
            (
                "display_name",
                "Display name",
                _first(existing, "display_name", "name", "full_name"),
            ),
            ("role", "Role", _server_role_key(existing) or "branch_user"),
            (
                "active_branch",
                "Active branch",
                _first(existing, "active_branch", "branch_id"),
            ),
            (
                "branch_scope",
                "Branch scope",
                self._user_scope_text(existing) if existing else "",
            ),
            ("temporary_password", "Temporary password", ""),
        ]
        dialog = _AdminFormDialog("User account", fields, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        payload = dialog.values()
        temporary_password = payload.pop("temporary_password", "")
        if temporary_password:
            payload["password"] = temporary_password
        elif existing:
            payload.pop("password", None)
        if payload.get("branch_scope") and (not payload.get("active_branch")):
            payload["active_branch"] = (
                payload.get("branch_scope", "").split(",", 1)[0].strip()
            )
        self._run_worker(
            lambda: self.admin_service.users.upsert_user(payload),
            lambda _r: self.refresh_all_async(),
            busy_text="Saving user...",
            success_text="User saved",
        )

    def _edit_selected_user(self) -> None:
        row = self._selected_table_row(self.users_table)
        if not row:
            QMessageBox.information(self, _("Users"), _("Select a user first."))
            return
        self._open_user_editor(row)

    def _reset_selected_password(self) -> None:
        username = self._selected_username()
        if not username:
            QMessageBox.information(self, _("Users"), _("Select a user first."))
            return
        dialog = _AdminPasswordDialog(username, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        password = dialog.value()
        self._run_worker(
            lambda: self.admin_service.users.reset_password(username, password),
            lambda _r: self.refresh_all_async(),
            busy_text="Resetting password...",
            success_text="Password reset",
        )

    def _delete_selected_user(self) -> None:
        username = self._selected_username()
        if not username:
            QMessageBox.information(self, _("Users"), _("Select a user first."))
            return
        if (
            QMessageBox.question(
                self,
                _("Delete user"),
                _("Delete user {username}?").format(username=username),
            )
            != QMessageBox.Yes
        ):
            return
        self._run_worker(
            lambda: self.admin_service.users.delete_user(username),
            lambda _r: self.refresh_all_async(),
            busy_text="Deleting user...",
            success_text="User deleted",
        )

    def _current_structure_key(self) -> str:
        return _text(self.structure_type.currentData()) or "regions"

    def _render_structure(self) -> None:
        key = self._current_structure_key()
        rows = list(self._snapshot.get(key) or [])
        self.structure_table.setRowCount(0)
        for row in rows:
            r = self.structure_table.rowCount()
            self.structure_table.insertRow(r)
            if key == "regions":
                values = [
                    _first(row, "region_id", "id"),
                    _first(row, "name"),
                    "—",
                    _first(row, "region_manager_id", "manager", "manager_username"),
                ]
            elif key == "areas":
                values = [
                    _first(row, "area_id", "id"),
                    _first(row, "name"),
                    _first(row, "region_id"),
                    _first(row, "area_manager_id", "manager", "manager_username"),
                ]
            else:
                values = [
                    _first(row, "branch_id", "id"),
                    _first(row, "name"),
                    _first(row, "area_id"),
                    _branch_manager(row),
                ]
            for col, value in enumerate(values):
                item = _item(value)
                item.setData(Qt.UserRole, row)
                self.structure_table.setItem(r, col, item)
        self.structure_table.resizeColumnsToContents()

    def _open_structure_editor(self, row: dict[str, Any] | None) -> None:
        self._open_structure_wizard(self._kind_from_structure_key(), row)

    def _edit_selected_structure(self) -> None:
        row = self._selected_table_row(self.structure_table)
        if not row:
            QMessageBox.information(self, _("Structure"), _("Select a row first."))
            return
        self._open_structure_editor(row)

    def _delete_selected_structure(self) -> None:
        key = self._current_structure_key()
        row = self._selected_table_row(self.structure_table)
        if not row:
            QMessageBox.information(self, _("Structure"), _("Select a row first."))
            return
        code = _first(row, "region_id", "area_id", "branch_id", "id")
        if not code:
            return
        if (
            QMessageBox.question(
                self, _("Delete"), _("Delete {code}?").format(code=code)
            )
            != QMessageBox.Yes
        ):
            return

        def _work():
            if key == "regions":
                return self.admin_service.structure.delete_region(code)
            if key == "areas":
                return self.admin_service.structure.delete_area(code)
            return self.admin_service.structure.delete_branch(code)

        self._run_worker(
            _work,
            lambda _r: self.refresh_all_async(),
            busy_text="Deleting structure...",
            success_text="Structure deleted",
        )

    def _clear_permissions(self) -> None:
        while self.permission_layout.count():
            item = self.permission_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _permission_rows_for_role(self, role: str) -> list[tuple[str, bool, str]]:
        templates = self._snapshot.get("permission_templates") or {}
        catalog = self._snapshot.get("permission_catalog") or []
        template = templates.get(role) if isinstance(templates, dict) else None
        if isinstance(template, dict):
            selected = set(_list_values(template.get("permissions")))
        else:
            selected = set(_list_values(template))
        rows: list[tuple[str, bool, str]] = []
        if isinstance(catalog, list) and catalog:
            for entry in catalog:
                if isinstance(entry, dict):
                    code = _text(entry.get("code") or entry.get("permission"))
                    hint = _text(entry.get("description") or entry.get("label") or code)
                else:
                    code = _text(entry)
                    hint = code
                if code:
                    rows.append((code, code in selected, hint))
        else:
            for code in sorted(selected):
                rows.append((code, True, code))
        return rows

    def _render_permissions(self) -> None:
        self._clear_permissions()
        role = normalize_role(self.permission_role.currentData() or "store_user")
        self._permission_checks: list[tuple[str, QCheckBox]] = []
        rows = self._permission_rows_for_role(role)
        if not rows:
            empty = QLabel(_("No permission catalog was returned by the server."))
            empty.setObjectName("AdminHintText")
            empty.setWordWrap(True)
            self.permission_layout.addWidget(empty)
            return
        for code, checked, hint in rows:
            card = QFrame()
            card.setObjectName("AdminPermissionCard")
            lay = QHBoxLayout(card)
            lay.setContentsMargins(12, 10, 12, 10)
            chk = QCheckBox()
            chk.setChecked(bool(checked))
            label = QLabel(f"{code}\n{hint}")
            label.setObjectName("AdminPermissionText")
            label.setWordWrap(True)
            lay.addWidget(chk)
            lay.addWidget(label, 1)
            self.permission_layout.addWidget(card)
            self._permission_checks.append((code, chk))
        self.permission_layout.addStretch(1)

    def _save_permissions(self) -> None:
        role = normalize_role(self.permission_role.currentData() or "store_user")
        permissions = [
            code
            for code, chk in getattr(self, "_permission_checks", [])
            if chk.isChecked()
        ]
        self._run_worker(
            lambda: self.admin_service.permissions.set_role_permissions(
                role, permissions
            ),
            lambda _r: self.refresh_all_async(),
            busy_text="Saving permissions...",
            success_text="Permissions saved",
        )

    def closeEvent(self, event) -> None:
        self._closed = True
        registry = getattr(self, "_worker_registry", None)
        if registry is not None:
            with suppress(UI_OPERATION_EXCEPTIONS):
                close = getattr(registry, "close", None)
                if callable(close):
                    close()
                else:
                    registry.cancel_all()
        super().closeEvent(event)


# --- package exports ---
__all__ = ["AdminHierarchyMixin", "AdminPagesMixin", "AdminStateMixin"]
