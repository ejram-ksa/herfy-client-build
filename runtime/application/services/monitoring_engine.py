from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from runtime.domain.tracking_models import TrackingKey, TrackingRecord
from runtime.application.services.expiry_status import ExpiryStatusKind, ExpiryThresholds
from runtime.application.services.expiry_status import classify_expiry_date


@dataclass(frozen=True, slots=True)
class ExpiryAlert:
    key: TrackingKey
    record: TrackingRecord
    state: ExpiryStatusKind
    severity: int
    days_left: int | None
    display_text: str


@dataclass(frozen=True, slots=True)
class ExpiryTransition:
    key: TrackingKey
    previous: ExpiryStatusKind | None
    current: ExpiryStatusKind
    alert: ExpiryAlert | None = None


class MonitoringEngine:
    def __init__(self) -> None:
        self._states: dict[TrackingKey, ExpiryStatusKind] = {}

    def evaluate(
        self,
        *,
        records: Iterable[TrackingRecord],
        now: datetime,
        policy: ExpiryThresholds,
    ) -> tuple[ExpiryTransition, ...]:
        today = now.date() if isinstance(now, datetime) else date.today()
        transitions: list[ExpiryTransition] = []
        next_states: dict[TrackingKey, ExpiryStatusKind] = {}
        for record in records:
            status = classify_expiry_date(
                record.key.expiry_date,
                today=today,
                expiring_soon_threshold=policy.soon_days,
                critical_threshold=policy.critical_days,
            )
            current = status.kind
            next_states[record.key] = current
            previous = self._states.get(record.key)
            alert = None
            if status.should_notify_default and status.days_remaining is not None:
                alert = ExpiryAlert(
                    key=record.key,
                    record=record,
                    state=current,
                    severity=status.severity_rank,
                    days_left=status.days_remaining,
                    display_text=status.display_text,
                )
            # Emit changed states for UI/state tracking and emit every currently
            # notifiable state so NotificationService can apply the configured
            # once-per-day/cooldown policy.  Suppressing unchanged states here
            # would make notification_repeat_interval_minutes ineffective.
            if previous != current or alert is not None:
                transitions.append(
                    ExpiryTransition(
                        key=record.key,
                        previous=previous,
                        current=current,
                        alert=alert,
                    )
                )
        self._states = next_states
        return tuple(transitions)
