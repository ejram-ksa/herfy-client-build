from __future__ import annotations

import json
import logging
import secrets
import threading
from collections.abc import Callable
from typing import Any

from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.objects import clean_string_list, normalize_int
from runtime.shared.signals import safe_disconnect

logger = logging.getLogger(__name__)


class Signal:
    """Small thread-safe callback signal used outside Qt objects."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[..., None]] = []
        self._lock = threading.RLock()

    def connect(self, callback: Callable[..., None]) -> None:
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def disconnect(self, callback: Callable[..., None] | None = None) -> None:
        with self._lock:
            if callback is None:
                self._callbacks.clear()
                return
            # Bound-method objects are recreated on each attribute access. Equality,
            # unlike identity, correctly matches the same instance/method pair.
            self._callbacks = [item for item in self._callbacks if item != callback]

    def emit(self, *args: Any) -> None:
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            try:
                callback(*args)
            except SERVICE_OPERATION_EXCEPTIONS:
                logger.exception("Realtime callback raised an exception")


class CallbackBridge:
    def __init__(self) -> None:
        self.on_changed = Signal()
        self.on_state = Signal()


class RemoteRealtimeMixin:
    def events_mode_available(self) -> bool:
        return not bool(getattr(self, "_events_unavailable", False))

    def _resolve_product_name(self, material_number: str) -> str:
        mid = str(material_number).strip()
        if mid in self._stored_cache:
            return self._stored_cache[mid]
        self._refresh_stored_snapshot_safely()
        return self._stored_cache.get(mid, mid)

    def _next_reconnect_delay(self, attempt: int) -> float:
        base = min(30.0, float(2 ** max(0, attempt)))
        jitter = 1.0 + secrets.SystemRandom().uniform(0.0, 0.2)
        return min(30.0, base * jitter)

    @staticmethod
    def _is_keepalive_line(line: str) -> bool:
        return str(line or "").startswith(":")

    @staticmethod
    def _cursor_from_realtime_payload(payload_text: str) -> int:
        text = str(payload_text or "").strip()
        if not text:
            return 0
        direct_value = normalize_int(text, 0)
        if direct_value > 0:
            return direct_value
        try:
            payload = json.loads(text)
        except SERVICE_OPERATION_EXCEPTIONS:
            return 0
        if not isinstance(payload, dict):
            return 0
        for key in ("cursor", "last_id", "id", "event_id", "version"):
            value = normalize_int(payload.get(key), 0)
            if value > 0:
                return value
        return 0

    def start_realtime(self, *args: Any, **kwargs: Any) -> None:
        if args and isinstance(args[0], list | tuple):
            branches = list(args[0])
            on_change = args[1] if len(args) > 1 else None
            self._start_stream_mode(branches, on_change)
            return
        on_changed = args[0] if args else None
        on_state = kwargs.get("on_state")
        self._start_events_mode(on_changed, on_state=on_state)

    @staticmethod
    def _replace_realtime_signal(
        signal: Signal, callback: Callable[..., None] | None
    ) -> None:
        # Always clear the previous receiver. Starting a mode without a callback
        # must not leave a stale callback from an earlier window/session attached.
        safe_disconnect(signal, logger_=logger, context="Realtime signal disconnect")
        if callback is not None:
            signal.connect(callback)

    def _iter_sse_events(self, response: Any, stop_event: threading.Event):
        event: str | None = None
        data_buf: list[str] = []
        for raw in response.iter_lines(decode_unicode=True):
            if stop_event.is_set():
                break
            if raw is None:
                continue
            line = raw.strip("\r")
            if not line:
                if event and data_buf:
                    yield (event, "\n".join(data_buf))
                event = None
                data_buf = []
                continue
            if self._is_keepalive_line(line):
                continue
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
                continue
            if line.startswith("data:"):
                data_buf.append(line.split(":", 1)[1].lstrip())
        if not stop_event.is_set() and event and data_buf:
            yield (event, "\n".join(data_buf))

    def _start_events_mode(
        self,
        on_changed: Callable[[int], None] | None,
        on_state: Callable[[bool], None] | None = None,
    ) -> None:
        self._reset_realtime_worker()
        stop_event = self._rt_stop
        self._events_unavailable = False
        bridge = self._callback_bridge
        self._replace_realtime_signal(bridge.on_changed, on_changed)
        self._replace_realtime_signal(bridge.on_state, on_state)

        def _run() -> None:
            connected = False
            attempt = 0
            while not stop_event.is_set():
                try:
                    with (
                        self._new_session() as stream_session,
                        self._realtime_get(
                            stream_session,
                            f"{self.base_url}/events",
                            headers=self._headers(),
                            params={"cursor": int(self._cursor)},
                            stream=True,
                        ) as response,
                    ):
                        if response.status_code in (404, 405, 501):
                            logger.info(
                                "Realtime events endpoint is unavailable; switching to fast pull fallback"
                            )
                            self._events_unavailable = True
                            connected = False
                            bridge.on_state.emit(False)
                            break
                        if response.status_code >= 400:
                            raise RuntimeError(response.text)
                        if not connected:
                            connected = True
                            attempt = 0
                            bridge.on_state.emit(True)
                        for event, payload_text in self._iter_sse_events(
                            response, stop_event
                        ):
                            if event == "changed" and payload_text:
                                try:
                                    last_id = self._cursor_from_realtime_payload(
                                        payload_text
                                    )
                                    bridge.on_changed.emit(last_id or self._cursor)
                                except SERVICE_OPERATION_EXCEPTIONS:
                                    logger.debug(
                                        "Realtime event dispatch failed",
                                        exc_info=True,
                                    )
                except SERVICE_OPERATION_EXCEPTIONS:
                    if connected:
                        connected = False
                        bridge.on_state.emit(False)
                    if stop_event.is_set():
                        break
                    if stop_event.wait(self._next_reconnect_delay(attempt)):
                        break
                    attempt = min(attempt + 1, 5)

        self._start_realtime_worker(_run)

    def _start_stream_mode(
        self,
        branches: list[str],
        on_change: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        self._reset_realtime_worker()
        stop_event = self._rt_stop
        branches_csv = ",".join(clean_string_list(branches)) or "all"
        bridge = self._callback_bridge
        self._replace_realtime_signal(bridge.on_changed, on_change)

        def _run() -> None:
            attempt = 0
            while not stop_event.is_set():
                try:
                    url = f"{self.base_url}/stream/{branches_csv}"
                    with (
                        self._new_session() as stream_session,
                        self._realtime_get(
                            stream_session,
                            url,
                            headers=self._headers(),
                            params={"cursor": int(self._cursor)},
                            stream=True,
                        ) as response,
                    ):
                        if response.status_code == 404:
                            self._start_events_mode(
                                lambda _event_id: (
                                    on_change({}) if callable(on_change) else None
                                )
                            )
                            return
                        response.raise_for_status()
                        attempt = 0
                        for event, payload_text in self._iter_sse_events(
                            response, stop_event
                        ):
                            if event in {"change", "changed"} and payload_text:
                                try:
                                    payload = json.loads(str(payload_text))
                                    change = payload.get("change")
                                    if isinstance(change, dict):
                                        bridge.on_changed.emit(change)
                                except SERVICE_OPERATION_EXCEPTIONS:
                                    logger.debug(
                                        "Realtime stream dispatch failed",
                                        exc_info=True,
                                    )
                except SERVICE_OPERATION_EXCEPTIONS:
                    if stop_event.is_set():
                        break
                    if stop_event.wait(self._next_reconnect_delay(attempt)):
                        break
                    attempt = min(attempt + 1, 5)

        self._start_realtime_worker(_run)

    def stop_realtime(self) -> None:
        # Never hold the lifecycle lock while joining. A worker may be finishing
        # code that also needs the same lock.
        with self._realtime_lock:
            stop_event = self._rt_stop
            thread = self._rt_thread
            stop_event.set()

        if thread and thread.is_alive() and thread is not threading.current_thread():
            try:
                thread.join(timeout=1.0)
            except RuntimeError:
                logger.debug("Realtime worker join failed", exc_info=True)

        with self._realtime_lock:
            if thread is self._rt_thread and (
                thread is threading.current_thread()
                or thread is None
                or not thread.is_alive()
            ):
                self._rt_thread = None
