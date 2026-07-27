from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

from typing import Any
from runtime.shared.booleans import parse_bool
from runtime.shared.objects import normalize_int, safe_get
from runtime.shared.strings import normalize_text


def normalize_alert(item: Any) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    return {
        "id": normalize_int(safe_get(data, "id")),
        "branch_id": normalize_text(safe_get(data, "branch_id")),
        "material_number": normalize_text(safe_get(data, "material_number")),
        "alert_type": normalize_text(safe_get(data, "alert_type")),
        "severity": normalize_text(safe_get(data, "severity")),
        "message": normalize_text(safe_get(data, "message")),
        "current_qty": normalize_int(safe_get(data, "current_qty")),
        "expiry_date": normalize_text(safe_get(data, "expiry_date")),
        "days_remaining": normalize_int(safe_get(data, "days_remaining")),
        "resolved": parse_bool(safe_get(data, "resolved")),
        "updated_at": normalize_text(safe_get(data, "updated_at")),
    }


from runtime.shared.objects import first_value
from runtime.shared.strings import best_product_name


def catalog_product_display_name(payload: dict, material: str) -> str:
    return best_product_name(
        material,
        payload.get("name"),
        payload.get("product_name"),
        payload.get("productName"),
        payload.get("material_name"),
        payload.get("materialName"),
        payload.get("description"),
        payload.get("display_name"),
        payload.get("displayName"),
        material,
    )


def normalize_stored_product(item: Any) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    material_number = normalize_text(
        first_value(
            data,
            "material_number",
            "material_id",
            "material",
            "material_code",
            "code",
            "matnr",
        )
    )
    name = catalog_product_display_name(data, material_number)
    return {
        "material_number": material_number,
        "name": name,
        "material_name": name,
        "is_active": parse_bool(
            first_value(data, "is_active", "active", "enabled", default=True), True
        ),
    }


def normalize_usage_product(item: Any) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    material = normalize_text(
        first_value(data, "material", "material_number", "material_code")
    )
    name = normalize_text(first_value(data, "material_name", "name", default=material))
    unit = normalize_text(first_value(data, "unit", "uom"))
    return {
        "material": material,
        "material_number": material,
        "material_code": material,
        "name": name,
        "material_name": name,
        "uom": unit,
        "unit": unit,
        "active": parse_bool(safe_get(data, "active"), True),
    }


_DELETE_OPERATIONS = {"delete", "deleted", "remove", "removed", "purge", "tombstone"}
_DELETE_FLAGS = ("deleted", "is_deleted", "tombstone")


def change_entity(change: dict) -> str:
    return normalize_text(change.get("entity_type") or change.get("type")).lower()


def change_operation(change: dict) -> str:
    op = normalize_text(
        change.get("op")
        or change.get("operation")
        or change.get("action")
        or change.get("event")
        or change.get("change_type")
    ).lower()
    if op in _DELETE_OPERATIONS:
        return "delete"
    payload = (
        change.get("payload") if isinstance(change.get("payload"), dict) else change
    )
    if any((parse_bool(change.get(flag), False) for flag in _DELETE_FLAGS)):
        return "delete"
    if isinstance(payload, dict) and any(
        (parse_bool(payload.get(flag), False) for flag in _DELETE_FLAGS)
    ):
        return "delete"
    return "upsert"


def change_payload(change: dict) -> dict:
    payload = (
        change.get("payload") if isinstance(change.get("payload"), dict) else change
    )
    payload = dict(payload or {})
    branch = normalize_text(
        payload.get("branch")
        or payload.get("branch_id")
        or payload.get("branch_code")
        or change.get("branch_id")
        or change.get("branch_code")
        or change.get("branch")
    )
    if branch:
        payload.setdefault("branch", branch)
        payload.setdefault("branch_id", branch)
    entity_key = normalize_text(change.get("entity_key") or change.get("key"))
    if entity_key:
        payload.setdefault("id", entity_key)
        payload.setdefault("doc_id", entity_key)
    return payload




def normalize_branch_payload(item: Any) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    code = normalize_text(
        safe_get(data, "branch_id")
        or safe_get(data, "branch_code")
        or safe_get(data, "code")
        or safe_get(data, "id")
    )
    area_id = normalize_text(
        safe_get(data, "area_id")
        or safe_get(data, "area_code")
        or safe_get(data, "area_name")
    )
    region_id = normalize_text(
        safe_get(data, "region_id")
        or safe_get(data, "region_code")
        or safe_get(data, "region_name")
    )
    return {
        "branch_id": code,
        "code": code,
        "region_id": region_id,
        "area_id": area_id,
        "area_manager_id": normalize_text(
            safe_get(data, "area_manager_id")
            or safe_get(data, "area_manager_user_id")
            or safe_get(data, "area_manager")
            or safe_get(data, "manager_username")
        ),
        "branch_manager_id": normalize_text(
            safe_get(data, "branch_manager_id")
            or safe_get(data, "branch_manager_user_id")
            or safe_get(data, "manager_id")
            or safe_get(data, "manager_username")
        ),
        "name": normalize_text(safe_get(data, "name") or code),
        "is_active": parse_bool(safe_get(data, "is_active"), True),
    }


def normalize_region_payload(item: Any) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    region_id = normalize_text(
        safe_get(data, "region_id")
        or safe_get(data, "region_code")
        or safe_get(data, "region_name")
        or safe_get(data, "code")
        or safe_get(data, "id")
        or safe_get(data, "name")
    )
    return {
        "region_id": region_id,
        "name": normalize_text(safe_get(data, "name") or region_id),
        "region_manager_id": normalize_text(
            safe_get(data, "region_manager_id")
            or safe_get(data, "region_manager_user_id")
            or safe_get(data, "manager_id")
            or safe_get(data, "manager_username")
        ),
        "is_active": parse_bool(safe_get(data, "is_active"), True),
    }


def normalize_area_payload(item: Any) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    area_id = normalize_text(
        safe_get(data, "area_id")
        or safe_get(data, "area_code")
        or safe_get(data, "area_name")
        or safe_get(data, "code")
        or safe_get(data, "id")
        or safe_get(data, "name")
    )
    region_id = normalize_text(
        safe_get(data, "region_id")
        or safe_get(data, "region_code")
        or safe_get(data, "region_name")
    )
    return {
        "area_id": area_id,
        "region_id": region_id,
        "name": normalize_text(safe_get(data, "name") or area_id),
        "area_manager_id": normalize_text(
            safe_get(data, "area_manager_id")
            or safe_get(data, "area_manager_user_id")
            or safe_get(data, "manager_id")
            or safe_get(data, "manager_username")
        ),
        "temporary_manager": parse_bool(safe_get(data, "temporary_manager"), False),
        "is_active": parse_bool(safe_get(data, "is_active"), True),
    }


from runtime.domain.remote_ids import normalize_remote_id

TRACKING_NAME_FIELDS = (
    "product_name",
    "productName",
    "material_name",
    "materialName",
    "name",
    "description",
    "display_name",
    "displayName",
    "item_name",
    "itemName",
)


def _tracking_item_name(
    data: dict[str, Any], material_number: str, stored_name: str
) -> str:
    return best_product_name(
        material_number,
        *(safe_get(data, field) for field in TRACKING_NAME_FIELDS),
        stored_name,
        material_number,
    )


def normalize_tracking_item(item: Any, stored_name: str = "") -> dict[str, Any]:
    data = safe_get(item, "item", item) if isinstance(item, dict) else {}
    remote_id = normalize_remote_id(data)
    material_number = normalize_text(
        safe_get(data, "material_number")
        or safe_get(data, "material_id")
        or safe_get(data, "material_code")
        or safe_get(data, "code")
    )
    name = _tracking_item_name(data, material_number, stored_name)
    return {
        "id": remote_id,
        "doc_id": remote_id,
        "branch_id": normalize_text(
            safe_get(data, "branch_id") or safe_get(data, "branch")
        ),
        "branch": normalize_text(
            safe_get(data, "branch") or safe_get(data, "branch_id")
        ),
        "material_number": material_number,
        "material_id": material_number,
        "name": name,
        "material_name": name,
        "quantity": normalize_int(safe_get(data, "quantity") or safe_get(data, "qty")),
        "production_date": normalize_text(
            safe_get(data, "production_date") or safe_get(data, "prod_date")
        ),
        "prod_date": normalize_text(
            safe_get(data, "prod_date") or safe_get(data, "production_date")
        ),
        "expiry_date": normalize_text(
            safe_get(data, "expiry_date") or safe_get(data, "exp_date")
        ),
        "exp_date": normalize_text(
            safe_get(data, "exp_date") or safe_get(data, "expiry_date")
        ),
        "note": normalize_text(safe_get(data, "note")),
        "updated_at": normalize_text(safe_get(data, "updated_at")),
        "raw": data if isinstance(data, dict) else {},
    }


from runtime.shared.objects import normalize_str_list


def normalize_user(item: Any) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    scope = safe_get(data, "scope") if isinstance(safe_get(data, "scope"), dict) else {}
    username = normalize_text(safe_get(data, "username") or safe_get(data, "uid"))
    real_user_id = normalize_text(
        safe_get(data, "id")
        or safe_get(data, "user_id")
        or safe_get(data, "uid")
        or username
    )
    branches = normalize_str_list(
        safe_get(scope, "branches")
        or safe_get(data, "assigned_branch_ids")
        or safe_get(data, "branches")
        or safe_get(data, "branch_scope")
    )
    regions = normalize_str_list(
        safe_get(scope, "regions")
        or safe_get(data, "region_scope")
        or ([safe_get(data, "region_id")] if safe_get(data, "region_id") else [])
    )
    areas = normalize_str_list(
        safe_get(scope, "areas")
        or safe_get(data, "area_scope")
        or ([safe_get(data, "area_id")] if safe_get(data, "area_id") else [])
    )
    return {
        "id": real_user_id,
        "user_id": real_user_id,
        "username": username or real_user_id,
        "full_name": normalize_text(
            safe_get(data, "full_name")
            or safe_get(data, "display_name")
            or username
            or real_user_id
        ),
        "role": normalize_text(safe_get(data, "role") or "store_user"),
        "permissions": normalize_str_list(safe_get(data, "permissions")),
        "branches": branches,
        "branch_scope": branches,
        "assigned_branch_ids": normalize_str_list(
            safe_get(data, "assigned_branch_ids") or branches
        ),
        "area_scope": areas,
        "scope": {
            "regions": regions,
            "areas": areas,
            "branches": branches,
            "all_regions": parse_bool(safe_get(scope, "all_regions"), False),
            "all_areas": parse_bool(safe_get(scope, "all_areas"), False),
            "all_branches": parse_bool(safe_get(scope, "all_branches"), False),
        },
        "region_scope": regions,
        "region_id": normalize_text(safe_get(data, "region_id")),
        "area_id": normalize_text(safe_get(data, "area_id")),
        "area_manager_id": normalize_text(
            safe_get(data, "area_manager_id") or safe_get(data, "area_manager_user_id")
        ),
        "must_change_password": parse_bool(
            safe_get(data, "must_change_password"), False
        ),
        "temporary_manager": parse_bool(safe_get(data, "temporary_manager"), False),
        "is_active": parse_bool(safe_get(data, "is_active"), True),
    }
