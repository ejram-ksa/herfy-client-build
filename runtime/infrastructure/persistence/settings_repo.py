from __future__ import annotations
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.objects import call_if_callable, safe_get

logger = logging.getLogger(__name__)
_SQLITE_LOCK_MARKERS = (
    "database is locked",
    "database table is locked",
    "database is busy",
    "locked",
)


def _is_sqlite_lock_error(exc: BaseException) -> bool:
    text = str(exc or "").lower()
    return any((marker in text for marker in _SQLITE_LOCK_MARKERS))


class DatabaseSettingsAlertMixin:

    def _run_sqlite_retry(self, action: Callable[[], Any], *, label: str) -> Any:
        main_thread = threading.current_thread() is threading.main_thread()
        attempts = 2 if main_thread else 40
        delay = 0.005 if main_thread else 0.04
        max_delay = 0.02 if main_thread else 1.25
        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                return action()
            except sqlite3.OperationalError as exc:
                if not _is_sqlite_lock_error(exc):
                    raise
                last_error = exc
                logger.warning(
                    "SQLite busy while %s; retry %s/%s",
                    label,
                    attempt,
                    attempts,
                    exc_info=True,
                )
                time.sleep(delay)
                delay = min(delay * 1.45, max_delay)
        if last_error is not None:
            raise last_error
        return None

    def _open_settings_connection(self):
        opener = getattr(self, "_fresh_connection", None)
        if not callable(opener):
            return self.connection
        return call_if_callable(opener)

    def _close_settings_connection(self, conn) -> None:
        if conn is not getattr(self, "connection", None):
            try:
                conn.close()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug("Closing settings connection failed", exc_info=True)

    def set_setting(self, key: str, value: str) -> None:
        setting_key = str(key or "").strip()
        if not setting_key:
            return

        def _write() -> None:
            lock = getattr(self, "_db_lock", None)
            if lock is not None:
                with lock:
                    return self._set_setting_once(setting_key, value)
            return self._set_setting_once(setting_key, value)

        try:
            self._run_sqlite_retry(_write, label=f"saving setting {setting_key}")
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.exception("Saving setting failed: %s", setting_key)

    def _set_setting_once(self, key: str, value: str) -> None:
        conn = self._open_settings_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                (str(key), str(value or "")),
            )
            conn.commit()
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            try:
                conn.rollback()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug("Rollback failed while saving setting", exc_info=True)
            raise
        finally:
            self._close_settings_connection(conn)

    def get_setting(self, key: str, default=None):
        setting_key = str(key or "").strip()
        if not setting_key:
            return default

        def _read():
            conn = self._open_settings_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key=?", (setting_key,))
                row = cursor.fetchone()
                if row:
                    return safe_get(row, "value", default)
                return default
            finally:
                self._close_settings_connection(conn)

        try:
            return self._run_sqlite_retry(_read, label=f"reading setting {setting_key}")
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.exception("Reading setting failed: %s", setting_key)
            return default

    def get_alert_state(self, key: str) -> dict:
        alert_key = str(key or "")

        def _read():
            conn = self._open_settings_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT key, last_date, last_notified_at, last_seen_at, fingerprint, severity_rank, status_text, notify_count FROM alert_state WHERE key=?",
                    (alert_key,),
                )
                row = cursor.fetchone()
                return dict(row) if row else {}
            finally:
                self._close_settings_connection(conn)

        try:
            return self._run_sqlite_retry(_read, label="reading alert state") or {}
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.exception("Reading alert state failed: %s", alert_key)
            return {}

    def set_alert_state(
        self,
        key: str,
        *,
        last_date: str = "",
        last_notified_at: float = 0.0,
        last_seen_at: float = 0.0,
        fingerprint: str = "",
        severity_rank: int = 0,
        status_text: str = "",
        notify_count: int = 0,
    ) -> None:
        alert_key = str(key or "")

        def _write() -> None:
            lock = getattr(self, "_db_lock", None)
            if lock is not None:
                with lock:
                    return self._set_alert_state_once(
                        alert_key,
                        last_date,
                        last_notified_at,
                        last_seen_at,
                        fingerprint,
                        severity_rank,
                        status_text,
                        notify_count,
                    )
            return self._set_alert_state_once(
                alert_key,
                last_date,
                last_notified_at,
                last_seen_at,
                fingerprint,
                severity_rank,
                status_text,
                notify_count,
            )

        try:
            self._run_sqlite_retry(_write, label="saving alert state")
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.exception("Saving alert state failed: %s", alert_key)

    def _set_alert_state_once(
        self,
        key: str,
        last_date: str,
        last_notified_at: float,
        last_seen_at: float,
        fingerprint: str,
        severity_rank: int,
        status_text: str,
        notify_count: int,
    ) -> None:
        conn = self._open_settings_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "\n                INSERT INTO alert_state(\n                    key, last_date, last_notified_at, last_seen_at,\n                    fingerprint, severity_rank, status_text, notify_count\n                )\n                VALUES(?,?,?,?,?,?,?,?)\n                ON CONFLICT(key) DO UPDATE SET\n                  last_date=excluded.last_date,\n                  last_notified_at=excluded.last_notified_at,\n                  last_seen_at=excluded.last_seen_at,\n                  fingerprint=excluded.fingerprint,\n                  severity_rank=excluded.severity_rank,\n                  status_text=excluded.status_text,\n                  notify_count=excluded.notify_count\n                ",
                (
                    str(key or ""),
                    str(last_date or ""),
                    float(last_notified_at or 0.0),
                    float(last_seen_at or 0.0),
                    str(fingerprint or ""),
                    int(severity_rank or 0),
                    str(status_text or ""),
                    int(notify_count or 0),
                ),
            )
            conn.commit()
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            try:
                conn.rollback()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug("Rollback failed while saving alert state", exc_info=True)
            raise
        finally:
            self._close_settings_connection(conn)

    def get_notification_ledger(self, key: str) -> dict:
        ledger_key = str(key or "")

        def _read():
            conn = self._open_settings_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT notification_key, state, severity, last_shown_at,
                           last_payload_hash, shown_count, acknowledged_at
                    FROM notification_ledger
                    WHERE notification_key=?
                    """,
                    (ledger_key,),
                )
                row = cursor.fetchone()
                return dict(row) if row else {}
            finally:
                self._close_settings_connection(conn)

        try:
            return (
                self._run_sqlite_retry(_read, label="reading notification ledger") or {}
            )
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.exception("Reading notification ledger failed: %s", ledger_key)
            return {}

    def record_notification_ledger(
        self,
        key: str,
        *,
        state: str,
        severity: int,
        payload_hash: str,
        acknowledged_at: str = "",
    ) -> None:
        ledger_key = str(key or "")
        shown_at = datetime.now(timezone.utc).isoformat()

        def _write() -> None:
            lock = getattr(self, "_db_lock", None)
            if lock is not None:
                with lock:
                    return self._record_notification_ledger_once(
                        ledger_key,
                        state,
                        severity,
                        payload_hash,
                        shown_at,
                        acknowledged_at,
                    )
            return self._record_notification_ledger_once(
                ledger_key,
                state,
                severity,
                payload_hash,
                shown_at,
                acknowledged_at,
            )

        try:
            self._run_sqlite_retry(_write, label="saving notification ledger")
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.exception("Saving notification ledger failed: %s", ledger_key)

    def _record_notification_ledger_once(
        self,
        key: str,
        state: str,
        severity: int,
        payload_hash: str,
        shown_at: str,
        acknowledged_at: str,
    ) -> None:
        conn = self._open_settings_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO notification_ledger(
                  notification_key, state, severity, last_shown_at,
                  last_payload_hash, shown_count, acknowledged_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(notification_key) DO UPDATE SET
                  state=excluded.state,
                  severity=excluded.severity,
                  last_shown_at=excluded.last_shown_at,
                  last_payload_hash=excluded.last_payload_hash,
                  shown_count=notification_ledger.shown_count + 1,
                  acknowledged_at=excluded.acknowledged_at
                """,
                (
                    str(key or ""),
                    str(state or ""),
                    int(severity or 0),
                    str(shown_at or ""),
                    str(payload_hash or ""),
                    1,
                    str(acknowledged_at or ""),
                ),
            )
            conn.commit()
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            try:
                conn.rollback()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug(
                    "Rollback failed while saving notification ledger",
                    exc_info=True,
                )
            raise
        finally:
            self._close_settings_connection(conn)

    def clear_alert_states(self) -> None:

        def _write() -> None:
            lock = getattr(self, "_db_lock", None)
            if lock is not None:
                with lock:
                    return self._clear_alert_states_once()
            return self._clear_alert_states_once()

        try:
            self._run_sqlite_retry(_write, label="clearing alert states")
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            logger.exception("Clearing alert states failed")

    def _clear_alert_states_once(self) -> None:
        conn = self._open_settings_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM alert_state")
            conn.commit()
        except (sqlite3.Error, *SERVICE_OPERATION_EXCEPTIONS):
            try:
                conn.rollback()
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.debug(
                    "Rollback failed while clearing alert states", exc_info=True
                )
            raise
        finally:
            self._close_settings_connection(conn)
