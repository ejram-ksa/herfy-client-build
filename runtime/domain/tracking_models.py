from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Any


@dataclass(frozen=True, slots=True)
class TrackingScope:
    branches: tuple[str, ...]

    @classmethod
    def from_value(cls, value: Any) -> "TrackingScope":
        if isinstance(value, TrackingScope):
            return value
        if isinstance(value, str):
            branches = (value.strip(),) if value.strip() else ()
        else:
            branches = tuple(
                str(branch or "").strip()
                for branch in value or ()
                if str(branch or "").strip()
            )
        return cls(tuple(dict.fromkeys(branches)))

    @property
    def hash(self) -> str:
        payload = "\n".join(branch.casefold() for branch in self.branches)
        return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, order=True)
class TrackingKey:
    branch_code: str
    material_number: str
    production_date: date | None
    expiry_date: date


@dataclass(frozen=True, slots=True)
class RemoteTrackingId:
    value: str


@dataclass(frozen=True, slots=True)
class TrackingRecord:
    key: TrackingKey
    remote_id: RemoteTrackingId
    product_name: str
    quantity: int
    branch_name: str
    revision: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TrackingBaseline:
    revision: int
    scope: TrackingScope
    records: tuple[TrackingRecord, ...]
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class TrackingDelta:
    from_revision: int
    to_revision: int
    inserted: tuple[TrackingRecord, ...]
    updated: tuple[TrackingRecord, ...]
    deleted: tuple[TrackingKey, ...]


@dataclass(frozen=True, slots=True)
class TrackingMutation:
    operation: str
    record: TrackingRecord | None = None
    key: TrackingKey | None = None
