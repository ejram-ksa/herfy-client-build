from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from runtime.domain.tracking_models import TrackingBaseline, TrackingScope
from runtime.domain.tracking_rows import deduplicate_tracking_records, tracking_record_from_row
from runtime.application.services.tracking_store import tracking_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrackingBaselineSnapshot:
    generation: int
    rows: tuple[dict[str, Any], ...]
    source: str
    priority: int
    ready: bool


class TrackingBaselineCoordinator:
    """Single in-process authority for tracking baseline publication."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._generation = 0
        self._rows: list[dict[str, Any]] = []
        self._source = ""
        self._priority = 0
        self._ready = False

    def reset(self) -> None:
        with self._lock:
            self._generation += 1
            self._rows = []
            self._source = ""
            self._priority = 0
            self._ready = False
        tracking_store.reset(session_id="")

    @staticmethod
    def _source_priority(source: str) -> int:
        return {
            "network": 50,
            "initial_hydrate": 45,
            "app_state": 40,
            "realtime": 40,
            "monitor": 25,
            "cache": 20,
            "monitor_preload": 15,
            "page_preload": 10,
        }.get(str(source or "").strip().lower(), 5)

    def publish(
        self, rows, *, source: str, force: bool = False
    ) -> TrackingBaselineSnapshot:
        normalized = deduplicate_tracking_records(rows)
        wanted_priority = self._source_priority(source)
        with self._lock:
            if self._ready and not force and wanted_priority < self._priority:
                return self._snapshot_unlocked()
            self._generation += 1
            self._rows = [dict(row) for row in normalized]
            self._source = str(source or "unknown")
            self._priority = wanted_priority
            self._ready = True
            snapshot = self._snapshot_unlocked()
        self._publish_to_store(snapshot)
        return snapshot

    def snapshot(self) -> TrackingBaselineSnapshot:
        with self._lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> TrackingBaselineSnapshot:
        return TrackingBaselineSnapshot(
            generation=self._generation,
            rows=tuple(dict(row) for row in self._rows),
            source=self._source,
            priority=self._priority,
            ready=self._ready,
        )

    @staticmethod
    def _publish_to_store(snapshot: TrackingBaselineSnapshot) -> None:
        records = tuple(
            record
            for row in snapshot.rows
            for record in (tracking_record_from_row(row),)
            if record is not None
        )
        scope = TrackingScope.from_value(
            tuple(dict.fromkeys(record.key.branch_code for record in records))
        )
        token = tracking_store.begin_refresh(scope, session_id="")
        result = tracking_store.commit_baseline(
            token,
            TrackingBaseline(
                revision=snapshot.generation,
                scope=scope,
                records=records,
                generated_at=datetime.now(timezone.utc),
            ),
        )
        if not result.accepted:
            logger.info(
                "tracking.baseline.rejected_generation",
                extra={"reason": result.reason, "generation": snapshot.generation},
            )


tracking_baseline = TrackingBaselineCoordinator()
