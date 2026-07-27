from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from runtime.shared.booleans import normalize_bool
from runtime.application.services.translations import normalize_language_code

CANONICAL_SETTINGS_DEFAULTS: dict[str, str] = {
    "language": "ar",
    "enable_alerts": "True",
    "enable_tray_background": "True",
    "enable_desktop_notifications": "True",
    "enable_smart_notifications": "True",
    "enable_sounds": "True",
    "expiry_expiring_soon_threshold_days": "7",
    "expiry_critical_threshold_days": "2",
    "expiry_enable_status_colors": "True",
    "expiry_enable_status_icons": "True",
    "notification_once_per_day": "True",
    "notification_repeat_interval_minutes": "240",
    "notification_duration_seconds": "8",
    "notification_max_per_cycle": "5",
    "notification_summary_threshold": "3",
    "monitoring_active_check_interval_minutes": "15",
    "monitoring_background_check_interval_minutes": "30",
    "notification_sound_default": "default.wav",
    "notification_sound_expired": "expired.wav",
    "notification_sound_today": "expires_today.wav",
    "notification_sound_critical": "expiry_critical.wav",
    "notification_sound_soon": "expiry_soon.wav",
}
OLD_TO_CANONICAL_SETTINGS: dict[str, str] = {
    "check_interval": "monitoring_active_check_interval_minutes",
    "background_check_interval": "monitoring_background_check_interval_minutes",
    "notification_duration": "notification_duration_seconds",
    "notification_repeat_interval": "notification_repeat_interval_minutes",
    "summary_notification_threshold": "notification_summary_threshold",
    "max_notifications_per_cycle": "notification_max_per_cycle",
    "expiring_soon_threshold": "expiry_expiring_soon_threshold_days",
    "critical_threshold": "expiry_critical_threshold_days",
    "notification_sound": "notification_sound_default",
}
CANONICAL_ALERT_SETTING_KEYS: tuple[str, ...] = tuple(CANONICAL_SETTINGS_DEFAULTS)


def canonical_default(key: str, default: str = "") -> str:
    return CANONICAL_SETTINGS_DEFAULTS.get(str(key or ""), str(default or ""))


def normalize_int(
    value: Any, default: int, *, minimum: int, maximum: int | None = None
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    parsed = max(int(minimum), parsed)
    if maximum is not None:
        parsed = min(int(maximum), parsed)
    return parsed


def canonicalize_value(key: str, value: Any) -> str:
    key = str(key or "")
    if key == "language":
        return normalize_language_code(
            str(value or CANONICAL_SETTINGS_DEFAULTS["language"])
        )
    if key == "enable_tray_background":
        return "True"
    if key.startswith("enable_") or key in {
        "expiry_enable_status_colors",
        "expiry_enable_status_icons",
        "notification_once_per_day",
    }:
        return (
            "True"
            if normalize_bool(value, normalize_bool(canonical_default(key), False))
            else "False"
        )
    return str(value if value is not None else canonical_default(key))


@dataclass(frozen=True)
class SettingsValidationResult:
    values: dict[str, str]
    errors: dict[str, str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_canonical_settings(values: dict[str, Any]) -> SettingsValidationResult:
    merged = {**CANONICAL_SETTINGS_DEFAULTS, **{str(k): v for k, v in values.items()}}
    errors: dict[str, str] = {}
    result: dict[str, str] = {}
    result["language"] = normalize_language_code(str(merged.get("language") or "ar"))
    result["enable_tray_background"] = "True"
    for key in (
        "enable_alerts",
        "enable_desktop_notifications",
        "enable_smart_notifications",
        "enable_sounds",
        "expiry_enable_status_colors",
        "expiry_enable_status_icons",
        "notification_once_per_day",
    ):
        result[key] = (
            "True"
            if normalize_bool(
                merged.get(key), normalize_bool(CANONICAL_SETTINGS_DEFAULTS[key], True)
            )
            else "False"
        )
    soon = normalize_int(
        merged.get("expiry_expiring_soon_threshold_days"), 7, minimum=3, maximum=60
    )
    raw_critical = merged.get("expiry_critical_threshold_days")
    try:
        requested_critical = int(raw_critical)
    except (TypeError, ValueError):
        requested_critical = 2
    if requested_critical > soon:
        errors["expiry_critical_threshold_days"] = (
            "settings.expiry.validation_threshold"
        )
    critical = normalize_int(
        requested_critical,
        2,
        minimum=1,
        maximum=soon,
    )
    result["expiry_expiring_soon_threshold_days"] = str(soon)
    result["expiry_critical_threshold_days"] = str(critical)
    result["notification_repeat_interval_minutes"] = str(
        normalize_int(
            merged.get("notification_repeat_interval_minutes"),
            240,
            minimum=15,
            maximum=1440,
        )
    )
    result["notification_duration_seconds"] = str(
        normalize_int(
            merged.get("notification_duration_seconds"), 8, minimum=3, maximum=30
        )
    )
    result["notification_max_per_cycle"] = str(
        normalize_int(
            merged.get("notification_max_per_cycle"), 5, minimum=1, maximum=20
        )
    )
    result["notification_summary_threshold"] = str(
        normalize_int(
            merged.get("notification_summary_threshold"), 3, minimum=2, maximum=50
        )
    )
    active = normalize_int(
        merged.get("monitoring_active_check_interval_minutes"),
        15,
        minimum=5,
        maximum=1440,
    )
    background = normalize_int(
        merged.get("monitoring_background_check_interval_minutes"),
        30,
        minimum=5,
        maximum=1440,
    )
    if background < active:
        errors["monitoring_background_check_interval_minutes"] = (
            "settings.monitoring.validation_interval"
        )
        background = active
    result["monitoring_active_check_interval_minutes"] = str(active)
    result["monitoring_background_check_interval_minutes"] = str(background)
    for key in (
        "notification_sound_default",
        "notification_sound_expired",
        "notification_sound_today",
        "notification_sound_critical",
        "notification_sound_soon",
    ):
        result[key] = (
            str(merged.get(key) or CANONICAL_SETTINGS_DEFAULTS[key]).strip()
            or CANONICAL_SETTINGS_DEFAULTS[key]
        )
    return SettingsValidationResult(values=result, errors=errors)
