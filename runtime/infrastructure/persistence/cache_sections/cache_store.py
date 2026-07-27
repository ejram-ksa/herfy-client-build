from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

import sqlite3
import logging
from runtime.shared.settings.config import _
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.domain.remote_ids import split_cloud_id, valid_remote_doc_id

logger = logging.getLogger(__name__)
_SESSION_CLEAR_SQL = {
    "cloud_tracked_products": "DELETE FROM cloud_tracked_products",
    "notify_log": "DELETE FROM notify_log",
    "stored_products": "DELETE FROM stored_products",
    "usage_products": "DELETE FROM usage_products",
    "usage_products_pending": "DELETE FROM usage_products_pending",
}


class CloudCacheContextRepositoryMixin:

    def _split_cloud_id(self, pid: str):
        return split_cloud_id(pid)

    def _valid_cloud_doc_id(self, doc_id: str | None) -> bool:
        return valid_remote_doc_id(doc_id)

    def _missing_cloud_doc_id_error(self, *, silent: bool = False) -> bool:
        return self._show_error(
            _("Server record id is missing. Refresh shelf-life data and try again."),
            silent=silent,
        )

    def _require_cloud_doc_id(
        self, doc_id: str | None, *, silent: bool = False
    ) -> bool:
        if self._valid_cloud_doc_id(doc_id):
            return True
        self._missing_cloud_doc_id_error(silent=silent)
        return False

    def clear_session_scoped_local_data(self, *, clear_catalog: bool = True) -> None:
        """Clear data fetched for the authenticated user after manual logout.

        This prevents stale branch-scoped records, suggested products, usage
        catalog rows, and notification state from being reused under another
        user's permissions.  Persistent settings and application resources are
        intentionally kept.
        """
        try:
            self._cloud_cache_by_id.clear()
            self._cloud_list_cache.clear()
            self._stored_name_cache.clear()
            self._tracking_fetch_events.clear()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Clearing in-memory session data failed", exc_info=True)
        tables = ["cloud_tracked_products", "notify_log"]
        if clear_catalog:
            tables.extend(
                ["stored_products", "usage_products", "usage_products_pending"]
            )
        try:
            with self._db_lock:
                conn = self._fresh_connection()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    for table in tables:
                        try:
                            conn.execute(_SESSION_CLEAR_SQL[table])
                        except sqlite3.Error:
                            logger.debug(
                                "Skipping missing/locked session table %s",
                                table,
                                exc_info=True,
                            )
                    conn.commit()
                except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
                    try:
                        conn.rollback()
                    except SERVICE_OPERATION_EXCEPTIONS:
                        logger.debug(
                            "Session data cleanup rollback failed", exc_info=True
                        )
                    raise
                finally:
                    conn.close()
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.debug("Clearing persisted session scoped data failed", exc_info=True)

    def invalidate_cloud_cache(self, branch: str | None = None):
        try:
            if branch:
                b = str(branch)
                self._cloud_list_cache.pop(b, None)
                self._cloud_list_cache.pop(b.lower(), None)
                self._cloud_list_cache.pop(b.upper(), None)
            self._cloud_list_cache.pop("", None)
            self._cloud_list_cache.pop("all", None)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "DatabaseCloudContextMixin.invalidate_cloud_cache fallback failed",
                exc_info=True,
            )
        try:
            service = self._cloud_service()
            if service and hasattr(service, "invalidate_tracking_cache"):
                service.invalidate_tracking_cache(branch)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "DatabaseCloudContextMixin.invalidate_cloud_cache fallback failed",
                exc_info=True,
            )





def is_transient_remote_error(exc: Exception) -> bool:
    exc_type = type(exc).__name__
    if exc_type == "SessionExpiredError":
        return False
    status_code = getattr(exc, "status_code", None)
    if exc_type == "RemoteRequestError":
        return status_code in (None, 502, 503, 504)
    message = str(exc or "").lower()
    if not message:
        return False
    transient_markers = (
        "server not reachable",
        "temporarily unavailable",
        "timed out",
        "timeout",
        "connection aborted",
        "connection reset",
        "connection refused",
        "failed to establish a new connection",
        "name or service not known",
    )
    return any((marker in message for marker in transient_markers))


from runtime.shared.objects import safe_get
from runtime.shared.strings import normalize_text
from runtime.domain.remote_ids import normalize_remote_id
from runtime.domain.tracking_rows import (
    deduplicate_tracking_records,
    tracking_record_identity_keys,
)
from runtime.application.dto import change_entity, change_operation, change_payload
from datetime import datetime
import time
import json



class TrackingCacheRepositoryMixin:

    def _cloud_cache_key(self, branch: str, doc_id: str) -> str:
        from runtime.infrastructure.persistence.tracking_cloud import build_cloud_cache_key

        return build_cloud_cache_key(branch, doc_id)

    def _cache_cloud_record(self, record: dict | None) -> dict:
        from runtime.infrastructure.persistence.tracking_cloud import normalize_cloud_tracking_record

        rec = normalize_cloud_tracking_record(
            record, stored_name_cache=self._stored_name_cache
        )
        cid = str(rec.get("id") or "").strip()
        if cid:
            identities = set(tracking_record_identity_keys(rec))
            if identities:
                for cached_id, cached_row in list(self._cloud_cache_by_id.items()):
                    if cached_id == cid:
                        continue
                    if identities.intersection(
                        tracking_record_identity_keys(cached_row)
                    ):
                        self._cloud_cache_by_id.pop(cached_id, None)
            self._cloud_cache_by_id[cid] = rec
        return rec

    def _cloud_record_from_item(self, item: dict) -> dict:
        from runtime.infrastructure.persistence.tracking_cloud import cloud_tracking_record_from_item

        return cloud_tracking_record_from_item(
            item, stored_name_cache=self._stored_name_cache
        )

    def _tracking_cache_key_accepts_record(self, cache_key: str, record: dict) -> bool:
        key = str(cache_key or "").strip().lower()
        branch = str(record.get("branch") or "").strip().lower()
        if key in {"", "all"}:
            return True
        if key == "scope_all":
            allowed = {
                str(b).strip().lower()
                for b in self.allowed_branches() or []
                if str(b).strip()
            }
            return not allowed or branch in allowed
        return branch == key

    def _remove_tracking_record_from_cloud_caches(
        self, doc_id: str, branch: str = ""
    ) -> list[str]:
        doc = str(doc_id or "").strip()
        branch_text = str(branch or "").strip()
        if not doc:
            return []
        removed: list[str] = []
        exact_key = self._cloud_cache_key(branch_text, doc) if branch_text else doc
        for cache_key, rec in list(self._cloud_cache_by_id.items()):
            rec_doc = (
                str(rec.get("doc_id") or rec.get("id") or "").split("::")[-1].strip()
            )
            rec_branch = str(rec.get("branch") or "").strip()
            if cache_key == exact_key or (
                rec_doc == doc
                and (not branch_text or rec_branch.lower() == branch_text.lower())
            ):
                removed_id = str(rec.get("id") or cache_key)
                removed.append(removed_id)
                self._cloud_cache_by_id.pop(cache_key, None)
                self._delete_persisted_cloud_tracking_record(removed_id, rec_branch)

        def _keep(row: dict) -> bool:
            row_doc = (
                str(row.get("doc_id") or row.get("id") or "").split("::")[-1].strip()
            )
            row_branch = str(row.get("branch") or "").strip()
            return not (
                row_doc == doc
                and (not branch_text or row_branch.lower() == branch_text.lower())
            )

        for key, cached in list(self._cloud_list_cache.items()):
            ts, rows = cached
            filtered = [row for row in rows if _keep(row)]
            if len(filtered) != len(rows):
                self._cloud_list_cache[key] = (ts, filtered)
        return removed or [exact_key]

    def _upsert_tracking_record_in_cloud_caches(self, record: dict) -> dict | None:
        rec = self._cache_cloud_record(record)
        rec_id = str(rec.get("id") or "").strip()
        if not rec_id:
            return None
        self._persist_cloud_tracking_records([rec])
        for key, cached in list(self._cloud_list_cache.items()):
            ts, rows = cached
            accepts = self._tracking_cache_key_accepts_record(key, rec)
            updated: list[dict] = []
            found = False
            for row in rows:
                row_id = str(row.get("id") or "").strip()
                row_doc = str(row.get("doc_id") or "").strip()
                if row_id == rec_id or (
                    row_doc and row_doc == str(rec.get("doc_id") or "")
                ):
                    found = True
                    if accepts:
                        updated.append(dict(rec))
                    continue
                updated.append(row)
            if accepts and (not found):
                updated.append(dict(rec))
            self._cloud_list_cache[key] = (
                ts,
                deduplicate_tracking_records(updated),
            )
        return rec

    def apply_remote_tracking_changes(self, changes: list[dict]) -> dict:
        upserts: list[dict] = []
        deletes: list[str] = []
        changed_branches: set[str] = set()
        for change in changes or []:
            if not isinstance(change, dict):
                continue
            entity = change_entity(change)
            if entity and entity not in {
                "tracking",
                "tracking_item",
                "tracked_product",
            }:
                continue
            payload = change_payload(change)
            op = change_operation(change)
            branch = normalize_text(payload.get("branch") or payload.get("branch_id"))
            doc_id = normalize_remote_id(payload) or normalize_text(
                change.get("entity_key")
            )
            if branch:
                changed_branches.add(branch)
            if op == "delete":
                deletes.extend(
                    self._remove_tracking_record_from_cloud_caches(doc_id, branch)
                )
                continue
            record = self._cloud_record_from_item(payload)
            if not record.get("doc_id"):
                continue
            if branch and (not record.get("branch")):
                record["branch"] = branch
            applied = self._upsert_tracking_record_in_cloud_caches(record)
            if applied:
                upserts.append(dict(applied))
        return {
            "upserts": upserts,
            "deletes": deletes,
            "branches": sorted(changed_branches),
            "applied": bool(upserts or deletes),
        }

    def _persist_cloud_tracking_records(self, rows: list[dict]) -> bool:
        rows = deduplicate_tracking_records(rows)
        if not rows:
            return True
        try:
            with self._db_lock:
                conn = self._fresh_connection()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    now_text = datetime.now().isoformat(timespec="seconds")
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        row_id = normalize_text(row.get("id") or row.get("doc_id"))
                        if not row_id:
                            continue
                        branch = normalize_text(row.get("branch"))
                        material = normalize_text(row.get("material_number"))
                        expiry = normalize_text(
                            row.get("expiry_date") or row.get("expiration_date")
                        )
                        if material and expiry:
                            conn.execute(
                                """
                                DELETE FROM cloud_tracked_products
                                WHERE lower(branch)=lower(?)
                                  AND lower(material_number)=lower(?)
                                  AND expiry_date=?
                                  AND id<>?
                                """,
                                (branch, material, expiry, row_id),
                            )
                        conn.execute(
                            "\n                            INSERT OR REPLACE INTO cloud_tracked_products(\n                                id, branch, material_number, expiry_date, payload, updated_at\n                            ) VALUES(?,?,?,?,?,?)\n                            ",
                            (
                                row_id,
                                branch,
                                material,
                                expiry,
                                json.dumps(row, ensure_ascii=False, sort_keys=True),
                                now_text,
                            ),
                        )
                    conn.commit()
                    return True
                except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
                    try:
                        conn.rollback()
                    except SERVICE_OPERATION_EXCEPTIONS:
                        logger.debug(
                            "Cloud tracking cache rollback failed", exc_info=True
                        )
                    raise
                finally:
                    conn.close()
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.exception("Persisting cloud tracking cache failed")
            return False

    def replace_cached_cloud_tracking_products(self, rows: list[dict] | None) -> bool:
        try:
            with self._db_lock:
                conn = self._fresh_connection()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute("DELETE FROM cloud_tracked_products")
                    conn.commit()
                except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
                    try:
                        conn.rollback()
                    except SERVICE_OPERATION_EXCEPTIONS:
                        logger.debug(
                            "Cloud tracking baseline rollback failed", exc_info=True
                        )
                    raise
                finally:
                    conn.close()
                self._cloud_cache_by_id.clear()
                self._cloud_list_cache.clear()
                return self._persist_cloud_tracking_records(list(rows or []))
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.exception("Replacing cloud tracking baseline failed")
            return False

    def _delete_persisted_cloud_tracking_record(
        self, row_id: str, branch: str = ""
    ) -> None:
        try:
            key = normalize_text(row_id)
            branch_text = normalize_text(branch)
            if not key:
                return
            with self._db_lock:
                conn = self._fresh_connection()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    if branch_text:
                        conn.execute(
                            "\n                            DELETE FROM cloud_tracked_products\n                            WHERE id=?\n                               OR (\n                                   json_extract(payload, '$.doc_id')=?\n                                   AND lower(branch)=lower(?)\n                               )\n                            ",
                            (key, key.split("::")[-1], branch_text),
                        )
                    else:
                        conn.execute(
                            "\n                            DELETE FROM cloud_tracked_products\n                            WHERE id=? OR json_extract(payload, '$.doc_id')=?\n                            ",
                            (key, key.split("::")[-1]),
                        )
                    conn.commit()
                except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
                    try:
                        conn.rollback()
                    except SERVICE_OPERATION_EXCEPTIONS:
                        logger.debug(
                            "Cloud tracking delete rollback failed", exc_info=True
                        )
                    raise
                finally:
                    conn.close()
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.debug(
                "Deleting persisted cloud tracking cache failed", exc_info=True
            )

    def _load_persisted_cloud_tracking_records(self, cache_key: str) -> list[dict]:
        try:
            conn = self._fresh_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT payload FROM cloud_tracked_products "
                    "ORDER BY updated_at DESC"
                )
                rows: list[dict] = []
                allowed = {
                    str(b).strip().lower()
                    for b in self.allowed_branches() or []
                    if str(b).strip()
                }
                wanted = normalize_text(cache_key).lower()
                for db_row in cursor.fetchall():
                    payload_text = safe_get(db_row, "payload", "")
                    try:
                        row = json.loads(str(payload_text or "{}"))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if not isinstance(row, dict):
                        continue
                    branch = normalize_text(row.get("branch")).lower()
                    if wanted in {"", "all"}:
                        rows.append(row)
                    elif wanted == "scope_all":
                        if not allowed or branch in allowed:
                            rows.append(row)
                    elif branch == wanted:
                        rows.append(row)
                rows = deduplicate_tracking_records(rows)
                for row in rows:
                    self._cache_cloud_record(row)
                if rows:
                    self._cloud_list_cache[wanted] = (
                        time.monotonic(),
                        [dict(row) for row in rows],
                    )
                return rows
            finally:
                conn.close()
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.debug("Loading persisted cloud tracking cache failed", exc_info=True)
            return []

    def _cloud_cache_key_for_branch(
        self, branch_filter_override: str | None = None
    ) -> str:
        branch_filter_raw = (
            branch_filter_override
            if branch_filter_override is not None
            else self.get_active_branch()
        )
        branch_filter_raw = str(branch_filter_raw or "").strip()
        cache_key = branch_filter_raw.lower() if branch_filter_raw else ""
        allowed = {
            str(b).strip().lower()
            for b in self.allowed_branches() or []
            if str(b).strip()
        }
        if cache_key == "all" and (not self.can_view_all_branches()) and allowed:
            return "scope_all"
        if cache_key == "all":
            return "all"
        return cache_key

    def fetch_cached_tracked_products(
        self, branch_filter_override: str | None = None
    ) -> list[dict]:
        cache_key = self._cloud_cache_key_for_branch(branch_filter_override)
        allowed = {
            str(b).strip().lower()
            for b in self.allowed_branches() or []
            if str(b).strip()
        }
        cached = self._cloud_list_cache.get(cache_key)
        if cached is not None:
            _ts, rows = cached
            return deduplicate_tracking_records(rows)
        rows: list[dict] = []
        for row in self._cloud_cache_by_id.values():
            branch = str(row.get("branch") or "").strip().lower()
            if cache_key in ("", "all"):
                rows.append(dict(row))
            elif cache_key == "scope_all":
                if not allowed or branch in allowed:
                    rows.append(dict(row))
            elif branch == cache_key:
                rows.append(dict(row))
        if rows:
            return deduplicate_tracking_records(rows)
        return self._load_persisted_cloud_tracking_records(cache_key)
