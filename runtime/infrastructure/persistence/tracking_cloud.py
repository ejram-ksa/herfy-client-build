from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from runtime.shared.objects import normalize_int
from runtime.shared.strings import best_product_name
from runtime.domain.remote_ids import normalize_remote_id


def build_cloud_cache_key(branch: str, doc_id: str) -> str:
    branch_text = str(branch or "").strip()
    doc_text = str(doc_id or "").strip()
    if branch_text and doc_text:
        return f"{branch_text}::{doc_text}"
    return doc_text


def normalize_cloud_tracking_record(
    record: Mapping[str, Any] | None,
    *,
    stored_name_cache: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = dict(record or {})
    material = str(source.get("material_number", "") or "").strip()
    doc_id = str(source.get("doc_id") or source.get("id") or "").strip()
    cached_name = ""
    if stored_name_cache:
        cached_name = str(stored_name_cache.get(material) or "").strip()
    normalized: dict[str, Any] = {
        "doc_id": doc_id,
        "material_number": material,
        "name": best_product_name(
            material,
            source.get("product_name"),
            source.get("material_name"),
            source.get("name"),
            cached_name,
            material,
        ),
        "production_date": str(source.get("production_date", "") or ""),
        "expiry_date": str(source.get("expiry_date", "") or ""),
        "branch": str(source.get("branch", "") or "").strip(),
    }
    normalized["quantity"] = normalize_int(source.get("quantity"), 0)
    normalized["id"] = build_cloud_cache_key(normalized["branch"], normalized["doc_id"])
    return normalized


def cloud_tracking_record_from_item(
    item: Mapping[str, Any] | None,
    *,
    stored_name_cache: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = dict(item or {})
    raw = source.get("raw") if isinstance(source.get("raw"), Mapping) else {}
    material = str(
        source.get("material_number", "")
        or raw.get("material_number", "")
        or raw.get("material_id", "")
        or ""
    ).strip()
    remote_id = normalize_remote_id(source) or normalize_remote_id(raw)
    cached_name = ""
    if stored_name_cache:
        cached_name = str(stored_name_cache.get(material) or "").strip()
    return normalize_cloud_tracking_record(
        {
            "doc_id": remote_id,
            "material_number": material,
            "name": best_product_name(
                material,
                source.get("product_name"),
                source.get("material_name"),
                source.get("name"),
                raw.get("product_name"),
                raw.get("material_name"),
                raw.get("name"),
                cached_name,
                material,
            ),
            "quantity": source.get("quantity", 0),
            "production_date": source.get("production_date")
            or raw.get("production_date")
            or source.get("prod_date")
            or raw.get("prod_date")
            or "",
            "expiry_date": source.get("expiry_date")
            or raw.get("expiry_date")
            or source.get("exp_date")
            or raw.get("exp_date")
            or "",
            "branch": source.get("branch", "") or raw.get("branch", "") or "",
        },
        stored_name_cache=stored_name_cache,
    )
