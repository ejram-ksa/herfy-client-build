from __future__ import annotations
import logging
from collections.abc import Callable
from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtWidgets import QApplication
from runtime.shared.signals import safe_disconnect

logger = logging.getLogger(__name__)


class SyncManager(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timers: dict[str, QTimer] = {}

    def _timer_parent(self) -> QObject:
        app = QApplication.instance()
        parent_obj = self.parent()
        if (
            app is not None
            and isinstance(parent_obj, QObject)
            and (parent_obj.thread() == app.thread())
        ):
            return parent_obj
        return self

    def schedule(
        self, key: str, callback: Callable[[], None] | None, delay_ms: int = 350
    ) -> None:
        if not callable(callback):
            return
        timer = self._timers.get(key)
        if timer is None:
            timer = QTimer(self._timer_parent())
            timer.setSingleShot(True)
            self._timers[key] = timer
        else:
            safe_disconnect(
                timer.timeout,
                logger_=logger,
                context="Timer disconnect during reschedule",
            )
        timer.timeout.connect(callback)
        timer.start(max(50, int(delay_ms)))

    def cancel(self, key: str) -> None:
        timer = self._timers.get(key)
        if timer is not None:
            timer.stop()

    def cancel_all(self) -> None:
        for timer in list(self._timers.values()):
            try:
                timer.stop()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("SyncManager timer stop failed", exc_info=True)

    def shutdown(self) -> None:
        for key, timer in list(self._timers.items()):
            try:
                timer.stop()
                safe_disconnect(
                    timer.timeout,
                    logger_=logger,
                    context=f"SyncManager shutdown disconnect: {key}",
                )
                timer.deleteLater()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("SyncManager shutdown failed for %s", key, exc_info=True)
        self._timers.clear()
