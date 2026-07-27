from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import RLock
from typing import Any

from runtime.domain.tracking_events import (
    CommitResult,
    DeltaResult,
    TrackingSnapshot,
    TrackingStoreEvent,
)
from runtime.domain.tracking_rows import tracking_key_sort_value
from runtime.domain.tracking_models import (
    RemoteTrackingId,
    TrackingBaseline,
    TrackingDelta,
    TrackingKey,
    TrackingRecord,
    TrackingScope,
)


@dataclass(frozen=True, slots=True)
class RefreshToken:
    session_id: str
    scope_hash: str
    generation: int


class Subscription:
    def __init__(
        self,
        subscribers: set[Callable[[TrackingStoreEvent], None]],
        callback: Callable[[TrackingStoreEvent], None],
        lock: RLock,
    ) -> None:
        self._subscribers = subscribers
        self._callback = callback
        self._lock = lock
        self._active = True

    def unsubscribe(self) -> None:
        with self._lock:
            if self._active:
                self._subscribers.discard(self._callback)
                self._active = False


class TrackingStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[TrackingKey, TrackingRecord] = {}
        self._remote_index: dict[RemoteTrackingId, TrackingKey] = {}
        self._generation = 0
        self._revision: int | None = None
        self._scope: TrackingScope | None = None
        self._session_id = ""
        self._baseline_ready = False
        self._pending_deltas: deque[TrackingDelta] = deque()
        self._subscribers: set[Callable[[TrackingStoreEvent], None]] = set()

    @property
    def current_generation(self) -> int:
        with self._lock:
            return self._generation

    def begin_refresh(self, scope: Any, session_id: str = "") -> RefreshToken:
        resolved = TrackingScope.from_value(scope)
        with self._lock:
            if self._scope != resolved or self._session_id != str(session_id or ""):
                self._generation += 1
                self._scope = resolved
                self._session_id = str(session_id or "")
            return RefreshToken(
                session_id=self._session_id,
                scope_hash=resolved.hash,
                generation=self._generation,
            )

    def commit_baseline(
        self, token: RefreshToken, baseline: TrackingBaseline
    ) -> CommitResult:
        with self._lock:
            rejection = self._token_rejection(token)
            if rejection:
                return CommitResult(False, rejection)
            records = self._deduplicate_records(baseline.records)
            new_records = {record.key: record for record in records}
            inserted, updated, deleted = self._baseline_diff_unlocked(new_records)
            self._records = new_records
            self._remote_index = {
                record.remote_id: record.key
                for record in records
                if record.remote_id.value
            }
            self._revision = int(baseline.revision)
            self._baseline_ready = True
            self._generation += 1
            self._drain_pending_deltas_unlocked()
            event = TrackingStoreEvent(
                "baseline_committed",
                self._snapshot_unlocked(),
                inserted=inserted,
                updated=updated,
                deleted=deleted,
            )
        self._publish(event)
        return CommitResult(True, "committed", event)

    def queue_or_apply_delta(self, delta: TrackingDelta) -> DeltaResult:
        with self._lock:
            if not self._baseline_ready:
                self._pending_deltas.append(delta)
                event = TrackingStoreEvent(
                    "delta_queued", self._snapshot_unlocked(), reason="baseline_missing"
                )
                publish = event
                result = DeltaResult(True, "queued", event)
            elif delta.from_revision != self._revision:
                self._pending_deltas.clear()
                event = TrackingStoreEvent(
                    "revision_gap",
                    self._snapshot_unlocked(),
                    reason="revision_gap",
                )
                publish = event
                result = DeltaResult(False, "revision_gap", event)
            else:
                event = self._apply_delta_unlocked(delta)
                publish = event
                result = DeltaResult(True, "applied", event)
        self._publish(publish)
        return result

    def upsert_local(self, record: TrackingRecord) -> TrackingStoreEvent:
        with self._lock:
            self._records = {**self._records, record.key: record}
            if record.remote_id.value:
                self._remote_index = {
                    **self._remote_index,
                    record.remote_id: record.key,
                }
            self._generation += 1
            event = TrackingStoreEvent(
                "upserted", self._snapshot_unlocked(), updated=(record,)
            )
        self._publish(event)
        return event

    def remove_local(self, key: TrackingKey) -> TrackingStoreEvent:
        with self._lock:
            records = dict(self._records)
            removed = records.pop(key, None)
            self._records = records
            self._remote_index = {
                remote_id: indexed_key
                for remote_id, indexed_key in self._remote_index.items()
                if indexed_key != key
            }
            self._generation += 1
            event = TrackingStoreEvent(
                "removed",
                self._snapshot_unlocked(),
                deleted=(key,) if removed is not None else (),
            )
        self._publish(event)
        return event

    def snapshot(self) -> TrackingSnapshot:
        with self._lock:
            return self._snapshot_unlocked()

    def subscribe(self, callback: Callable[[TrackingStoreEvent], None]) -> Subscription:
        with self._lock:
            self._subscribers.add(callback)
        return Subscription(self._subscribers, callback, self._lock)

    def reset(self, session_id: str = "") -> None:
        with self._lock:
            self._records = {}
            self._remote_index = {}
            self._generation += 1
            self._revision = None
            self._scope = None
            self._session_id = str(session_id or "")
            self._baseline_ready = False
            self._pending_deltas.clear()
            event = TrackingStoreEvent("reset", self._snapshot_unlocked())
        self._publish(event)

    def _token_rejection(self, token: RefreshToken) -> str:
        if token.session_id != self._session_id:
            return "rejected_session_changed"
        if self._scope is None or token.scope_hash != self._scope.hash:
            return "rejected_scope_changed"
        if token.generation != self._generation:
            return "rejected_stale_generation"
        return ""

    def _apply_delta_unlocked(self, delta: TrackingDelta) -> TrackingStoreEvent:
        records = dict(self._records)
        for key in delta.deleted:
            records.pop(key, None)
        for record in (*delta.inserted, *delta.updated):
            records[record.key] = record
        self._records = records
        self._remote_index = {
            record.remote_id: record.key
            for record in records.values()
            if record.remote_id.value
        }
        self._revision = int(delta.to_revision)
        self._generation += 1
        return TrackingStoreEvent(
            "delta_applied",
            self._snapshot_unlocked(),
            inserted=delta.inserted,
            updated=delta.updated,
            deleted=delta.deleted,
        )

    def _drain_pending_deltas_unlocked(self) -> None:
        pending = tuple(
            sorted(self._pending_deltas, key=lambda item: item.from_revision)
        )
        self._pending_deltas.clear()
        for delta in pending:
            if delta.from_revision != self._revision:
                self._pending_deltas.clear()
                break
            self._apply_delta_unlocked(delta)

    def _snapshot_unlocked(self) -> TrackingSnapshot:
        scope_hash = self._scope.hash if self._scope is not None else ""
        return TrackingSnapshot(
            generation=self._generation,
            revision=self._revision,
            scope_hash=scope_hash,
            baseline_ready=self._baseline_ready,
            records=tuple(
                self._records[key]
                for key in sorted(self._records, key=tracking_key_sort_value)
            ),
        )

    def _baseline_diff_unlocked(
        self, new_records: dict[TrackingKey, TrackingRecord]
    ) -> tuple[
        tuple[TrackingRecord, ...], tuple[TrackingRecord, ...], tuple[TrackingKey, ...]
    ]:
        old_records = self._records
        inserted = tuple(
            record for key, record in new_records.items() if key not in old_records
        )
        updated = tuple(
            record
            for key, record in new_records.items()
            if key in old_records and old_records[key] != record
        )
        deleted = tuple(key for key in old_records if key not in new_records)
        return (inserted, updated, deleted)

    @staticmethod
    def _deduplicate_records(
        records: Iterable[TrackingRecord],
    ) -> tuple[TrackingRecord, ...]:
        by_key = {record.key: record for record in records}
        return tuple(
            by_key[key] for key in sorted(by_key, key=tracking_key_sort_value)
        )

    def _publish(self, event: TrackingStoreEvent) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for callback in subscribers:
            callback(event)


tracking_store = TrackingStore()
