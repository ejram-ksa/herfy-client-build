from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

import logging
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.booleans import parse_bool

logger = logging.getLogger(__name__)


class DatabaseDefaultsMixin:

    def _apply_threshold_notification_migration_once(self) -> None:
        try:
            marker = self.get_setting("threshold_notification_state_initialized", "")
            if parse_bool(marker, False):
                return
            self.clear_alert_states()
            self.set_setting("threshold_notification_state_initialized", "True")
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "Threshold notification state initialization failed", exc_info=True
            )

    def ensure_default_settings(self):
        defaults = {
            "date_format": "yyyy-MM-dd",
            "language": "ar",
            "enable_alerts": "True",
            "enable_tray_background": "True",
            "enable_desktop_notifications": "True",
            "enable_smart_notifications": "True",
            "enable_sounds": "True",
            "expiry_expiring_soon_threshold_days": "7",
            "expiry_critical_threshold_days": "2",
            "expiry_enable_status_colors": "True",
            "expiry_enable_status_icons": "True",
            "notification_once_per_day": "True",
            "notification_repeat_interval_minutes": "240",
            "notification_duration_seconds": "8",
            "notification_max_per_cycle": "5",
            "notification_summary_threshold": "3",
            "monitoring_active_check_interval_minutes": "15",
            "monitoring_background_check_interval_minutes": "30",
            "notification_sound_default": "default.wav",
            "notification_sound_expired": "expired.wav",
            "notification_sound_today": "expires_today.wav",
            "notification_sound_critical": "expiry_critical.wav",
            "notification_sound_soon": "expiry_soon.wav",
            "font_size": "10",
            "font": "Segoe UI",
            "start_with_windows": "False",
            "tray_show_message_on_minimize": "False",
            "usage_hide_total_zero": "False",
            "immediate_server_sync": "True",
        }
        installer_defaults_applied = False
        try:
            from runtime.application.services.installer_defaults import merge_installer_defaults

            merged_defaults = merge_installer_defaults(defaults)
            installer_defaults_applied = merged_defaults != defaults
            defaults = merged_defaults
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Installer defaults merge skipped", exc_info=True)
        for key, value in defaults.items():
            if not self.get_setting(key, None):
                self.set_setting(key, value)
        try:
            if installer_defaults_applied and (
                not self.get_setting("tray_settings_migrated_v2", None)
            ):
                self.set_setting("tray_settings_migrated_v2", "True")
            if not installer_defaults_applied and (
                not self.get_setting("tray_settings_migrated_v2", None)
            ):
                self.set_setting("enable_tray_background", "True")
                self.set_setting("tray_show_message_on_minimize", "False")
                self.set_setting("tray_settings_migrated_v2", "True")
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception("Failed to apply tray settings migration")


class UIFeedbackHandlersMixin:

    def set_ui_feedback_handlers(self, *, error=None, info=None, confirm=None):
        self._ui_feedback_handlers = {
            "error": error if callable(error) else None,
            "info": info if callable(info) else None,
            "confirm": confirm if callable(confirm) else None,
        }


import json
from datetime import datetime, timezone

from runtime.shared.objects import safe_get
from runtime.domain.tracking_rows import tracking_key_from_row


class DatabaseSchemaMixin:

    def create_tables(self):
        """Create tables."""
        c = self.connection.cursor()
        c.execute(
            "\n            CREATE TABLE IF NOT EXISTS stored_products(\n              material_number TEXT PRIMARY KEY,\n              name TEXT NOT NULL\n            )\n        "
        )
        c.execute(
            "\n            CREATE TABLE IF NOT EXISTS tracked_products(\n              id INTEGER PRIMARY KEY AUTOINCREMENT,\n              material_number TEXT NOT NULL,\n              quantity INTEGER NOT NULL,\n              production_date TEXT NOT NULL,\n              expiry_date TEXT NOT NULL,\n              created_at TEXT,\n              FOREIGN KEY(material_number) REFERENCES stored_products(material_number) ON DELETE CASCADE\n            )\n        "
        )
        c.execute(
            "\n            CREATE TABLE IF NOT EXISTS settings(\n              key TEXT PRIMARY KEY,\n              value TEXT NOT NULL\n            )\n        "
        )
        c.execute(
            "\n            CREATE TABLE IF NOT EXISTS cloud_tracked_products(\n              id TEXT PRIMARY KEY,\n              branch TEXT DEFAULT '',\n              material_number TEXT DEFAULT '',\n              expiry_date TEXT DEFAULT '',\n              payload TEXT NOT NULL,\n              updated_at TEXT NOT NULL\n            )\n        "
        )
        c.execute(
            "\n            CREATE TABLE IF NOT EXISTS notify_log(\n              key TEXT PRIMARY KEY,\n              last_date TEXT NOT NULL\n            )\n        "
        )
        c.execute(
            "\n            CREATE TABLE IF NOT EXISTS alert_state(\n              key TEXT PRIMARY KEY,\n              last_date TEXT DEFAULT '',\n              last_notified_at REAL DEFAULT 0,\n              last_seen_at REAL DEFAULT 0,\n              fingerprint TEXT DEFAULT '',\n              severity_rank INTEGER DEFAULT 0,\n              status_text TEXT DEFAULT '',\n              notify_count INTEGER DEFAULT 0\n            )\n        "
        )
        c.execute("""
            CREATE TABLE IF NOT EXISTS tracking_records_v2 (
              logical_key TEXT PRIMARY KEY,
              branch_code TEXT NOT NULL,
              material_number TEXT NOT NULL,
              production_date TEXT,
              expiry_date TEXT NOT NULL,
              remote_id TEXT NOT NULL,
              product_name TEXT NOT NULL DEFAULT '',
              quantity INTEGER NOT NULL,
              revision INTEGER NOT NULL DEFAULT 0,
              payload_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """)
        c.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tracking_remote_id_v2
            ON tracking_records_v2(branch_code, remote_id)
            """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_tracking_scope_v2
            ON tracking_records_v2(branch_code, expiry_date)
            """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS tracking_sync_state (
              scope_hash TEXT PRIMARY KEY,
              revision INTEGER,
              last_success_at TEXT,
              last_error TEXT,
              session_subject TEXT
            )
            """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS tracking_remote_aliases (
              branch_code TEXT NOT NULL,
              old_remote_id TEXT NOT NULL,
              current_remote_id TEXT NOT NULL,
              logical_key TEXT NOT NULL,
              migrated_at TEXT NOT NULL,
              PRIMARY KEY(branch_code, old_remote_id)
            )
            """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS notification_ledger (
              notification_key TEXT PRIMARY KEY,
              state TEXT NOT NULL,
              severity INTEGER NOT NULL,
              last_shown_at TEXT,
              last_payload_hash TEXT,
              shown_count INTEGER NOT NULL DEFAULT 0,
              acknowledged_at TEXT
            )
            """)
        c.execute(
            "\n            CREATE TABLE IF NOT EXISTS usage_products(\n              material TEXT PRIMARY KEY,\n              name TEXT,\n              uom TEXT\n            )\n        "
        )
        c.execute(
            "\n            CREATE TABLE IF NOT EXISTS usage_products_pending(\n              id INTEGER PRIMARY KEY AUTOINCREMENT,\n              op TEXT NOT NULL,\n              material TEXT NOT NULL,\n              name TEXT DEFAULT '',\n              uom TEXT DEFAULT '',\n              created_at TEXT NOT NULL\n            )\n        "
        )
        c.execute("PRAGMA table_info(tracked_products)")
        cols = [safe_get(x, "name", "") for x in c.fetchall()]
        if "created_at" not in cols:
            c.execute("ALTER TABLE tracked_products ADD COLUMN created_at TEXT")
        self.connection.commit()
        self._migrate_tracking_records_v2_once()

    def _migrate_tracking_records_v2_once(self) -> None:
        marker = "tracking_records_v2_migrated_2_18_0"
        if parse_bool(self.get_setting(marker, ""), False):
            return
        conn = self.connection
        cursor = conn.cursor()
        migrated_at = datetime.now(timezone.utc).isoformat()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            rows = self._previous_tracking_rows_for_v2(cursor)
            selected: dict[str, dict] = {}
            aliases: list[tuple[str, str, str, str, str]] = []
            for row in rows:
                key = tracking_key_from_row(row)
                if key is None:
                    continue
                logical_key = self._tracking_logical_key_text(key)
                remote_id = str(
                    safe_get(row, "id", "")
                    or safe_get(row, "doc_id", "")
                    or safe_get(row, "tracking_id", "")
                    or logical_key
                ).strip()
                candidate = {
                    "logical_key": logical_key,
                    "branch_code": key.branch_code,
                    "material_number": key.material_number,
                    "production_date": (
                        key.production_date.isoformat() if key.production_date else None
                    ),
                    "expiry_date": key.expiry_date.isoformat(),
                    "remote_id": remote_id,
                    "product_name": str(
                        safe_get(row, "name", "")
                        or safe_get(row, "product_name", "")
                        or key.material_number
                    ).strip(),
                    "quantity": int(safe_get(row, "quantity", 0) or 0),
                    "revision": int(safe_get(row, "revision", 0) or 0),
                    "payload_json": json.dumps(dict(row), ensure_ascii=False),
                    "updated_at": str(
                        safe_get(row, "updated_at", "")
                        or safe_get(row, "created_at", "")
                        or migrated_at
                    ),
                }
                previous = selected.get(logical_key)
                if previous is not None and previous["remote_id"] != remote_id:
                    aliases.append(
                        (
                            key.branch_code,
                            str(previous["remote_id"]),
                            remote_id,
                            logical_key,
                            migrated_at,
                        )
                    )
                if previous is None or self._tracking_v2_newer(candidate, previous):
                    selected[logical_key] = candidate
            for item in selected.values():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO tracking_records_v2(
                      logical_key, branch_code, material_number, production_date,
                      expiry_date, remote_id, product_name, quantity, revision,
                      payload_json, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        item["logical_key"],
                        item["branch_code"],
                        item["material_number"],
                        item["production_date"],
                        item["expiry_date"],
                        item["remote_id"],
                        item["product_name"],
                        item["quantity"],
                        item["revision"],
                        item["payload_json"],
                        item["updated_at"],
                    ),
                )
            for alias in aliases:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO tracking_remote_aliases(
                      branch_code, old_remote_id, current_remote_id,
                      logical_key, migrated_at
                    ) VALUES(?,?,?,?,?)
                    """,
                    alias,
                )
            cursor.execute("SELECT COUNT(*) AS count FROM tracking_records_v2")
            inserted = int(safe_get(cursor.fetchone(), "count", 0) or 0)
            if inserted < len(selected):
                raise RuntimeError("tracking_records_v2 logical count mismatch")
            cursor.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                (marker, "True"),
            )
            conn.commit()
        except (Exception, *SERVICE_OPERATION_EXCEPTIONS):
            try:
                conn.rollback()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug(
                    "tracking_records_v2 migration rollback failed", exc_info=True
                )
            try:
                self._tracking_v2_readonly_degraded = True
                cursor.execute(
                    "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                    ("tracking_records_v2_degraded", "True"),
                )
                conn.commit()
            except (Exception, *SERVICE_OPERATION_EXCEPTIONS):
                logger.exception("tracking_records_v2 degraded marker failed")
            logger.exception("tracking_records_v2 migration failed")

    def _previous_tracking_rows_for_v2(self, cursor) -> list[dict]:
        rows: list[dict] = []
        cursor.execute("""
            SELECT
              id, '' AS branch, material_number, quantity, production_date,
              expiry_date, created_at, created_at AS updated_at, 0 AS revision
            FROM tracked_products
            ORDER BY COALESCE(created_at, '') DESC, id DESC
            """)
        rows.extend(dict(row) for row in cursor.fetchall())
        cursor.execute(
            "SELECT payload FROM cloud_tracked_products ORDER BY updated_at DESC"
        )
        for db_row in cursor.fetchall():
            try:
                payload = json.loads(str(safe_get(db_row, "payload", "") or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    @staticmethod
    def _tracking_logical_key_text(key) -> str:
        production = key.production_date.isoformat() if key.production_date else ""
        return "|".join(
            (
                key.branch_code,
                key.material_number,
                production,
                key.expiry_date.isoformat(),
            )
        )

    @staticmethod
    def _tracking_v2_newer(candidate: dict, previous: dict) -> bool:
        return (
            int(candidate.get("revision") or 0),
            str(candidate.get("updated_at") or ""),
        ) >= (
            int(previous.get("revision") or 0),
            str(previous.get("updated_at") or ""),
        )


class SerializedCursor:

    def __init__(self, cursor, lock):
        self._cursor = cursor
        self._lock = lock

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._cursor.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return self._cursor.executemany(*args, **kwargs)

    def fetchone(self, *args, **kwargs):
        with self._lock:
            return self._cursor.fetchone(*args, **kwargs)

    def fetchall(self, *args, **kwargs):
        with self._lock:
            return self._cursor.fetchall(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class SerializedConnection:

    def __init__(self, connection, lock):
        self._connection = connection
        self._lock = lock

    def cursor(self, *args, **kwargs):
        with self._lock:
            return SerializedCursor(
                self._connection.cursor(*args, **kwargs), self._lock
            )

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._connection.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return self._connection.executemany(*args, **kwargs)

    def commit(self):
        with self._lock:
            return self._connection.commit()

    def rollback(self):
        with self._lock:
            return self._connection.rollback()

    def close(self):
        with self._lock:
            return self._connection.close()

    def __getattr__(self, name):
        return getattr(self._connection, name)


import sqlite3
import threading
from collections.abc import Callable
from typing import Any
from runtime.shared.settings.config import db_file_path, get_cache_ttl
from runtime.infrastructure.persistence.cloud_repo_sections import DatabaseCloudContextMixin
from runtime.infrastructure.persistence.settings_repo import DatabaseSettingsAlertMixin
from runtime.infrastructure.persistence.tracking_repo_sections import DatabaseTrackingCatalogMixin
from runtime.infrastructure.persistence.usage_repo_sections import DatabaseUsageCatalogMixin
from runtime.domain.runtime_state import RuntimeStateCore



class LocalDataStore(
    DatabaseCloudContextMixin,
    DatabaseTrackingCatalogMixin,
    DatabaseUsageCatalogMixin,
    DatabaseSettingsAlertMixin,
    DatabaseSchemaMixin,
    DatabaseDefaultsMixin,
    UIFeedbackHandlersMixin,
):

    def __init__(self, app_state: Any | None = None):
        self.app_state = app_state or RuntimeStateCore()
        self.db_path = db_file_path()
        self.connection = None
        self._db_lock = threading.RLock()
        self._allowed_branches: list[str] = []
        self._active_branch: str = ""
        self._cloud_cache_by_id: dict[str, dict] = {}
        self._stored_name_cache: dict[str, str] = {}
        self._cloud_list_cache: dict[str, tuple[float, list[dict]]] = {}
        self._tracking_fetch_events: dict[str, threading.Event] = {}
        self._usage_refresh_event: threading.Event | None = None
        self._usage_refresh_result: list[dict[str, Any]] | None = None
        self._usage_refresh_started_at: float = 0.0
        self.cloud_list_cache_ttl_seconds = int(get_cache_ttl().catalog)
        self.last_message: str = ""
        self.last_error: str = ""
        self._ui_feedback_handlers: dict[str, Callable[..., Any] | None] = {
            "error": None,
            "info": None,
            "confirm": None,
        }
        self.connect()
        self.create_tables()
        self.ensure_default_settings()
        self._apply_threshold_notification_migration_once()

    def connect(self):
        raw_connection = sqlite3.connect(
            self.db_path, timeout=90.0, check_same_thread=False, isolation_level=None
        )
        raw_connection.row_factory = sqlite3.Row
        raw_connection.execute("PRAGMA foreign_keys=ON")
        raw_connection.execute("PRAGMA busy_timeout=60000")
        raw_connection.execute("PRAGMA journal_mode=WAL")
        raw_connection.execute("PRAGMA synchronous=NORMAL")
        raw_connection.execute("PRAGMA wal_autocheckpoint=500")
        raw_connection.execute("PRAGMA temp_store=MEMORY")
        raw_connection.execute("PRAGMA locking_mode=NORMAL")
        self.connection = SerializedConnection(raw_connection, self._db_lock)

    def _fresh_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=90.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA wal_autocheckpoint=500")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA locking_mode=NORMAL")
        return conn

    def close(self):
        try:
            if self.connection:
                self.connection.close()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("LocalDataStore.close fallback failed", exc_info=True)


# --- package exports ---
__all__ = ["SerializedConnection", "SerializedCursor", "LocalDataStore"]
_SerializedCursor = SerializedCursor
_SerializedConnection = SerializedConnection
