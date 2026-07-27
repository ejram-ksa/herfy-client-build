from __future__ import annotations
import inspect
import logging
import os
import threading
from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS, UI_OPERATION_EXCEPTIONS

logger = logging.getLogger(__name__)


def client_thread_pool() -> QThreadPool:
    """Return the shared client thread pool with a safe bounded capacity.

    The client performs network pulls, catalog reads, expiry checks, and usage
    calculations from the UI.  Leaving the global QThreadPool unbounded on a
    large CPU machine can allow repeated refresh/realtime events to compete
    with user actions.  A small bounded pool keeps the UI responsive while
    preserving enough parallelism for background sync.
    """
    pool = QThreadPool.globalInstance()
    try:
        cpu_count = int(os.cpu_count() or 4)
    except (TypeError, ValueError):
        cpu_count = 4
    max_threads = max(4, min(6, cpu_count))
    try:
        if int(pool.maxThreadCount()) != max_threads:
            pool.setMaxThreadCount(max_threads)
        if hasattr(pool, "setExpiryTimeout"):
            pool.setExpiryTimeout(30000)
    except UI_OPERATION_EXCEPTIONS:
        logger.debug("Failed to configure bounded client QThreadPool", exc_info=True)
    return pool


class WorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    progress = pyqtSignal(object)


class Worker(QRunnable):

    def __init__(self, fn, *args, log_exceptions: bool = True, **kwargs):
        super().__init__()
        try:
            self.setAutoDelete(True)
        except UI_OPERATION_EXCEPTIONS:
            logger.debug("Worker auto-delete configuration skipped", exc_info=True)
        self._cancel_requested = False
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.log_exceptions = bool(log_exceptions)
        self.signals = WorkerSignals()

    @staticmethod
    def _supports_callback_argument(fn, argument_name: str) -> bool:
        """Return whether a worker function can accept a callback argument."""
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return False
        for param in signature.parameters.values():
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                return True
            if param.name == argument_name:
                return True
        return False

    def _emit_signal(self, signal_name: str, *args) -> bool:
        try:
            signal = getattr(self.signals, signal_name)
            signal.emit(*args)
            return True
        except UI_OPERATION_EXCEPTIONS:
            logger.debug(
                "Worker signal emission skipped after receiver cleanup: %s",
                signal_name,
                exc_info=True,
            )
            return False

    def cancel(self) -> None:
        """Request cooperative cancellation for long-running work."""
        self._cancel_requested = True

    def is_cancel_requested(self) -> bool:
        """Return whether cooperative cancellation was requested."""
        return bool(getattr(self, "_cancel_requested", False))

    def _progress_callback(self, message) -> None:
        """Emit progress only while the worker is still current."""
        if self.is_cancel_requested():
            return
        self._emit_signal("progress", message)

    def run(self):
        try:
            kwargs = dict(self.kwargs)
            if "progress_callback" not in kwargs and self._supports_callback_argument(
                self.fn, "progress_callback"
            ):
                kwargs["progress_callback"] = self._progress_callback
            if "cancel_callback" not in kwargs and self._supports_callback_argument(
                self.fn, "cancel_callback"
            ):
                kwargs["cancel_callback"] = self.is_cancel_requested
            if "is_cancelled" not in kwargs and self._supports_callback_argument(
                self.fn, "is_cancelled"
            ):
                kwargs["is_cancelled"] = self.is_cancel_requested
            if self.is_cancel_requested():
                return
            result = self.fn(*self.args, **kwargs)
            if not self.is_cancel_requested():
                self._emit_signal("result", result)
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if self.is_cancel_requested():
                logger.debug("Cancelled worker suppressed service error: %s", exc)
            elif self.log_exceptions:
                logger.exception("Background worker failed")
            else:
                logger.warning("Background worker failed: %s", exc)
            if not self.is_cancel_requested():
                self._emit_signal("error", str(exc))
        except Exception as exc:
            if self.is_cancel_requested():
                logger.debug("Cancelled worker suppressed error: %s", exc)
            elif self.log_exceptions:
                logger.exception("Background worker failed")
            else:
                logger.warning("Background worker failed: %s", exc)
            if not self.is_cancel_requested():
                self._emit_signal("error", str(exc))
        finally:
            self._emit_signal("finished")


class WorkerRegistry:
    """Own background workers and operation keys for one UI component."""

    def __init__(self, pool: QThreadPool | None = None):
        self.pool = pool or client_thread_pool()
        self._workers: set[Worker] = set()
        self._active_keys: set[str] = set()
        self._generation = 0
        self._closed = False
        self._lock = threading.RLock()

    def active_count(self) -> int:
        with self._lock:
            return len(self._workers)

    def has_active_key(self, key: str | None) -> bool:
        clean_key = str(key or "").strip()
        with self._lock:
            return bool(clean_key and clean_key in self._active_keys)

    def cancel_all(self) -> None:
        """Cancel all owned work and invalidate callbacks from old workers."""
        with self._lock:
            self._generation += 1
            workers = list(self._workers)
            self._active_keys.clear()
        for worker in workers:
            try:
                worker.cancel()
            except UI_OPERATION_EXCEPTIONS:
                logger.debug("Worker cancellation skipped", exc_info=True)

    def close(self) -> None:
        """Permanently stop this registry for a closing UI component."""
        with self._lock:
            self._closed = True
        self.cancel_all()

    def start(
        self,
        work,
        *,
        on_result=None,
        on_error=None,
        on_progress=None,
        on_finished=None,
        operation_key: str | None = None,
        scope_checker=None,
        log_exceptions: bool = True,
    ):
        clean_key = str(operation_key or "").strip()
        with self._lock:
            if self._closed:
                logger.debug(
                    "Skipping background operation on closed registry: %s",
                    operation_key,
                )
                return None
            if clean_key and clean_key in self._active_keys:
                logger.debug("Skipping duplicate background operation: %s", clean_key)
                return None
            generation = self._generation
            worker = Worker(work, log_exceptions=log_exceptions)
            self._workers.add(worker)
            if clean_key:
                self._active_keys.add(clean_key)

        def _scope_ok() -> bool:
            with self._lock:
                registry_stale = self._closed or generation != self._generation
            if registry_stale:
                return False
            if scope_checker is None:
                return True
            try:
                return bool(scope_checker())
            except UI_OPERATION_EXCEPTIONS:
                logger.debug("Worker scope check failed", exc_info=True)
                return False

        def _guarded_result(payload):
            if _scope_ok() and on_result is not None:
                on_result(payload)

        def _guarded_error(message):
            if _scope_ok() and on_error is not None:
                on_error(message)

        def _guarded_progress(message):
            if _scope_ok() and on_progress is not None:
                on_progress(message)

        def _release():
            with self._lock:
                self._workers.discard(worker)
                if clean_key and generation == self._generation:
                    self._active_keys.discard(clean_key)
            if _scope_ok() and on_finished is not None:
                on_finished()

        if on_result is not None:
            worker.signals.result.connect(_guarded_result)
        if on_error is not None:
            worker.signals.error.connect(_guarded_error)
        if on_progress is not None:
            worker.signals.progress.connect(_guarded_progress)
        worker.signals.finished.connect(_release)
        self.pool.start(worker)
        return worker
