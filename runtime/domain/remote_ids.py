from __future__ import annotations
from typing import Any
from runtime.shared.objects import safe_get
from runtime.shared.strings import normalize_text

REMOTE_ID_KEYS = (
    "doc_id",
    "document_id",
    "tracking_id",
    "tracked_id",
    "track_id",
    "item_id",
    "row_id",
    "uuid",
    "_id",
    "pk",
    "id",
)


def split_cloud_id(value: Any) -> tuple[str, str]:
    text = str(value or "").strip()
    if "::" not in text:
        return ("", text)
    branch, document_id = text.split("::", 1)
    return (branch.strip(), document_id.strip())


def valid_remote_doc_id(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and text != "0")


def qualify_remote_doc_id(branch: Any, document_id: Any) -> str:
    doc_text = str(document_id or "").strip()
    branch_text = str(branch or "").strip()
    if not branch_text or "::" in doc_text:
        return doc_text
    return f"{branch_text}::{doc_text}"


def normalize_remote_id(data: Any) -> str:
    source = data if isinstance(data, dict) else {}
    for key in REMOTE_ID_KEYS:
        value = safe_get(source, key)
        text = normalize_text(value)
        if text and text != "0":
            return text
    nested = safe_get(source, "item")
    if isinstance(nested, dict) and nested is not source:
        return normalize_remote_id(nested)
    return ""
