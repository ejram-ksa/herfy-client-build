from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any
from runtime.shared.errors import PARSE_OPERATION_EXCEPTIONS
from runtime.application.services.translations import format_days_text as _format_days_text
from runtime.application.services.translations import tr

class ExpiryStatusKind(str, Enum):
    UNKNOWN = 'unknown'
    VALID = 'valid'
    EXPIRING_SOON = 'expiring_soon'
    EXPIRING_HIGH = 'expiring_high'
    EXPIRES_TOMORROW = 'expires_tomorrow'
    EXPIRES_TODAY = 'expires_today'
    EXPIRED = 'expired'

class ExpirySeverity(int, Enum):
    UNKNOWN = 0
    VALID = 1
    EXPIRING_SOON = 2
    EXPIRING_HIGH = 3
    EXPIRES_TOMORROW = 4
    EXPIRES_TODAY = 5
    EXPIRED = 6

@dataclass(frozen=True, slots=True)
class ExpiryStatusResult:
    kind: ExpiryStatusKind
    severity_rank: int
    days_remaining: int | None
    days_expired: int | None
    label_key: str
    detail_key: str
    label_text: str
    detail_text: str
    color_token: str
    icon_token: str
    should_notify_default: bool
    notification_priority: str
    sort_weight: int

    @property
    def display_text(self) -> str:
        if self.kind in {ExpiryStatusKind.UNKNOWN, ExpiryStatusKind.VALID, ExpiryStatusKind.EXPIRES_TODAY}:
            return self.label_text
        if self.kind == ExpiryStatusKind.EXPIRED:
            return self.detail_text
        if self.detail_text and self.detail_text != self.label_text:
            return f'{self.label_text} — {self.detail_text}'
        return self.label_text
_KIND_META = {ExpiryStatusKind.UNKNOWN: (0, 'expiry.status.unknown', 'expiry.detail.unknown', 'gray', 'unknown', False, 'none', 0), ExpiryStatusKind.VALID: (1, 'expiry.status.valid', 'expiry.detail.remaining_days', 'green', 'valid', False, 'none', 10), ExpiryStatusKind.EXPIRING_SOON: (2, 'expiry.status.expiring_soon', 'expiry.detail.remaining_days', 'amber', 'soon', True, 'low', 20), ExpiryStatusKind.EXPIRING_HIGH: (3, 'expiry.status.expiring_high', 'expiry.detail.remaining_days', 'orange', 'high', True, 'medium', 30), ExpiryStatusKind.EXPIRES_TOMORROW: (4, 'expiry.status.expires_tomorrow', 'expiry.detail.remaining_day', 'deep_orange', 'tomorrow', True, 'high', 40), ExpiryStatusKind.EXPIRES_TODAY: (5, 'expiry.status.expires_today', 'expiry.detail.expires_today', 'red', 'today', True, 'urgent', 50), ExpiryStatusKind.EXPIRED: (6, 'expiry.status.expired', 'expiry.detail.expired_days_ago', 'dark_red', 'expired', True, 'urgent', 60)}
_COLOR_BY_TOKEN = {'gray': '#7A869A', 'green': '#138A43', 'amber': '#B7791F', 'orange': '#DD6B20', 'deep_orange': '#C05621', 'red': '#D62828', 'dark_red': '#8B1E1E'}

def parse_expiry_date(value: Any) -> date | None:
    text = str(value or '').strip()
    if not text:
        return None
    for raw_candidate in (text[:10], text):
        candidate = raw_candidate.strip()
        if not candidate:
            continue
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m-%d-%Y', '%Y/%m/%d'):
            try:
                return datetime.strptime(candidate, fmt).date()
            except PARSE_OPERATION_EXCEPTIONS:
                continue
    return None

def _normalize_thresholds(expiring_soon_threshold: int=7, critical_threshold: int=2) -> tuple[int, int]:
    try:
        soon = int(expiring_soon_threshold)
    except (TypeError, ValueError):
        soon = 7
    try:
        critical = int(critical_threshold)
    except (TypeError, ValueError):
        critical = 2
    soon = max(3, min(60, soon))
    critical = max(1, min(soon, critical))
    return (soon, critical)

def _result(kind: ExpiryStatusKind, days_remaining: int | None, days_expired: int | None) -> ExpiryStatusResult:
    severity, label_key, detail_key, color, icon, should_notify, priority, sort_weight = _KIND_META[kind]
    label = tr(label_key)
    if kind == ExpiryStatusKind.UNKNOWN:
        detail = tr('expiry.detail.unknown')
    elif kind == ExpiryStatusKind.EXPIRED:
        detail = _format_days_text(days_expired, expired=True)
    elif kind == ExpiryStatusKind.EXPIRES_TODAY:
        detail = tr('expiry.detail.expires_today')
    else:
        detail = _format_days_text(days_remaining, expired=False)
    return ExpiryStatusResult(kind=kind, severity_rank=int(severity), days_remaining=days_remaining, days_expired=days_expired, label_key=label_key, detail_key=detail_key, label_text=label, detail_text=detail, color_token=color, icon_token=icon, should_notify_default=should_notify, notification_priority=priority, sort_weight=sort_weight)

def classify_expiry_days(days_remaining: int | None, *, expiring_soon_threshold: int=7, critical_threshold: int=2) -> ExpiryStatusResult:
    soon, critical = _normalize_thresholds(expiring_soon_threshold, critical_threshold)
    if days_remaining is None:
        return _result(ExpiryStatusKind.UNKNOWN, None, None)
    days = int(days_remaining)
    if days > soon:
        return _result(ExpiryStatusKind.VALID, days, None)
    if critical < days <= soon:
        return _result(ExpiryStatusKind.EXPIRING_SOON, days, None)
    if 2 <= days <= critical:
        return _result(ExpiryStatusKind.EXPIRING_HIGH, days, None)
    if days == 1:
        return _result(ExpiryStatusKind.EXPIRES_TOMORROW, days, None)
    if days == 0:
        return _result(ExpiryStatusKind.EXPIRES_TODAY, days, None)
    return _result(ExpiryStatusKind.EXPIRED, days, abs(days))

def classify_expiry_date(expiry_value: Any, *, today: date | None=None, expiring_soon_threshold: int=7, critical_threshold: int=2) -> ExpiryStatusResult:
    expiry = parse_expiry_date(expiry_value)
    if expiry is None:
        return classify_expiry_days(None, expiring_soon_threshold=expiring_soon_threshold, critical_threshold=critical_threshold)
    current_day = today or date.today()
    return classify_expiry_days((expiry - current_day).days, expiring_soon_threshold=expiring_soon_threshold, critical_threshold=critical_threshold)
EXPIRY_DATE_FIELD_ALIASES = ('expiry_date', 'expiration_date', 'exp_date', 'expiryDate', 'expirationDate', 'expiry')

@dataclass(frozen=True, slots=True)
class ExpiryThresholds:
    soon_days: int = 7
    critical_days: int = 2
    recent_expired_days: int = 0

    @classmethod
    def from_settings(cls, settings_source: Any | None) -> 'ExpiryThresholds':

        def read_int(key: str, default: int) -> int:
            try:
                if settings_source is None:
                    return int(default)
                getter = getattr(settings_source, 'get_setting', None)
                if callable(getter):
                    return int(getter(key, str(default)))
            except (TypeError, ValueError, RuntimeError, AttributeError):
                return int(default)
            return int(default)
        soon = read_int('expiry_expiring_soon_threshold_days', read_int('expiring_soon_threshold', 7))
        critical = read_int('expiry_critical_threshold_days', read_int('critical_threshold', 2))
        recent = read_int('recently_expired_threshold', 0)
        soon = max(3, min(60, int(soon)))
        critical = max(1, min(soon, int(critical)))
        recent = max(0, min(3650, int(recent)))
        return cls(soon_days=soon, critical_days=critical, recent_expired_days=recent)

@dataclass(frozen=True, slots=True)
class ExpiryStatus:
    key: str
    label: str
    detail: str
    display_text: str
    severity: str
    severity_rank: int
    progress: int
    days_left: int | None
    should_notify: bool

    @property
    def is_expired(self) -> bool:
        return bool(self.days_left is not None and self.days_left < 0)

def _day_word(days: int) -> str:
    return tr('day') if abs(int(days)) == 1 else tr('days')

def days_remaining_phrase(days_left: int) -> str:
    days_left = int(days_left)
    if days_left < 0:
        overdue = abs(days_left)
        return tr('Expired {days} {day_word} ago').format(days=overdue, day_word=_day_word(overdue))
    if days_left == 0:
        return tr('Expires today')
    return tr('Expires in {days} {day_word}').format(days=days_left, day_word=_day_word(days_left))

def expires_after_phrase(days_left: int) -> str:
    days_left = max(1, int(days_left))
    return tr('Expires after {days} {day_word}').format(days=days_left, day_word=_day_word(days_left))

def format_days_text(result_or_days: ExpiryStatusResult | int | None, *, expired: bool | None=None) -> str:
    if isinstance(result_or_days, ExpiryStatusResult):
        return result_or_days.detail_text
    return _format_days_text(result_or_days, expired=bool(expired))

def format_expiry_status_text(result: ExpiryStatusResult) -> str:
    return result.display_text

def row_expiry_value(row: Mapping[str, Any] | None) -> str:
    data = row if isinstance(row, Mapping) else {}
    for key in EXPIRY_DATE_FIELD_ALIASES:
        value = data.get(key)
        if value not in (None, ''):
            return str(value).strip()
    return ''

def _status_from_result(result: ExpiryStatusResult, thresholds: ExpiryThresholds | None=None) -> ExpiryStatus:
    th = thresholds or ExpiryThresholds()
    progress = expiry_progress_percent(result, expiring_soon_threshold=th.soon_days, critical_threshold=th.critical_days)
    severity_by_kind = {ExpiryStatusKind.UNKNOWN: 'neutral', ExpiryStatusKind.VALID: 'valid', ExpiryStatusKind.EXPIRING_SOON: 'warning', ExpiryStatusKind.EXPIRING_HIGH: 'critical', ExpiryStatusKind.EXPIRES_TOMORROW: 'critical', ExpiryStatusKind.EXPIRES_TODAY: 'today', ExpiryStatusKind.EXPIRED: 'expired'}
    key_by_kind = {ExpiryStatusKind.UNKNOWN: 'missing_expiry', ExpiryStatusKind.VALID: 'valid', ExpiryStatusKind.EXPIRING_SOON: 'expiring_soon', ExpiryStatusKind.EXPIRING_HIGH: 'expiring_high', ExpiryStatusKind.EXPIRES_TOMORROW: 'expires_tomorrow', ExpiryStatusKind.EXPIRES_TODAY: 'expires_today', ExpiryStatusKind.EXPIRED: 'expired'}
    return ExpiryStatus(key=key_by_kind.get(result.kind, 'missing_expiry'), label=result.label_text, detail=result.detail_text, display_text=result.display_text, severity=severity_by_kind.get(result.kind, 'neutral'), severity_rank=result.severity_rank, progress=progress, days_left=result.days_remaining, should_notify=result.should_notify_default)

def classify_days(days_left: int | None, thresholds: ExpiryThresholds | None=None) -> ExpiryStatus:
    th = thresholds or ExpiryThresholds()
    return _status_from_result(classify_expiry_days(days_left, expiring_soon_threshold=th.soon_days, critical_threshold=th.critical_days), th)

def classify_tracking_row(row: Mapping[str, Any] | None, thresholds: ExpiryThresholds | None=None) -> ExpiryStatus:
    th = thresholds or ExpiryThresholds()
    return _status_from_result(classify_expiry_date(row_expiry_value(row), expiring_soon_threshold=th.soon_days, critical_threshold=th.critical_days), th)

def get_expiry_visual_token(kind_or_result: ExpiryStatusKind | ExpiryStatusResult | str) -> dict[str, str]:
    kind: ExpiryStatusKind
    if isinstance(kind_or_result, ExpiryStatusResult):
        kind = kind_or_result.kind
    else:
        try:
            kind = ExpiryStatusKind(str(kind_or_result))
        except ValueError:
            kind = ExpiryStatusKind.UNKNOWN
    color_token = _KIND_META[kind][3]
    icon_token = _KIND_META[kind][4]
    return {'color_token': color_token, 'color': _COLOR_BY_TOKEN.get(color_token, '#7A869A'), 'icon_token': icon_token}

def expiry_progress_percent(kind_or_result: ExpiryStatusKind | ExpiryStatusResult | str, *, days_remaining: int | None=None, expiring_soon_threshold: int=7, critical_threshold: int=2) -> int:
    """Return a countdown progress percentage based on remaining days.

    The percentage intentionally decreases as the expiry date gets closer:
    valid items remain full, soon items decrease through the soon window,
    critical/tomorrow items drop further, and today/expired/unknown are zero.
    """
    if isinstance(kind_or_result, ExpiryStatusResult):
        kind = kind_or_result.kind
        days = kind_or_result.days_remaining
    else:
        try:
            kind = ExpiryStatusKind(str(kind_or_result))
        except ValueError:
            kind = ExpiryStatusKind.UNKNOWN
        days = days_remaining
    soon, critical = _normalize_thresholds(expiring_soon_threshold, critical_threshold)
    try:
        remaining = None if days is None else int(days)
    except (TypeError, ValueError):
        remaining = None
    if kind == ExpiryStatusKind.VALID:
        return 100
    if kind == ExpiryStatusKind.EXPIRING_SOON and remaining is not None:
        span = max(1, soon - critical)
        return max(42, min(90, int(round(42 + 48 * ((remaining - critical) / span)))))
    if kind == ExpiryStatusKind.EXPIRING_HIGH and remaining is not None:
        if critical <= 2:
            return 28 if remaining >= 2 else 18
        return max(18, min(40, int(round(18 + 22 * ((remaining - 2) / max(1, critical - 2))))))
    if kind == ExpiryStatusKind.EXPIRES_TOMORROW:
        return 14
    return 0
