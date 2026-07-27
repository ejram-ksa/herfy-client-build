from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

import logging
from runtime.shared.numbers import parse_plain_number
from runtime.shared.booleans import parse_bool
from runtime.shared.strings import best_product_name, looks_like_material_code

logger = logging.getLogger(__name__)


def _looks_like_material_code(value: object, material: str = "") -> bool:
    return looks_like_material_code(value, material)


def _best_product_name(material: str, *candidates: object) -> str:
    return best_product_name(material, *candidates)


def _normalize_material_key(value: object) -> str:
    text = str(value or "").strip()
    return text.replace(" ", "").replace("-", "").upper()


def _first_text(mapping: dict | None, *keys: str) -> str:
    row = mapping if isinstance(mapping, dict) else {}
    for key in keys:
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return ""


def _catalog_material(row: dict | None) -> str:
    return _first_text(
        row,
        "material",
        "material_number",
        "materialNumber",
        "material_code",
        "materialCode",
        "code",
        "item_code",
        "itemCode",
        "matnr",
    )


def _catalog_name(row: dict | None, material: str = "") -> str:
    return _best_product_name(
        material,
        _first_text(
            row,
            "name",
            "product_name",
            "productName",
            "material_name",
            "materialName",
            "description",
            "product_description",
            "productDescription",
            "display_name",
            "displayName",
            "item_name",
            "itemName",
        ),
    )


import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from runtime.shared.settings.config import _, resource_path
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS



@dataclass(frozen=True)
class UsageWorkspaceDecision:
    allowed: bool
    message: str = ""


@dataclass(frozen=True)
class UsageFilePresentation:
    display_name: str
    tooltip: str


class UsageWorkspaceService:

    def format_selected_file(self, path: str) -> UsageFilePresentation:
        clean_path = str(path or "").strip()
        if not clean_path:
            return UsageFilePresentation(display_name=_("No file selected"), tooltip="")
        return UsageFilePresentation(
            display_name=os.path.basename(clean_path), tooltip=clean_path
        )

    def auto_compute_ready(self, receipts_path: str, beginning_path: str) -> bool:
        return bool(
            str(receipts_path or "").strip() and str(beginning_path or "").strip()
        )

    def evaluate_compute_request(
        self,
        *,
        access_allowed: bool,
        access_reason: str,
        usage_service: Any,
        receipts_path: str,
        beginning_path: str,
    ) -> UsageWorkspaceDecision:
        if not access_allowed:
            return UsageWorkspaceDecision(
                False,
                access_reason or _("Usage is not available for the current account."),
            )
        if usage_service is None:
            return UsageWorkspaceDecision(False, _("Usage service is unavailable."))
        receipts_path = str(receipts_path or "").strip()
        beginning_path = str(beginning_path or "").strip()
        if not (
            receipts_path
            and beginning_path
            and os.path.exists(receipts_path)
            and os.path.exists(beginning_path)
        ):
            return UsageWorkspaceDecision(False, _("Select both input files first."))
        return UsageWorkspaceDecision(True, "")

    def build_result_status(
        self, rows: Sequence[dict] | None, usage_service: Any
    ) -> str:
        rows = list(rows or [])
        if rows:
            return _("Done ({count} rows)").format(count=len(rows))
        info = (
            getattr(usage_service, "last_compute_info", {})
            if usage_service is not None
            else {}
        )
        status = str(info.get("status") or "")
        if status == "empty_catalog":
            return _(
                "Consumption item catalog is empty. Add shared food-service items first."
            )
        if status == "no_catalog_matches":
            return _(
                "Imported files were read, but no food items matched the shared daily consumption catalog."
            )
        if status == "empty_import":
            return _("Imported files contain no usable rows.")
        return _("No rows matched.")

    @staticmethod
    def hide_total_zero_enabled(db_manager: Any) -> bool:
        if db_manager is None:
            return False
        try:
            return parse_bool(
                db_manager.get_setting("usage_hide_total_zero", "False"),
                False,
            )
        except SERVICE_OPERATION_EXCEPTIONS:
            return False

    @staticmethod
    def set_hide_total_zero_enabled(db_manager: Any, enabled: bool) -> None:
        if db_manager is None:
            return
        try:
            db_manager.set_setting(
                "usage_hide_total_zero", "True" if enabled else "False"
            )
        except SERVICE_OPERATION_EXCEPTIONS:
            return

    def evaluate_preview_request(
        self, *, access_allowed: bool, access_reason: str, row_count: int
    ) -> UsageWorkspaceDecision:
        if not access_allowed:
            return UsageWorkspaceDecision(
                False,
                access_reason or _("Usage is not available for the current account."),
            )
        if int(row_count or 0) <= 0:
            return UsageWorkspaceDecision(False, _("No usage rows to preview."))
        return UsageWorkspaceDecision(True, "")

    def build_print_context(
        self,
        *,
        usage_print_service,
        model,
        headers: Sequence[str],
        numeric_columns: Iterable[int],
        column_ratios: Sequence[int],
        db_manager=None,
    ):
        profile = (
            getattr(getattr(db_manager, "app_state", None), "current_user", None)
            if db_manager is not None
            else None
        )
        active_branch = ""
        if db_manager is not None:
            try:
                active_branch = str(db_manager.get_active_branch() or "").strip()
            except SERVICE_OPERATION_EXCEPTIONS:
                active_branch = ""
        if not active_branch and profile is not None:
            active_branch = str(getattr(profile, "active_branch", "") or "").strip()
        if not active_branch:
            branches = (
                list(getattr(profile, "branches", []) or [])
                if profile is not None
                else []
            )
            active_branch = (
                str(branches[0]).strip()
                if len(branches) == 1
                else _("All restaurant branches")
            )
        return usage_print_service.build_context(
            model=model,
            headers=headers,
            numeric_columns=numeric_columns,
            column_ratios=column_ratios,
            title=_("Herfy Monthly Usage"),
            branch_text=active_branch or _("All stores"),
            logo_path=resource_path("resources", "images", "logo.png"),
        )


from runtime.application.services.import_excel import parse_begining, parse_receipts_uom_from_colD



class UsageService:

    def __init__(self, db: Any):
        self.db = db
        self.last_compute_info: dict = {}

    def load_catalog_products(self) -> list[dict]:
        refresh = getattr(self.db, "refresh_usage_products_from_server", None)
        if callable(refresh):
            try:
                server_rows = list(refresh(force_refresh=True) or [])
                if server_rows:
                    return server_rows
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug("Usage catalog server hydration failed", exc_info=True)
        return list(self.db.fetch_usage_products() or [])

    def _catalog_index(self, products: list[dict]) -> tuple[set[str], dict[str, dict]]:
        product_map: dict[str, dict] = {}
        canonical_codes: set[str] = set()
        for product in products or []:
            if not isinstance(product, dict):
                continue
            material = _catalog_material(product)
            if not material:
                continue
            normalized = _normalize_material_key(material)
            if not normalized:
                continue
            name = _catalog_name(product, material)
            merged = dict(product)
            merged["material"] = material
            merged["name"] = _best_product_name(material, name, product.get("name"))
            product_map[material] = merged
            product_map[normalized] = merged
            canonical_codes.add(material)
        return (canonical_codes, product_map)

    def _parse_input_sources(
        self, receipts_path: str, begin_path: str, progress
    ) -> tuple[dict, dict, dict]:
        progress("Parsing receipts…")
        receipts, uom_map = parse_receipts_uom_from_colD(receipts_path)
        progress("Parsing beginning/count file…")
        begining = parse_begining(begin_path)
        progress("Updating local UOM cache…")
        self.db.update_usage_uom_bulk(uom_map)
        return (receipts, begining, uom_map)

    def _build_row(
        self,
        *,
        code: str,
        product_map: dict[str, dict],
        receipt_row: dict | None,
        beginning_row: dict | None,
    ) -> dict:
        receipts_value = (
            parse_plain_number(receipt_row.get("receipts")) if receipt_row else 0.0
        )
        beginning_value = (
            parse_plain_number(beginning_row.get("qty")) if beginning_row else 0.0
        )
        total_value = receipts_value + beginning_value
        product_row = (
            product_map.get(code)
            or product_map.get(_normalize_material_key(code))
            or {}
        )
        name = _best_product_name(
            code,
            product_row.get("name"),
            receipt_row.get("name") if receipt_row else "",
            beginning_row.get("name") if beginning_row else "",
        )
        uom = (
            (receipt_row.get("uom") if receipt_row else "")
            or product_row.get("uom")
            or ""
        ).strip()
        return {
            "material": code,
            "name": name,
            "uom": uom,
            "receipts": receipts_value,
            "begin": beginning_value,
            "total": total_value,
            "onhand": 0.0,
            "usage": 0.0,
            "user_set": False,
        }

    def compute_rows(
        self, receipts_path: str, begin_path: str, progress_callback=None
    ) -> list[dict]:
        progress = progress_callback or (lambda *_args, **_kwargs: None)
        receipts, begining, _uom_map = self._parse_input_sources(
            receipts_path, begin_path, progress
        )
        prods = self.load_catalog_products()
        codes, product_map = self._catalog_index(prods)
        rows: list[dict] = []
        imported_codes = set(receipts.keys()) | set(begining.keys())
        if not codes:
            self.last_compute_info = {
                "status": "empty_catalog",
                "catalog_count": 0,
                "imported_count": len(imported_codes),
                "matched_count": 0,
            }
            return []
        progress("Computing usage rows…")
        for code in sorted(codes):
            receipt_row = receipts.get(code)
            beginning_row = begining.get(code)
            if not receipt_row and (not beginning_row):
                continue
            rows.append(
                self._build_row(
                    code=code,
                    product_map=product_map,
                    receipt_row=receipt_row,
                    beginning_row=beginning_row,
                )
            )
        status = "ok"
        if imported_codes and (not rows):
            status = "no_catalog_matches"
        elif not imported_codes:
            status = "empty_import"
        self.last_compute_info = {
            "status": status,
            "catalog_count": len(codes),
            "imported_count": len(imported_codes),
            "matched_count": len(rows),
        }
        progress("Done")
        return rows
