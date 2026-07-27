from __future__ import annotations
from runtime.shared.booleans import parse_bool
from runtime.shared.objects import normalize_int
from runtime.shared.numbers import parse_plain_number
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import time
from typing import Any
from runtime.application.services.expiry_status import ExpiryStatusKind, format_days_text
from runtime.application.services.translations import tr
_URGENT_ORDER = {ExpiryStatusKind.EXPIRED.value: 6, ExpiryStatusKind.EXPIRES_TODAY.value: 5, ExpiryStatusKind.EXPIRES_TOMORROW.value: 4, ExpiryStatusKind.EXPIRING_HIGH.value: 3, ExpiryStatusKind.EXPIRING_SOON.value: 2, ExpiryStatusKind.UNKNOWN.value: 0, ExpiryStatusKind.VALID.value: 1}
_ALLOWED_SOURCES = {'local', 'server', 'monitor', 'monitoring', 'background', 'scheduled'}
_REJECTED_SOURCES = {'', 'manual', 'crud', 'add', 'edit', 'update', 'delete', 'user'}

@dataclass(frozen=True, slots=True)
class NotificationDecision:
    should_notify: bool
    key: str
    changed: bool
    escalated: bool

    def details(self) -> dict[str, object]:
        return {
            "key": self.key,
            "changed": self.changed,
            "escalated": self.escalated,
        }


class NotificationDecisionService:
    """Pure notification repetition/escalation policy.

    Persistence is supplied through a small duck-typed store contract.  This
    keeps cooldown and once-per-day decisions outside the Qt presentation
    layer and makes the behavior deterministic in unit and release gates.
    """

    def __init__(
        self,
        engine: "NotificationEngine | None" = None,
        *,
        clock=None,
        today_provider=None,
    ) -> None:
        self.engine = engine or NotificationEngine()
        self._clock = clock or time.time
        self._today_provider = today_provider or (
            lambda: datetime.now().strftime("%Y-%m-%d")
        )

    def evaluate(
        self,
        store: Any,
        event: dict,
        *,
        repeat_minutes: int = 240,
        once_per_day: bool = True,
    ) -> NotificationDecision:
        key = self.engine.alert_key(event)
        now_ts = float(self._clock())
        today = str(self._today_provider())
        repeat_minutes = min(1440, max(15, normalize_int(repeat_minutes, 240)))
        cooldown = repeat_minutes * 60

        state = store.get_alert_state(key) or {}
        ledger = (
            store.get_notification_ledger(key)
            if hasattr(store, "get_notification_ledger")
            else {}
        )
        fingerprint = self.engine.fingerprint(event)
        rank = normalize_int(event.get("severity_rank"), 0)
        last_fingerprint = str(state.get("fingerprint") or "")
        last_rank = normalize_int(state.get("severity_rank"), 0)
        last_date = str(state.get("last_date") or "")
        ledger_fingerprint = str(ledger.get("last_payload_hash") or "")
        ledger_rank = normalize_int(ledger.get("severity"), 0)
        ledger_date = str(ledger.get("last_shown_at") or "")[:10]
        last_notified_at = parse_plain_number(state.get("last_notified_at"))
        notify_count = normalize_int(state.get("notify_count"), 0)

        changed = fingerprint != (ledger_fingerprint or last_fingerprint)
        escalated = rank > max(last_rank, ledger_rank)
        cooldown_elapsed = now_ts - last_notified_at >= cooldown
        should_notify = not state or changed or escalated or cooldown_elapsed
        already_today = last_date == today or ledger_date == today
        if once_per_day and already_today and not changed and not escalated:
            should_notify = False

        store.set_alert_state(
            key,
            last_date=today if should_notify else last_date,
            last_notified_at=now_ts if should_notify else last_notified_at,
            last_seen_at=now_ts,
            fingerprint=fingerprint,
            severity_rank=rank,
            status_text=str(event.get("status") or ""),
            notify_count=notify_count + 1 if should_notify else notify_count,
        )
        if should_notify and hasattr(store, "record_notification_ledger"):
            store.record_notification_ledger(
                key,
                state=self.engine.normalized_kind(event),
                severity=rank,
                payload_hash=fingerprint,
            )

        return NotificationDecision(
            should_notify=should_notify,
            key=key,
            changed=changed,
            escalated=escalated,
        )


class NotificationEngine:
    """Smart notification policy and event normalization service."""

    @staticmethod
    def normalized_kind(event: dict | None) -> str:
        data = event if isinstance(event, dict) else {}
        kind = str(data.get('status_kind') or data.get('kind') or '').strip().lower()
        if kind:
            return kind
        text = str(data.get('severity') or data.get('status') or '').strip().lower()
        if any((token in text for token in ('expired', 'overdue', 'مضى'))):
            return ExpiryStatusKind.EXPIRED.value
        if any((token in text for token in ('today', 'اليوم'))):
            return ExpiryStatusKind.EXPIRES_TODAY.value
        if any((token in text for token in ('tomorrow', 'غدا', 'غدًا'))):
            return ExpiryStatusKind.EXPIRES_TOMORROW.value
        if any((token in text for token in ('high', 'critical', 'حرج', 'أعلى'))):
            return ExpiryStatusKind.EXPIRING_HIGH.value
        if any((token in text for token in ('soon', 'warning', 'expiring', 'قريب'))):
            return ExpiryStatusKind.EXPIRING_SOON.value
        if any((token in text for token in ('valid', 'صالح'))):
            return ExpiryStatusKind.VALID.value
        return ExpiryStatusKind.UNKNOWN.value

    @classmethod
    def severity_rank(cls, event: dict) -> int:
        explicit = event.get('severity_rank')
        try:
            if explicit is not None:
                return int(explicit)
        except (TypeError, ValueError):
            return int(_URGENT_ORDER.get(cls.normalized_kind(event), 0))
        return int(_URGENT_ORDER.get(cls.normalized_kind(event), 0))

    @staticmethod
    def alert_key(event: dict) -> str:
        data = event if isinstance(event, dict) else {}
        product_fallback = str(data.get('product_name') or data.get('display_product') or '').strip()
        material = str(data.get('material_number') or product_fallback).strip()
        return '::'.join([str(data.get('branch') or '').strip(), material, str(data.get('production_date') or '').strip(), str(data.get('expiry_date') or '').strip()]).lower()

    @classmethod
    def fingerprint(cls, event: dict) -> str:
        data = event if isinstance(event, dict) else {}
        return '|'.join([str(data.get('branch') or '').strip().lower(), str(data.get('material_number') or '').strip().lower(), str(data.get('product_name') or '').strip().lower(), str(data.get('production_date') or '').strip().lower(), str(data.get('expiry_date') or '').strip().lower(), str(data.get('quantity') or 0), cls.normalized_kind(data), str(cls.severity_rank(data)), str(data.get('days_remaining') or ''), str(data.get('days_expired') or '')])

    @staticmethod
    def days_remaining_text(days_remaining: int) -> str:
        try:
            days = int(days_remaining)
        except (TypeError, ValueError):
            days = 0
        if days < 0:
            return format_days_text(abs(days), expired=True)
        return format_days_text(days, expired=False)

    @staticmethod
    def is_notifiable_source(event: dict | None) -> bool:
        if not isinstance(event, dict):
            return False
        source = str(event.get('source') or '').strip().lower()
        if source in _ALLOWED_SOURCES:
            return True
        if source in _REJECTED_SOURCES:
            return False
        return False

    @classmethod
    def is_notifiable_status(cls, event: dict | None) -> bool:
        kind = cls.normalized_kind(event)
        return kind not in {ExpiryStatusKind.VALID.value, ExpiryStatusKind.UNKNOWN.value}

    @classmethod
    def is_summary_preferred(cls, event: dict | None) -> bool:
        """Return True only for low-priority soon alerts that may be grouped.

        Urgent expiry states must remain visible as individual Windows/tray
        notifications.  This prevents a large batch of soon alerts from hiding
        expired/today/tomorrow items inside a summary.
        """
        return cls.normalized_kind(event) == ExpiryStatusKind.EXPIRING_SOON.value

    @classmethod
    def sort_key(cls, event: dict | None) -> tuple[int, int, str]:
        data = event if isinstance(event, dict) else {}
        return (cls.severity_rank(data), _URGENT_ORDER.get(cls.normalized_kind(data), 0), str(data.get('expiry_date') or ''))

    @classmethod
    def sound_setting_key(cls, event_or_status: dict | str | None) -> str:
        data = event_or_status if isinstance(event_or_status, dict) else {'status': event_or_status or ''}
        kind = cls.normalized_kind(data)
        if kind == ExpiryStatusKind.EXPIRED.value:
            return 'notification_sound_expired'
        if kind == ExpiryStatusKind.EXPIRES_TODAY.value:
            return 'notification_sound_today'
        if kind in {ExpiryStatusKind.EXPIRES_TOMORROW.value, ExpiryStatusKind.EXPIRING_HIGH.value}:
            return 'notification_sound_critical'
        if kind == ExpiryStatusKind.EXPIRING_SOON.value:
            return 'notification_sound_soon'
        return 'notification_sound_default'

    @classmethod
    def history_entry(cls, event: dict) -> dict:
        rd_ = event.get('days_remaining')
        try:
            rd_int = int(rd_ or 0)
        except (TypeError, ValueError):
            rd_int = 0
        return {'title': str(event.get('title') or tr('notification.expiry.item_title')), 'message': str(event.get('message') or ''), 'product': str(event.get('product_name') or event.get('display_product') or ''), 'status': str(event.get('status') or ''), 'status_label': str(event.get('status') or ''), 'status_kind': cls.normalized_kind(event), 'severity_rank': cls.severity_rank(event), 'days_remaining': normalize_int(event.get('days_remaining'), rd_int), 'days_expired': normalize_int(event.get('days_expired'), abs(rd_int) if rd_int < 0 else 0), 'days_text': str(event.get('detail_text') or cls.days_remaining_text(rd_int)), 'branch': str(event.get('branch') or ''), 'branch_name': str(event.get('branch_name') or ''), 'branch_label': str(event.get('branch_label') or ''), 'store': str(event.get('store') or ''), 'store_name': str(event.get('store_name') or ''), 'region': str(event.get('region') or ''), 'area': str(event.get('area') or ''), 'material_number': str(event.get('material_number') or ''), 'quantity': normalize_int(event.get('quantity'), 0), 'production_date': str(event.get('production_date') or ''), 'expiry_date': str(event.get('expiry_date') or ''), 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'), 'read': False}

    @classmethod
    def history_key(cls, entry: dict | None) -> str:
        data = entry if isinstance(entry, dict) else {}
        return '|'.join([str(data.get('title') or '').strip().lower(), str(data.get('product') or '').strip().lower(), str(data.get('branch') or '').strip().lower(), str(data.get('material_number') or '').strip().lower(), str(data.get('production_date') or '').strip().lower(), str(data.get('expiry_date') or '').strip().lower(), str(data.get('status') or '').strip().lower(), str(data.get('days_text') or '').strip().lower()])

    @classmethod
    def build_event(cls, product_name: str, qty: int, st_text: str, rd_: int, branch: str='', material_number: str='', production_date: str='', expiry_date: str='', severity: str | None=None, source: str='local', severity_rank: int | None=None, store: str='', store_name: str='', branch_name: str='', branch_label: str='', region: str='', area: str='') -> dict:
        branch = str(branch or '').strip()
        product_name = str(product_name or '').strip()
        kind = cls.normalized_kind({'severity': severity or st_text, 'status': st_text})
        display_product = f'[{branch}] {product_name}' if branch else product_name
        days_value = normalize_int(rd_, 0)
        days_text = cls.days_remaining_text(days_value)
        status_text = str(st_text or '').strip()
        title_key = 'notification.expiry.urgent_title' if _URGENT_ORDER.get(kind, 0) >= 5 else 'notification.expiry.item_title'
        body_key = 'notification.expiry.urgent_body' if _URGENT_ORDER.get(kind, 0) >= 5 else 'notification.expiry.item_body'
        message = tr(body_key, product=display_product or product_name, status=status_text, detail=days_text)
        event = {'title': tr(title_key), 'product_name': product_name, 'display_product': display_product, 'quantity': normalize_int(qty, 0), 'status': status_text, 'status_kind': kind, 'days_remaining': days_value, 'days_expired': abs(days_value) if days_value < 0 else 0, 'detail_text': days_text, 'branch': branch, 'branch_name': str(branch_name or '').strip(), 'branch_label': str(branch_label or '').strip(), 'store': str(store or '').strip(), 'store_name': str(store_name or store or '').strip(), 'region': str(region or '').strip(), 'area': str(area or '').strip(), 'material_number': str(material_number or product_name or '').strip(), 'production_date': str(production_date or '').strip(), 'expiry_date': str(expiry_date or '').strip(), 'message': message, 'source': source, 'source_category': source, 'severity': str(severity or kind or '')}
        event['severity_rank'] = int(severity_rank) if severity_rank is not None else cls.severity_rank(event)
        return event

class NotificationsStateService:

    @staticmethod
    def normalize(items: list[Any] | tuple[Any, ...] | None) -> list[dict]:
        normalized: list[dict] = []
        for item in list(items or []):
            if isinstance(item, dict):
                normalized.append(deepcopy(item))
            else:
                normalized.append({'message': str(item)})
        return normalized

    @classmethod
    def unread_count(cls, items: list[Any] | tuple[Any, ...] | None) -> int:
        return sum((1 for item in cls.normalize(items) if not parse_bool(item.get('read'), False)))

    @classmethod
    def mark_one_read(cls, items: list[Any] | tuple[Any, ...] | None, index: int) -> tuple[list[dict], bool]:
        normalized = cls.normalize(items)
        if index < 0 or index >= len(normalized):
            return (normalized, False)
        if parse_bool(normalized[index].get('read'), False):
            return (normalized, False)
        normalized[index]['read'] = True
        return (normalized, True)

    @classmethod
    def mark_all_read(cls, items: list[Any] | tuple[Any, ...] | None) -> tuple[list[dict], bool]:
        normalized = cls.normalize(items)
        changed = False
        for item in normalized:
            if not parse_bool(item.get('read'), False):
                item['read'] = True
                changed = True
        return (normalized, changed)

    @staticmethod
    def clear() -> list[dict]:
        return []
