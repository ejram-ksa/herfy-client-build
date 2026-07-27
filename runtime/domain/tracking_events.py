from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from runtime.domain.tracking_models import TrackingKey, TrackingRecord

StoreEventKind = Literal[
    "baseline_committed",
    "delta_applied",
    "delta_queued",
    "revision_gap",
    "upserted",
    "removed",
    "reset",
]


@dataclass(frozen=True, slots=True)
class TrackingSnapshot:
    generation: int
    revision: int | None
    scope_hash: str
    baseline_ready: bool
    records: tuple[TrackingRecord, ...]


@dataclass(frozen=True, slots=True)
class TrackingStoreEvent:
    kind: StoreEventKind
    snapshot: TrackingSnapshot
    inserted: tuple[TrackingRecord, ...] = ()
    updated: tuple[TrackingRecord, ...] = ()
    deleted: tuple[TrackingKey, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CommitResult:
    accepted: bool
    reason: str
    event: TrackingStoreEvent | None = None


@dataclass(frozen=True, slots=True)
class DeltaResult:
    accepted: bool
    reason: str
    event: TrackingStoreEvent | None = None
