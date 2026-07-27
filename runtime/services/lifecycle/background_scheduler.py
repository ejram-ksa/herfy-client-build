from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable


@dataclass(slots=True)
class ScheduledJob:
    name: str
    interval_seconds: float
    callback: Callable[[], None]
    run_immediately: bool = False
    next_run_at: float = field(default=0.0)
    last_error: str | None = None
    run_count: int = 0
    running: bool = False
    pending: bool = False


class BackgroundScheduler:
    """Recurring-job scheduler with bounded non-overlapping execution.

    The scheduler thread only decides *when* a job is due. Long-running work is
    dispatched to a bounded executor so one slow network or database operation
    cannot delay unrelated token-refresh, notification, heartbeat, or sync jobs.
    A job never overlaps with itself; one pending rerun is coalesced while it is
    running.
    """

    def __init__(
        self,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
        max_workers: int = 4,
    ) -> None:
        del sleep  # The scheduler uses wake events rather than injected sleeps.
        self._clock = clock
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jobs: dict[str, ScheduledJob] = {}
        self._paused = False
        self._max_workers = max(1, int(max_workers))
        self._executor: ThreadPoolExecutor | None = None
        self._futures: set[Future[None]] = set()

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def register(
        self,
        name: str,
        interval_seconds: float,
        callback: Callable[[], None],
        *,
        run_immediately: bool = False,
    ) -> None:
        key = str(name or "").strip()
        if not key:
            raise ValueError("job name is required")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if not callable(callback):
            raise TypeError("callback must be callable")
        now = self._clock()
        with self._lock:
            existing = self._jobs.get(key)
            if existing is not None and existing.running:
                raise RuntimeError(f"cannot replace running scheduled job: {key}")
            self._jobs[key] = ScheduledJob(
                name=key,
                interval_seconds=float(interval_seconds),
                callback=callback,
                run_immediately=bool(run_immediately),
                next_run_at=now if run_immediately else now + float(interval_seconds),
            )
        self._wake.set()

    def unregister(self, name: str) -> None:
        with self._lock:
            self._jobs.pop(str(name), None)
        self._wake.set()

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._wake.clear()
            self._ensure_executor_locked()
            self._thread = threading.Thread(
                target=self._run,
                name="herfy-background-scheduler",
                daemon=True,
            )
            self._thread.start()

    def pause(self) -> None:
        with self._lock:
            self._paused = True
        self._wake.set()

    def resume(self) -> None:
        now = self._clock()
        with self._lock:
            self._paused = False
            for job in self._jobs.values():
                if job.next_run_at < now:
                    job.next_run_at = now
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wait(self, timeout_seconds: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        thread = self._thread
        if thread is not None:
            thread.join(max(0.0, deadline - time.monotonic()))
            if thread.is_alive():
                return False
        with self._lock:
            futures = tuple(self._futures)
        for future in futures:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0.0:
                return False
            try:
                future.result(timeout=remaining)
            except Exception:
                # Callback failures are already captured on the job.
                pass
        self._shutdown_executor(wait=False)
        return True

    def run_due_once(self) -> int:
        """Run due callbacks synchronously.

        This deterministic path is intentionally retained for validation tools
        and unit tests. The live scheduler thread uses ``dispatch_due_once`` so
        long-running callbacks never block scheduling of unrelated jobs.
        """
        due = self._claim_due_jobs()
        for job in due:
            self._execute_job(job)
        return len(due)

    def dispatch_due_once(self) -> int:
        """Dispatch due callbacks to the bounded executor without overlap."""
        due = self._claim_due_jobs()
        if not due:
            return 0
        with self._lock:
            executor = self._ensure_executor_locked()
            for job in due:
                future = executor.submit(self._execute_job, job)
                self._futures.add(future)
                future.add_done_callback(self._discard_future)
        return len(due)

    def snapshot(self) -> dict[str, dict[str, object]]:
        with self._lock:
            return {
                name: {
                    "interval_seconds": job.interval_seconds,
                    "next_run_at": job.next_run_at,
                    "last_error": job.last_error,
                    "run_count": job.run_count,
                    "running": job.running,
                    "pending": job.pending,
                }
                for name, job in self._jobs.items()
            }

    def _claim_due_jobs(self) -> list[ScheduledJob]:
        now = self._clock()
        due: list[ScheduledJob] = []
        with self._lock:
            if self._paused or self._stop.is_set():
                return due
            for job in self._jobs.values():
                if job.next_run_at > now:
                    continue
                job.next_run_at = now + job.interval_seconds
                if job.running:
                    job.pending = True
                    continue
                job.running = True
                due.append(job)
        return due

    def _execute_job(self, job: ScheduledJob) -> None:
        try:
            job.callback()
            error: str | None = None
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        rerun = False
        with self._lock:
            current = self._jobs.get(job.name)
            if current is job:
                job.last_error = error
                job.run_count += 1
                job.running = False
                if job.pending and not self._paused and not self._stop.is_set():
                    job.pending = False
                    job.running = True
                    rerun = True
        if rerun:
            with self._lock:
                executor = self._ensure_executor_locked()
                future = executor.submit(self._execute_job, job)
                self._futures.add(future)
                future.add_done_callback(self._discard_future)
        self._wake.set()

    def _discard_future(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)

    def _ensure_executor_locked(self) -> ThreadPoolExecutor:
        executor = self._executor
        if executor is None:
            executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="herfy-background-job",
            )
            self._executor = executor
        return executor

    def _shutdown_executor(self, *, wait: bool) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=False)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.dispatch_due_once()
            timeout = self._next_timeout()
            self._wake.wait(timeout)
            self._wake.clear()

    def _next_timeout(self) -> float:
        with self._lock:
            if self._paused or not self._jobs:
                return 0.5
            now = self._clock()
            next_due = min(job.next_run_at for job in self._jobs.values())
            return max(0.01, min(0.5, next_due - now))
