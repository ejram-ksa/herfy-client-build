from __future__ import annotations

from threading import RLock
from typing import Callable

from runtime.services.lifecycle.models import LifecycleReport, LifecycleState, RegisteredResource


class ApplicationLifecycle:
    """Central owner of startup, background transition and orderly shutdown."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._state = LifecycleState.NEW
        self._resources: list[RegisteredResource] = []
        self._startup_steps: list[tuple[str, Callable[[], None]]] = []
        self._background_steps: list[tuple[str, Callable[[], None]]] = []
        self._foreground_steps: list[tuple[str, Callable[[], None]]] = []
        self._shutdown_steps: list[tuple[str, Callable[[], None]]] = []

    @property
    def state(self) -> LifecycleState:
        with self._lock:
            return self._state

    def register_resource(
        self,
        name: str,
        resource,
        *,
        stop_method: str = "stop",
        wait_method: str | None = "wait",
        timeout_seconds: float = 5.0,
    ) -> None:
        item = RegisteredResource(
            name=str(name),
            resource=resource,
            stop_method=stop_method,
            wait_method=wait_method,
            timeout_seconds=timeout_seconds,
        )
        with self._lock:
            self._resources.append(item)

    def on_start(self, name: str, callback: Callable[[], None]) -> None:
        self._startup_steps.append((name, callback))

    def on_background(self, name: str, callback: Callable[[], None]) -> None:
        self._background_steps.append((name, callback))

    def on_foreground(self, name: str, callback: Callable[[], None]) -> None:
        self._foreground_steps.append((name, callback))

    def on_shutdown(self, name: str, callback: Callable[[], None]) -> None:
        self._shutdown_steps.append((name, callback))

    def start(self) -> LifecycleReport:
        with self._lock:
            if self._state in {LifecycleState.RUNNING, LifecycleState.BACKGROUND}:
                return LifecycleReport("start", completed_steps=["already_running"])
            if self._state == LifecycleState.STOPPING:
                raise RuntimeError("cannot start while stopping")
            self._state = LifecycleState.STARTING
        report = self._run_steps("start", self._startup_steps)
        with self._lock:
            self._state = LifecycleState.RUNNING if report.successful else LifecycleState.FAILED
        return report

    def enter_background(self) -> LifecycleReport:
        with self._lock:
            if self._state != LifecycleState.RUNNING:
                raise RuntimeError("background transition requires running state")
        report = self._run_steps("background", self._background_steps)
        if report.successful:
            with self._lock:
                self._state = LifecycleState.BACKGROUND
        return report

    def enter_foreground(self) -> LifecycleReport:
        with self._lock:
            if self._state != LifecycleState.BACKGROUND:
                raise RuntimeError("foreground transition requires background state")
        report = self._run_steps("foreground", self._foreground_steps)
        if report.successful:
            with self._lock:
                self._state = LifecycleState.RUNNING
        return report

    def shutdown(self) -> LifecycleReport:
        with self._lock:
            if self._state == LifecycleState.STOPPED:
                return LifecycleReport("shutdown", completed_steps=["already_stopped"])
            self._state = LifecycleState.STOPPING

        report = LifecycleReport("shutdown")
        for name, callback in reversed(self._shutdown_steps):
            self._attempt(report, name, callback)

        with self._lock:
            resources = tuple(reversed(self._resources))

        for item in resources:
            stop = getattr(item.resource, item.stop_method, None)
            if callable(stop):
                self._attempt(report, f"stop:{item.name}", stop)
            if item.wait_method:
                wait = getattr(item.resource, item.wait_method, None)
                if callable(wait):
                    self._attempt(
                        report,
                        f"wait:{item.name}",
                        lambda wait=wait, timeout=item.timeout_seconds: self._require_wait(wait, timeout),
                    )

        with self._lock:
            self._state = LifecycleState.STOPPED if report.successful else LifecycleState.FAILED
        return report

    @staticmethod
    def _require_wait(wait, timeout: float) -> None:
        result = wait(timeout)
        if result is False:
            raise TimeoutError(f"resource did not stop within {timeout} seconds")

    def _run_steps(self, operation: str, steps) -> LifecycleReport:
        report = LifecycleReport(operation)
        for name, callback in steps:
            self._attempt(report, name, callback)
            if report.errors and operation == "start":
                break
        return report

    @staticmethod
    def _attempt(report: LifecycleReport, name: str, callback: Callable[[], None]) -> None:
        try:
            callback()
            report.completed_steps.append(name)
        except Exception as exc:
            report.errors.append(f"{name}: {type(exc).__name__}")
