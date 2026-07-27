from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from PyQt5.QtCore import QObject, QThreadPool, QTimer, pyqtSignal
from runtime.shared.settings.config import _
from runtime.application.services.usage import UsageWorkspaceDecision, UsageWorkspaceService
from runtime.bootstrap.qt.workers import WorkerRegistry, client_thread_pool


@dataclass(frozen=True)
class UsageComputePayload:
    rows: list[dict]
    status_text: str


class UsageComputeService(QObject):
    busy_changed = pyqtSignal(bool)
    status_changed = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    error_raised = pyqtSignal(str)

    def __init__(
        self,
        *,
        usage_service: Any,
        workspace_service: UsageWorkspaceService | None = None,
        thread_pool: QThreadPool | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.usage_service = usage_service
        self.workspace_service = workspace_service or UsageWorkspaceService()
        self._pool = thread_pool or client_thread_pool()
        self._worker_registry = WorkerRegistry(self._pool)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._run_pending_request)
        self._compute_running = False
        self._compute_pending = False
        self._compute_token = 0
        self._current_worker = None
        self._last_request: dict[str, object] = {
            "access_allowed": True,
            "access_reason": "",
            "receipts_path": "",
            "beginning_path": "",
        }

    @property
    def is_busy(self) -> bool:
        return bool(self._compute_running)

    def close(self) -> None:
        self.cancel()

    def cancel(self) -> None:
        self._compute_token = int(getattr(self, "_compute_token", 0) or 0) + 1
        self._compute_pending = False
        self._debounce.stop()
        registry = getattr(self, "_worker_registry", None)
        if registry is not None:
            registry.cancel_all()
        self._current_worker = None
        if self._compute_running:
            self._emit_busy(False)

    def request_auto_compute(
        self,
        *,
        access_allowed: bool,
        access_reason: str,
        receipts_path: str,
        beginning_path: str,
        delay_ms: int = 400,
        db_manager=None,
    ) -> bool:
        self._last_request = {
            "access_allowed": bool(access_allowed),
            "access_reason": str(access_reason or ""),
            "receipts_path": str(receipts_path or "").strip(),
            "beginning_path": str(beginning_path or "").strip(),
        }
        if not self.workspace_service.auto_compute_ready(receipts_path, beginning_path):
            return False
        if self._compute_running:
            self._compute_pending = True
        self.status_changed.emit(_("Preparing…"))
        self._debounce.start(max(150, int(delay_ms or 0)))
        return True

    def request_compute(
        self,
        *,
        access_allowed: bool,
        access_reason: str,
        receipts_path: str,
        beginning_path: str,
        db_manager=None,
    ) -> None:
        self._last_request = {
            "access_allowed": bool(access_allowed),
            "access_reason": str(access_reason or ""),
            "receipts_path": str(receipts_path or "").strip(),
            "beginning_path": str(beginning_path or "").strip(),
        }
        if self._compute_running:
            self._compute_pending = True
            self.status_changed.emit(
                _("Calculation already running; queued latest request…")
            )
            return
        self._run_pending_request()

    def _emit_busy(self, busy: bool) -> None:
        busy = bool(busy)
        self._compute_running = busy
        self.busy_changed.emit(busy)

    def _evaluate_request(self) -> UsageWorkspaceDecision:
        return self.workspace_service.evaluate_compute_request(
            access_allowed=bool(self._last_request.get("access_allowed", True)),
            access_reason=str(self._last_request.get("access_reason") or ""),
            usage_service=self.usage_service,
            receipts_path=str(self._last_request.get("receipts_path") or ""),
            beginning_path=str(self._last_request.get("beginning_path") or ""),
        )

    def _run_pending_request(self) -> None:
        if self._compute_running:
            return
        decision = self._evaluate_request()
        if not decision.allowed:
            self.error_raised.emit(decision.message)
            return
        receipts_path = str(self._last_request.get("receipts_path") or "")
        beginning_path = str(self._last_request.get("beginning_path") or "")
        self._compute_token = int(getattr(self, "_compute_token", 0) or 0) + 1
        compute_token = self._compute_token
        self._emit_busy(True)
        self.status_changed.emit(_("Preparing…"))

        def _is_current_compute() -> bool:
            return compute_token == int(getattr(self, "_compute_token", -1) or -1)

        def _work(progress_callback=None):
            return self.usage_service.compute_rows(
                receipts_path, beginning_path, progress_callback=progress_callback
            )

        worker = self._worker_registry.start(
            _work,
            on_progress=self._on_worker_progress,
            on_result=self._on_worker_result,
            on_error=self._on_worker_error,
            on_finished=self._on_worker_finished,
            operation_key="usage:compute",
            scope_checker=_is_current_compute,
        )
        self._current_worker = worker
        if worker is None:
            self._emit_busy(False)
            self._compute_pending = True
            self._debounce.start(400)

    def _on_worker_progress(self, message) -> None:
        if message:
            self.status_changed.emit(str(message))

    def _on_worker_result(self, rows) -> None:
        rows = list(rows or [])
        status_text = self.workspace_service.build_result_status(
            rows, self.usage_service
        )
        self.result_ready.emit(UsageComputePayload(rows=rows, status_text=status_text))
        self.status_changed.emit(status_text)

    def _on_worker_error(self, message: str) -> None:
        self.error_raised.emit(str(message or _("Usage calculation failed.")))

    def _on_worker_finished(self) -> None:
        self._current_worker = None
        self._emit_busy(False)
        if self._compute_pending:
            self._compute_pending = False
            self._debounce.start(400)
