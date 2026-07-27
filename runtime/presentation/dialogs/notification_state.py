from __future__ import annotations
import logging
import threading
import time
from typing import Any
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.application.services.notifications import NotificationEngine

logger = logging.getLogger(__name__)


class NotificationDuplicateGuard:

    def __init__(self, *, stale_after_seconds: float = 900.0) -> None:
        self._recent_messages: dict[str, float] = {}
        self._lock = threading.RLock()
        self._stale_after_seconds = max(1.0, float(stale_after_seconds))

    def prune(self) -> None:
        cutoff = time.monotonic() - self._stale_after_seconds
        with self._lock:
            stale = [key for key, ts in self._recent_messages.items() if ts < cutoff]
            for key in stale:
                self._recent_messages.pop(key, None)

    def mark_recent(self, key: str, *, ttl_seconds: float = 60.0) -> bool:
        key = str(key or "").strip().lower()
        if not key:
            return True
        now = time.monotonic()
        self.prune()
        with self._lock:
            last = self._recent_messages.get(key, 0.0)
            if now - last < max(1.0, float(ttl_seconds)):
                return False
            self._recent_messages[key] = now
        return True

    def clear(self) -> None:
        with self._lock:
            self._recent_messages.clear()


class NotificationHistoryStore:

    def __init__(
        self, main_window: Any, engine: NotificationEngine, *, max_items: int = 500
    ) -> None:
        self.main_window = main_window
        self.engine = engine
        self.max_items = int(max_items)

    def history_key(self, entry: dict | None) -> str:
        return self.engine.history_key(entry)

    def record_entries(self, entries: list[dict]) -> bool:
        if not entries:
            return False
        mw = self.main_window
        try:
            existing = list(mw.notifications_list or [])
            existing_keys = {
                self.history_key(item) for item in existing if isinstance(item, dict)
            }
            for entry in reversed(entries):
                entry_key = self.history_key(entry)
                if not entry_key or entry_key not in existing_keys:
                    existing.insert(0, entry)
                    if entry_key:
                        existing_keys.add(entry_key)
            if len(existing) > self.max_items:
                del existing[self.max_items :]
            mw.notifications_list = existing
            return True
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception("Failed to record notification history")
            return False

    def clear_runtime_items(self) -> None:
        try:
            self.main_window.notifications_list = []
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception("Failed to clear notification history")
