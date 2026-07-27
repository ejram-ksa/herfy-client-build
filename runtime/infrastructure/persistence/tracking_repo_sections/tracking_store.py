from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

import logging
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.objects import safe_get
from runtime.application.dto import catalog_product_display_name
from runtime.application.dto import change_entity, change_operation, change_payload
from runtime.shared.strings import normalize_text

logger = logging.getLogger(__name__)


class TrackingCatalogRepositoryMixin:

    def add_stored_product(self, mat_num: str, name_: str):
        c = self.connection.cursor()
        c.execute(
            "INSERT OR REPLACE INTO stored_products(material_number,name) VALUES(?,?)",
            (mat_num, name_),
        )
        self.connection.commit()
        cloud_tracking = self._cloud_service()
        if cloud_tracking is not None:
            try:
                cloud_tracking.upsert_stored_product(str(mat_num), str(name_))
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug("Stored product remote sync failed", exc_info=True)
        cache = getattr(self, "_stored_name_cache", None)
        if cache is None:
            self._stored_name_cache = {}
            cache = self._stored_name_cache
        cache[str(mat_num).strip()] = str(name_).strip()

    def fetch_stored_products(self):
        c = self.connection.cursor()
        c.execute("SELECT material_number,name FROM stored_products")
        rows = [dict(r) for r in c.fetchall()]
        self._stored_name_cache = {
            str(safe_get(r, "material_number", "")): str(safe_get(r, "name", ""))
            for r in rows
        }
        return rows

    def refresh_stored_products_from_cloud(self) -> list[dict]:
        cloud_tracking = self._cloud_service()
        if cloud_tracking is None:
            return self.fetch_stored_products()
        try:
            remote_rows = cloud_tracking.list_stored_products()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Remote stored product refresh failed", exc_info=True)
            return self.fetch_stored_products()
        if remote_rows:
            return self.merge_remote_stored_products(remote_rows)
        return self.fetch_stored_products()

    def merge_remote_stored_products(self, rows: list[dict] | None) -> list[dict]:
        cursor = self.connection.cursor()
        applied: list[dict] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            material = normalize_text(
                row.get("material_number")
                or row.get("material_code")
                or row.get("material")
                or row.get("code")
            )
            if not material:
                continue
            name = normalize_text(
                row.get("name")
                or row.get("material_name")
                or row.get("description")
                or material
            )
            cursor.execute(
                "INSERT OR REPLACE INTO stored_products(material_number,name) VALUES(?,?)",
                (material, name),
            )
            applied.append({"material_number": material, "name": name})
        if applied:
            self.connection.commit()
            self._stored_name_cache.update(
                {row["material_number"]: row["name"] for row in applied}
            )
        return applied

    def apply_remote_stored_product_changes(self, changes: list[dict]) -> dict:
        upserts = 0
        deletes = 0
        cache = getattr(self, "_stored_name_cache", None)
        if cache is None:
            self._stored_name_cache = {}
            cache = self._stored_name_cache
        cursor = self.connection.cursor()
        for change in changes or []:
            if not isinstance(change, dict):
                continue
            entity = change_entity(change)
            if entity and entity not in {
                "stored_product",
                "catalog_product",
                "product",
            }:
                continue
            payload = change_payload(change)
            material = normalize_text(
                payload.get("material_number")
                or payload.get("material_code")
                or payload.get("material")
                or payload.get("code")
            )
            if not material:
                continue
            if change_operation(change) == "delete":
                cursor.execute(
                    "DELETE FROM stored_products WHERE material_number=?", (material,)
                )
                cache.pop(material, None)
                deletes += 1
                continue
            name = catalog_product_display_name(payload, material)
            cursor.execute(
                "INSERT OR REPLACE INTO stored_products(material_number,name) VALUES(?,?)",
                (material, name),
            )
            cache[material] = name
            upserts += 1
        if upserts or deletes:
            self.connection.commit()
        return {
            "upserts": upserts,
            "deletes": deletes,
            "applied": bool(upserts or deletes),
        }

    def stored_product_exists(self, mat_num: str) -> bool:
        material = str(mat_num or "").strip()
        if not material:
            return False
        c = self.connection.cursor()
        c.execute("SELECT 1 FROM stored_products WHERE material_number=?", (material,))
        return bool(c.fetchone())

    def delete_stored_product(self, mat_num: str):
        c = self.connection.cursor()
        c.execute("DELETE FROM stored_products WHERE material_number=?", (mat_num,))
        self.connection.commit()
        try:
            if self._cloud_service():
                self._cloud_service().delete_stored_product_remote(str(mat_num))
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            self.last_error = str(exc)
            logger.warning(
                "Remote stored-product deletion deferred for later synchronization: %s",
                exc,
            )
        try:
            self._stored_name_cache.pop(str(mat_num).strip(), None)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "DatabaseTrackingCatalogMixin.delete_stored_product fallback failed",
                exc_info=True,
            )


from datetime import datetime
from runtime.shared.settings.config import _



class TrackingCommandRepositoryMixin:

    def _delete_cloud_tracked_product(
        self, branch: str, doc_id: str, cache_id: str, *, silent: bool = False
    ) -> bool:
        if not self._valid_cloud_doc_id(doc_id):
            return self._missing_cloud_doc_id_error(silent=silent)
        try:
            self._cloud_service().delete_item(branch=branch, doc_id=str(doc_id).strip())
            self._cloud_cache_by_id.pop(cache_id, None)
            self._delete_persisted_cloud_tracking_record(doc_id, branch)
            self.invalidate_cloud_cache(branch)
            return self._show_success(_("Food item deleted."), silent=silent)
        except SERVICE_OPERATION_EXCEPTIONS as e:
            return self._show_cloud_operation_error(e, silent=silent)

    def _delete_local_tracked_product(self, pid, *, silent: bool = False) -> bool:
        c = self.connection.cursor()
        c.execute("DELETE FROM tracked_products WHERE id=?", (pid,))
        self.connection.commit()
        return self._show_success(_("Food item deleted."), silent=silent)

    def _update_cloud_tracked_product(
        self,
        branch: str,
        doc_id: str,
        cache_id: str,
        *,
        qty: int,
        prod_date: str,
        exp_date: str,
        silent: bool = False,
    ) -> bool:
        if self._valid_cloud_doc_id(doc_id):
            rec = self._cloud_cache_by_id.get(cache_id) or {}
        else:
            return self._missing_cloud_doc_id_error(silent=silent)
        material = str(rec.get("material_number", "")).strip()
        if not material:
            return self._show_error(
                _("Food item was not found. Refresh shelf-life data and try again."),
                silent=silent,
            )
        try:
            self._cloud_service().update_item(
                branch=branch,
                doc_id=str(doc_id).strip(),
                material_number=material,
                quantity=int(qty),
                production_date=str(prod_date),
                expiry_date=str(exp_date),
            )
            rec.update(
                {
                    "doc_id": doc_id,
                    "material_number": material,
                    "quantity": int(qty),
                    "production_date": str(prod_date),
                    "expiry_date": str(exp_date),
                    "branch": branch,
                }
            )
            self._cache_cloud_record(rec)
            self._persist_cloud_tracking_records([rec])
            self.invalidate_cloud_cache(branch)
            return self._show_success(_("Food item updated."), silent=silent)
        except SERVICE_OPERATION_EXCEPTIONS as e:
            return self._show_cloud_operation_error(e, silent=silent)

    def _update_local_tracked_product(
        self, pid, *, qty: int, prod_date: str, exp_date: str, silent: bool = False
    ) -> bool:
        c = self.connection.cursor()
        c.execute(
            "UPDATE tracked_products SET quantity=?, production_date=?, expiry_date=? WHERE id=?",
            (qty, prod_date, exp_date, pid),
        )
        self.connection.commit()
        return self._show_success(_("Food item updated."), silent=silent)

    def add_tracked_product(
        self, mat_num: str, qty: int, prod_date: str, exp_date: str, name_: str = ""
    ):
        self.last_message = ""
        self.last_error = ""
        if self._cloud_service():
            branch = self._pick_branch_for_write()
            doc = self._cloud_service().add_item(
                branch=branch,
                material_number=str(mat_num),
                material_name=str(name_ or mat_num),
                quantity=int(qty),
                production_date=str(prod_date),
                expiry_date=str(exp_date),
            )
            doc_id = str(doc.get("doc_id") or "")
            if doc_id:
                rec = self._cache_cloud_record(
                    {
                        "doc_id": doc_id,
                        "material_number": str(mat_num),
                        "name": str(name_ or mat_num),
                        "quantity": int(qty),
                        "production_date": str(prod_date),
                        "expiry_date": str(exp_date),
                        "branch": branch,
                    }
                )
                self._persist_cloud_tracking_records([rec])
            self.invalidate_cloud_cache(branch)
            self.last_message = "Food item added."
            return
        now_str = datetime.now().strftime("%Y-%m-%d")
        c = self.connection.cursor()
        c.execute(
            "\n                INSERT INTO tracked_products(material_number,quantity,production_date,expiry_date,created_at)\n                VALUES(?,?,?,?,?)\n            ",
            (mat_num, qty, prod_date, exp_date, now_str),
        )
        self.connection.commit()
        self.last_message = "Food item added."

    def _modify_cloud_tracked_product(
        self,
        operation: str,
        pid,
        qty=None,
        prod_date=None,
        exp_date=None,
        *,
        silent: bool = False,
    ) -> bool:
        pid_str = str(pid or "").strip()
        bid, doc_id = self._split_cloud_id(pid_str)
        if not self._require_cloud_doc_id(doc_id, silent=silent):
            return False
        try:
            branch = bid or self._pick_branch_for_write()
        except SERVICE_OPERATION_EXCEPTIONS as e:
            self.last_error = str(e)
            return self._show_error(str(e), silent=silent)
        cache_id = self._cloud_cache_key(branch, doc_id)
        if operation == "delete":
            return self._delete_cloud_tracked_product(
                branch, doc_id, cache_id, silent=silent
            )
        if operation == "update":
            is_valid, parsed_qty = self._validate_tracking_update(
                qty, prod_date, exp_date, silent=silent
            )
            if not is_valid:
                return bool(parsed_qty)
            return self._update_cloud_tracked_product(
                branch,
                doc_id,
                cache_id,
                qty=int(parsed_qty),
                prod_date=str(prod_date),
                exp_date=str(exp_date),
                silent=silent,
            )
        return self._show_error(_("Unknown operation."), silent=silent)

    def _modify_local_tracked_product(
        self,
        operation: str,
        pid,
        qty=None,
        prod_date=None,
        exp_date=None,
        *,
        silent: bool = False,
    ) -> bool:
        if not self._local_tracked_product_exists(pid):
            return self._show_error(_("Food item was not found."), silent=silent)
        if operation == "delete":
            return self._delete_local_tracked_product(pid, silent=silent)
        if operation == "update":
            is_valid, parsed_qty = self._validate_tracking_update(
                qty, prod_date, exp_date, silent=silent
            )
            if not is_valid:
                return bool(parsed_qty)
            return self._update_local_tracked_product(
                pid,
                qty=int(parsed_qty),
                prod_date=str(prod_date),
                exp_date=str(exp_date),
                silent=silent,
            )
        return self._show_error(_("Unknown operation."), silent=silent)

    def modify_tracked_product(
        self,
        operation: str,
        pid,
        qty=None,
        prod_date=None,
        exp_date=None,
        *,
        silent: bool = False,
    ) -> bool:
        self.last_message = ""
        self.last_error = ""
        op = str(operation or "").lower().strip()
        if self._cloud_service():
            return self._modify_cloud_tracked_product(
                op, pid, qty, prod_date, exp_date, silent=silent
            )
        return self._modify_local_tracked_product(
            op, pid, qty, prod_date, exp_date, silent=silent
        )


from runtime.domain.remote_ids import normalize_remote_id
from runtime.domain.tracking_rows import deduplicate_tracking_records
import sqlite3
import threading
import time



class TrackingQueryRepositoryMixin:

    def fetch_tracked_products(self, branch_filter_override: str | None = None):
        if self._cloud_service():
            logger.info(
                "Fetching tracked products from cloud, branch_filter: %s",
                branch_filter_override,
            )
            try:
                self.refresh_stored_products_from_cloud()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug("Stored product cloud refresh failed", exc_info=True)
            if not getattr(self, "_stored_name_cache", None):
                try:
                    self.fetch_stored_products()
                except SERVICE_OPERATION_EXCEPTIONS:
                    logger.debug("Stored product cache preload failed", exc_info=True)
            allowed_branches = [
                str(b).strip() for b in self.allowed_branches() or [] if str(b).strip()
            ]
            allowed_branch_keys = {b.lower() for b in allowed_branches}
            can_view_all = bool(self.can_view_all_branches())
            branch_filter_raw = (
                branch_filter_override
                if branch_filter_override is not None
                else self.get_active_branch()
            )
            branch_filter_raw = str(branch_filter_raw or "").strip()
            cache_key = branch_filter_raw.lower() if branch_filter_raw else ""
            if not can_view_all:
                if not allowed_branch_keys:
                    logger.warning(
                        "Tracked-product read blocked because the authenticated scope has no branches"
                    )
                    return []
                if cache_key in {"", "all"}:
                    cache_key = "scope_all"
                elif cache_key not in allowed_branch_keys:
                    logger.warning(
                        "Tracked-product read blocked for a branch outside the authenticated scope"
                    )
                    return []

            def _scoped_rows(rows):
                copied = deduplicate_tracking_records(rows)
                if can_view_all:
                    return copied
                return [
                    row
                    for row in copied
                    if str(row.get("branch") or "").strip().lower()
                    in allowed_branch_keys
                ]

            now = time.monotonic()
            if cache_key in self._cloud_list_cache:
                ts, cached_out = self._cloud_list_cache[cache_key]
                if now - ts <= self.cloud_list_cache_ttl_seconds:
                    logger.info(
                        "Returning cached tracked products (%s items)", len(cached_out)
                    )
                    return _scoped_rows(cached_out)
            persisted_rows = self._load_persisted_cloud_tracking_records(cache_key)
            if persisted_rows:
                logger.info(
                    "Returning persisted tracked baseline (%s items)",
                    len(persisted_rows),
                )
                return _scoped_rows(persisted_rows)
            try:
                saved_cursor = int(self.get_setting("server_sync_cursor", "0") or 0)
            except (TypeError, ValueError, *SERVICE_OPERATION_EXCEPTIONS):
                saved_cursor = 0
            try:
                baseline_loaded = str(
                    self.get_setting("cloud_tracking_baseline_loaded", "0") or "0"
                ).strip().lower() in {"1", "true", "yes", "on"}
            except SERVICE_OPERATION_EXCEPTIONS:
                baseline_loaded = False
            if saved_cursor > 0 and baseline_loaded:
                logger.info(
                    "Returning empty persisted tracking baseline; no broad server refresh requested"
                )
                self._cloud_list_cache[cache_key] = (now, [])
                return []
            loader_event = None
            should_load = False
            with self._db_lock:
                loader_event = self._tracking_fetch_events.get(cache_key)
                if loader_event is None:
                    loader_event = threading.Event()
                    self._tracking_fetch_events[cache_key] = loader_event
                    should_load = True
            if not should_load:
                self._wait_for_cloud_tracking_fetch(loader_event)
                cached = self._cloud_list_cache.get(cache_key)
                if cached is not None:
                    _, cached_out = cached
                    logger.info(
                        "Returning coalesced tracked products (%s items)",
                        len(cached_out),
                    )
                    return _scoped_rows(cached_out)
                snapshot_rows = [
                    row
                    for row in self._cloud_cache_by_id.values()
                    if cache_key in ("", "all")
                    or (
                        cache_key == "scope_all"
                        and str(row.get("branch") or "").strip().lower()
                        in allowed_branch_keys
                    )
                    or str(row.get("branch") or "").strip().lower() == cache_key
                ]
                if snapshot_rows:
                    logger.info(
                        "Returning in-memory tracked snapshot (%s items)",
                        len(snapshot_rows),
                    )
                    return _scoped_rows(snapshot_rows)
                try:
                    local_rows = self.fetch_tracked_products_local_newconn()
                except SERVICE_OPERATION_EXCEPTIONS:
                    local_rows = []
                if local_rows:
                    logger.info(
                        "Returning local tracked products while cloud fetch is in flight"
                    )
                    return _scoped_rows(local_rows)
                logger.debug(
                    "Skipped duplicate cloud tracking fetch while another worker is loading"
                )
                return []
            try:
                try:
                    if cache_key in {"all", "scope_all"} and allowed_branches:
                        items = []
                        seen: set[str] = set()
                        for branch_name in allowed_branches:
                            branch_items = self._cloud_service().list_items(
                                branch_filter=self._resolve_branch_case(branch_name)
                            )
                            for item in branch_items:
                                if not isinstance(item, dict):
                                    continue
                                doc_id = normalize_remote_id(item)
                                branch_value = normalize_text(
                                    item.get("branch")
                                    or item.get("branch_id")
                                    or branch_name
                                )
                                key = f"{branch_value.lower()}::{doc_id or id(item)}"
                                if key in seen:
                                    continue
                                seen.add(key)
                                items.append(item)
                    else:
                        if cache_key in ("", "all"):
                            branch_filter_for_service = None
                        else:
                            branch_filter_for_service = self._resolve_branch_case(
                                branch_filter_raw
                            )
                        items = self._cloud_service().list_items(
                            branch_filter=branch_filter_for_service
                        )
                    logger.info("Fetched %s items from cloud", len(items))
                except SERVICE_OPERATION_EXCEPTIONS as e:
                    logger.error("Error fetching tracked products from cloud: %s", e)
                    if cache_key in self._cloud_list_cache:
                        _, cached_out = self._cloud_list_cache[cache_key]
                        logger.info(
                            "Returning stale cache due to error (%s items)",
                            len(cached_out),
                        )
                        return _scoped_rows(cached_out)
                    raise
                out: list[dict] = []
                for d in items:
                    rec = self._cache_cloud_record(self._cloud_record_from_item(d))
                    branch_value = str(rec.get("branch") or "").strip().lower()
                    if not can_view_all and branch_value not in allowed_branch_keys:
                        continue
                    if (
                        cache_key not in {"", "all", "scope_all"}
                        and branch_value != cache_key
                    ):
                        continue
                    out.append(rec)
                out = deduplicate_tracking_records(out)
                self._persist_cloud_tracking_records(out)
                self._cloud_list_cache[cache_key] = (time.monotonic(), out)
                logger.info(
                    "Cached %s tracked products for key: %s", len(out), cache_key
                )
                return _scoped_rows(out)
            finally:
                with self._db_lock:
                    event = self._tracking_fetch_events.pop(cache_key, None)
                    if event is not None:
                        event.set()
        c = self.connection.cursor()
        c.execute(
            "\n                SELECT tp.id, tp.material_number, tp.quantity,\n                       tp.production_date, tp.expiry_date, tp.created_at,\n                       sp.name\n                FROM tracked_products tp\n                JOIN stored_products sp ON tp.material_number = sp.material_number\n            "
        )
        return [dict(r) for r in c.fetchall()]

    def fetch_tracked_products_local_newconn(self):
        connector = getattr(self, "_fresh_connection", None)
        if callable(connector):
            conn = connector.__call__()
        else:
            conn = sqlite3.connect(self.db_path, timeout=90.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            c = conn.cursor()
            c.execute(
                "\n                    SELECT tp.id, tp.material_number, tp.quantity,\n                           tp.production_date, tp.expiry_date, tp.created_at,\n                           sp.name\n                    FROM tracked_products tp\n                    JOIN stored_products sp ON tp.material_number = sp.material_number\n                    "
            )
            return [dict(r) for r in c.fetchall()]
        finally:
            try:
                conn.close()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug(
                    "DatabaseTrackingCatalogMixin.fetch_tracked_products_local_newconn fallback failed",
                    exc_info=True,
                )


from typing import Any



def clean_tracking_error_message(message: str) -> str:
    text = str(message or "").strip()
    if not text:
        return _("Operation failed.")
    lowered = text.lower()
    if "body.id" in lowered or "valid string" in lowered or "string_type" in lowered:
        return _("Server record id is missing. Refresh shelf-life data and try again.")
    if text.startswith(("[{", "{'", '{"')):
        return _("Server rejected the request. Refresh shelf-life data and try again.")
    return text


from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrackingUpdateValidation:
    ok: bool
    quantity: int | None = None
    error_message: str = ""
    dates_reversed: bool = False


def validate_tracking_update_fields(
    qty: Any, prod_date: Any, exp_date: Any
) -> TrackingUpdateValidation:
    try:
        parsed_qty = int(qty)
    except (TypeError, ValueError):
        parsed_qty = 0
    if parsed_qty <= 0:
        return TrackingUpdateValidation(
            ok=False, error_message=_("Quantity must be a positive integer.")
        )
    if not prod_date or not exp_date:
        return TrackingUpdateValidation(
            ok=False, error_message=_("Production and expiry dates are required.")
        )
    try:
        prod = datetime.strptime(str(prod_date), "%Y-%m-%d").date()
        exp = datetime.strptime(str(exp_date), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return TrackingUpdateValidation(
            ok=False, error_message=_("Invalid date format!")
        )
    return TrackingUpdateValidation(
        ok=True, quantity=parsed_qty, dates_reversed=prod > exp
    )


from runtime.shared.concurrency import wait_for_inflight_event



class TrackingFeedbackMixin:

    def _wait_for_cloud_tracking_fetch(self, loader_event) -> None:
        wait_for_inflight_event(
            loader_event,
            timeout_seconds=max(
                5.0, min(15.0, float(self.cloud_list_cache_ttl_seconds) / 8.0)
            ),
            logger_=logger,
            context="DatabaseTrackingCatalogMixin.fetch_tracked_products",
        )

    def _feedback_handler(self, key: str):
        handlers = getattr(self, "_ui_feedback_handlers", None)
        if isinstance(handlers, dict):
            callback = handlers.get(str(key or "").strip())
            if callable(callback):
                return callback
        return None

    def _notify_error(
        self, title: str, message: str, *, critical: bool = False
    ) -> None:
        callback = self._feedback_handler("error")
        if callback is not None:
            try:
                callback(title, message, critical=bool(critical))
                return
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.exception("Database error feedback callback failed")
        logger.error("%s: %s", title, message)

    def _notify_info(self, title: str, message: str) -> None:
        callback = self._feedback_handler("info")
        if callback is not None:
            try:
                callback(title, message)
                return
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.exception("Database info feedback callback failed")
        logger.info("%s: %s", title, message)

    def _confirm_action(self, title: str, message: str) -> bool:
        callback = self._feedback_handler("confirm")
        if callback is not None:
            try:
                return bool(callback(title, message))
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.exception("Database confirmation callback failed")
        return False

    def _show_error(
        self, message: str, *, critical: bool = False, silent: bool = False
    ) -> bool:
        self.last_error = str(message or "").strip()
        if silent:
            return False
        self._notify_error(_("Error"), self.last_error, critical=critical)
        return False

    def _clean_user_error(self, message: str) -> str:
        return clean_tracking_error_message(message)

    def _show_cloud_operation_error(
        self, exc: Exception, *, silent: bool = False
    ) -> bool:
        logger.exception("Cloud tracking operation failed")
        return self._show_error(
            self._clean_user_error(str(exc)), critical=True, silent=silent
        )

    def _show_success(self, message: str, *, silent: bool = False) -> bool:
        self.last_message = str(message or "").strip()
        if not silent:
            self._notify_info(_("Success"), self.last_message)
        return True

    def _confirm_invalid_date_order(self) -> bool:
        return self._confirm_action(
            _("Confirm date order"),
            _("Production date is after expiry date. Do you want to proceed?"),
        )

    def _local_tracked_product_exists(self, pid) -> bool:
        c = self.connection.cursor()
        c.execute("SELECT 1 FROM tracked_products WHERE id=?", (pid,))
        return bool(c.fetchone())

    def _validate_tracking_update(
        self, qty=None, prod_date=None, exp_date=None, *, silent: bool = False
    ) -> tuple[bool, int | None]:
        validation = validate_tracking_update_fields(qty, prod_date, exp_date)
        if not validation.ok:
            return (False, self._show_error(validation.error_message, silent=silent))
        if validation.dates_reversed and (not self._confirm_invalid_date_order()):
            return (False, False)
        return (True, validation.quantity)


from runtime.infrastructure.persistence import TrackingCacheRepositoryMixin



class DatabaseTrackingCatalogMixin(
    TrackingFeedbackMixin,
    TrackingCacheRepositoryMixin,
    TrackingCatalogRepositoryMixin,
    TrackingCommandRepositoryMixin,
    TrackingQueryRepositoryMixin,
):
    """Composition surface for tracking persistence responsibilities."""
