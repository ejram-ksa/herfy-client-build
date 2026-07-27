from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from typing import Any

from runtime.domain.tracking_models import RemoteTrackingId, TrackingRecord
from runtime.domain.tracking_models import TrackingKey

_NESTED_KEYS = ("item", "product", "data", "payload", "raw")
_BRANCH_KEYS = ("branch", "branch_code", "branch_id")
_MATERIAL_KEYS = (
    "material_number",
    "material_code",
    "material_id",
    "material",
    "code",
)
_EXPIRY_KEYS = (
    "expiry_date",
    "exp_date",
    "expiryDate",
    "expiration_date",
    "expiration",
)
_PRODUCTION_KEYS = (
    "production_date",
    "prod_date",
    "productionDate",
    "manufacturing_date",
    "mfg_date",
)
_ID_KEYS = (
    "doc_id",
    "document_id",
    "tracking_id",
    "tracked_id",
    "item_id",
    "uuid",
    "_id",
    "id",
)


def _sources(row: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    source = row if isinstance(row, Mapping) else {}
    nested: list[Mapping[str, Any]] = [source]
    for key in _NESTED_KEYS:
        value = source.get(key)
        if isinstance(value, Mapping):
            nested.append(value)
    return tuple(nested)


def _first_text(row: Mapping[str, Any] | None, keys: tuple[str, ...]) -> str:
    for source in _sources(row):
        for key in keys:
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _date_or_none(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None



def tracking_key_sort_value(key: TrackingKey) -> tuple[str, str, str, str]:
    """Return the canonical deterministic ordering for tracking keys."""

    return (
        key.branch_code.casefold(),
        key.material_number.casefold(),
        key.production_date.isoformat() if key.production_date else "",
        key.expiry_date.isoformat(),
    )

def tracking_key_from_row(row: Mapping[str, Any] | None) -> TrackingKey | None:
    branch = _first_text(row, _BRANCH_KEYS)
    material = _first_text(row, _MATERIAL_KEYS)
    production = _date_or_none(_first_text(row, _PRODUCTION_KEYS))
    expiry = _date_or_none(_first_text(row, _EXPIRY_KEYS))
    if not branch or not material or expiry is None:
        return None
    return TrackingKey(
        branch_code=branch,
        material_number=material,
        production_date=production,
        expiry_date=expiry,
    )


def tracking_record_from_row(row: Mapping[str, Any] | None) -> TrackingRecord | None:
    key = tracking_key_from_row(row)
    if key is None:
        return None
    remote_id = _first_text(row, _ID_KEYS)
    if "::" in remote_id:
        remote_id = remote_id.split("::", 1)[1].strip()
    try:
        quantity = int(_first_text(row, ("quantity", "qty", "on_hand")) or 0)
    except ValueError:
        quantity = 0
    try:
        revision = int(_first_text(row, ("revision", "record_revision")) or 0)
    except ValueError:
        revision = 0
    updated_text = _first_text(row, ("updated_at", "modified_at", "created_at"))
    try:
        updated_at = datetime.fromisoformat(updated_text.replace("Z", "+00:00"))
    except ValueError:
        updated_at = datetime.now(timezone.utc)
    product_name = _first_text(row, ("product_name", "name", "material_name"))
    branch_name = _first_text(row, ("branch_name", "branch_label", "store_name"))
    return TrackingRecord(
        key=key,
        remote_id=RemoteTrackingId(remote_id),
        product_name=product_name or key.material_number,
        branch_name=branch_name,
        quantity=quantity,
        revision=revision,
        updated_at=updated_at,
    )


def tracking_record_identity_keys(
    row: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Return exact and business identities for one shelf-life record.

    The remote id identifies the server document. Branch/material/expiry is
    the previous business identity already used by create-or-merge. The primary
    logical identity includes production date so two batches with the same
    branch/material/expiry do not collapse into one row.
    """

    branch = _first_text(row, _BRANCH_KEYS).casefold()
    material = _first_text(row, _MATERIAL_KEYS).casefold()
    production = _first_text(row, _PRODUCTION_KEYS)
    expiry = _first_text(row, _EXPIRY_KEYS)
    remote_id = _first_text(row, _ID_KEYS)
    if "::" in remote_id:
        id_branch, bare_id = remote_id.split("::", 1)
        branch = branch or id_branch.strip().casefold()
        remote_id = bare_id.strip()

    keys: list[str] = []
    if material and expiry:
        keys.append(f"logical:{branch}|{material}|{production}|{expiry}")
    if remote_id:
        keys.append(f"remote:{branch}|{remote_id.casefold()}")
    return tuple(dict.fromkeys(keys))


def deduplicate_tracking_records(
    rows: Iterable[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Keep one current row for each exact or business identity."""

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        copied = dict(row)
        keys = tracking_record_identity_keys(copied)
        if keys and any(key in seen for key in keys):
            continue
        result.append(copied)
        seen.update(keys)
    return result
