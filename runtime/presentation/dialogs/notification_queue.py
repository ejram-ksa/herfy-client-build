from __future__ import annotations
import logging
from collections import deque
from collections.abc import Callable
from typing import Any
from PyQt5.QtCore import QTimer
from runtime.shared.settings.config import _, APP_DISPLAY_NAME
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS, UI_OPERATION_EXCEPTIONS
from runtime.shared.objects import normalize_int
from runtime.presentation.notifications import NotificationMessageFormatter

logger = logging.getLogger(__name__)


class DesktopNotificationQueue:
    """Qt delivery queue only; payload text formatting lives in runtime.presentation."""

    def __init__(
        self,
        main_window: Any,
        *,
        get_bool: Callable[[str, bool], bool],
        show_tray_message: Callable[[str, str, int], bool],
        play_sound: Callable[[dict], None],
        show_card_notification: Callable[[str, dict | None, int], bool] | None = None,
        max_queue_size: int = 50,
    ) -> None:
        self.main_window = main_window
        self._get_bool = get_bool
        self._show_tray_message = show_tray_message
        self._show_card_notification = show_card_notification
        self._play_sound = play_sound
        self._queue = deque()
        self._busy = False
        self._max_queue_size = int(max_queue_size)
        self._formatter = NotificationMessageFormatter()
        self._timer = QTimer(self.main_window)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.drain)

    def enqueue(
        self,
        *,
        title: str,
        message: str,
        duration_s: int,
        status: str = "",
        entry: dict | None = None,
    ) -> None:
        self._queue.append(
            self._build_payload(
                title=title,
                message=message,
                duration_s=duration_s,
                status=status,
                entry=entry,
            )
        )
        while len(self._queue) > self._max_queue_size:
            try:
                self._queue.popleft()
            except SERVICE_OPERATION_EXCEPTIONS:
                break
        self.schedule(0)

    def schedule(self, delay_ms: int = 0) -> None:
        try:
            delay_ms = max(0, int(delay_ms))
            if self._timer.isActive():
                return
            self._timer.start(max(10, delay_ms))
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception("Failed to schedule desktop notifications")

    def _build_payload(
        self,
        *,
        title: str,
        message: str,
        duration_s: int,
        status: str = "",
        entry: dict | None = None,
    ) -> dict:
        payload = {
            "title": str(title or _("Notification")),
            "app_title": APP_DISPLAY_NAME,
            "message": str(message or "").strip(),
            "duration_s": max(4, int(duration_s or 4)),
            "status": str(status or "").strip(),
        }
        if entry:
            payload.update(
                {
                    key: value
                    for key, value in dict(entry).items()
                    if value not in (None, "")
                }
            )
        return payload

    def _take_dispatch_batch(self) -> list[dict]:
        first = self._queue.popleft()
        batch = [first]
        while self._queue and len(batch) < 12:
            batch.append(self._queue.popleft())
        batch.sort(key=self._formatter.severity_rank, reverse=True)
        return batch

    def clear(self) -> None:
        try:
            self._queue.clear()
            self._busy = False
            if self._timer.isActive():
                self._timer.stop()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception("Failed to clear desktop notification queue")

    def drain(self) -> None:
        if self._busy or not self._queue:
            return
        self._busy = True
        duration_s = 4
        try:
            batch = self._take_dispatch_batch()
            payload = batch[0]
            duration_s = max(4, min(60, normalize_int(payload.get("duration_s"), 4)))
            if len(batch) > 1:
                title = _("Products expiration tracking")
                message = self._formatter.format_summary_message(batch)
                card_payload = {
                    "title": title,
                    "message": message,
                    "is_summary": True,
                    "items_count": len(batch),
                    "status_kind": payload.get("status_kind")
                    or payload.get("kind")
                    or "",
                    "severity_rank": payload.get("severity_rank"),
                    "source": payload.get("source") or "local",
                }
            else:
                title = str(payload.get("title") or _("Notification"))
                if (
                    payload.get("product")
                    or payload.get("branch")
                    or payload.get("status_kind")
                ):
                    title = _("Products expiration tracking")
                message = self._formatter.format_message(payload)
                card_payload = dict(payload)
                card_payload["message"] = message
            if self._get_bool("enable_desktop_notifications", True):
                shown = self._show_tray_message(title, message, duration_s)
                if not shown and callable(self._show_card_notification):
                    self._show_card_notification(title, card_payload, duration_s)
            self._play_sound(
                {
                    "status_kind": payload.get("status_kind")
                    or payload.get("kind")
                    or "",
                    "severity_rank": payload.get("severity_rank"),
                    "status": payload.get("status")
                    or payload.get("status_label")
                    or "",
                }
            )
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception("Notification queue dispatch failed")
        finally:
            self._busy = False
            if self._queue:
                self._timer.start(max(900, min(duration_s * 1000 + 500, 2800)))

    def close(self) -> None:
        try:
            self._queue.clear()
            self._busy = False
            if self._timer.isActive():
                self._timer.stop()
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Notification queue shutdown failed", exc_info=True)
