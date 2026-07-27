from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from runtime.shared.settings.config import normalize_api_base_url
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.booleans import parse_bool
from runtime.application.services.settings_schema import (
    CANONICAL_ALERT_SETTING_KEYS,
    CANONICAL_SETTINGS_DEFAULTS,
    OLD_TO_CANONICAL_SETTINGS,
    validate_canonical_settings,
)
from runtime.application.services.sync import apply_startup_preferences, normalize_startup_preferences
from runtime.application.services.sync import current_api_base_url
from runtime.application.services.translations import normalize_language_code, set_language

ALERT_SETTING_KEYS = CANONICAL_ALERT_SETTING_KEYS


def _bool_text(value: bool) -> str:
    return "True" if bool(value) else "False"


@dataclass(frozen=True, slots=True)
class SettingsState:
    language: str
    enable_alerts: bool
    enable_tray_background: bool
    enable_desktop_notifications: bool
    enable_smart_notifications: bool
    enable_sounds: bool
    expiry_expiring_soon_threshold_days: int
    expiry_critical_threshold_days: int
    expiry_enable_status_colors: bool
    expiry_enable_status_icons: bool
    notification_once_per_day: bool
    notification_repeat_interval_minutes: int
    notification_duration_seconds: int
    notification_max_per_cycle: int
    notification_summary_threshold: int
    monitoring_active_check_interval_minutes: int
    monitoring_background_check_interval_minutes: int
    notification_sound_default: str
    notification_sound_expired: str
    notification_sound_today: str
    notification_sound_critical: str
    notification_sound_soon: str
    server_url: str
    date_format: str = "yyyy-MM-dd"
    usage_hide_total_zero: bool = False
    start_with_windows: bool = False
    tray_show_message_on_minimize: bool = False
    check_updates_on_startup: bool = True
    refresh_remote_ui_on_startup: bool = True
    immediate_server_sync: bool = True
    alert_snapshot: dict[str, str] | None = None

    @property
    def check_interval(self) -> int:
        return self.monitoring_active_check_interval_minutes

    @property
    def background_check_interval(self) -> int:
        return self.monitoring_background_check_interval_minutes

    @property
    def notification_duration(self) -> int:
        return self.notification_duration_seconds

    @property
    def notification_repeat_interval(self) -> int:
        return self.notification_repeat_interval_minutes

    @property
    def summary_notification_threshold(self) -> int:
        return self.notification_summary_threshold

    @property
    def max_notifications_per_cycle(self) -> int:
        return self.notification_max_per_cycle

    @property
    def notification_sound(self) -> str:
        return self.notification_sound_default

    @property
    def expiring_soon_threshold(self) -> int:
        return self.expiry_expiring_soon_threshold_days

    @property
    def critical_threshold(self) -> int:
        return self.expiry_critical_threshold_days

    @property
    def enable_in_app_toasts(self) -> bool:
        return False

    @property
    def recently_expired_threshold(self) -> int:
        return 0


@dataclass(frozen=True, slots=True)
class SettingsSaveResult:
    normalized_server_url: str
    alert_settings_changed: bool
    errors: dict[str, str] | None = None


class SettingsService:

    def __init__(self, db_manager: Any):
        self.db_manager = db_manager

    def _raw_value(self, key: str, default: str = "") -> str:
        try:
            return str(self.db_manager.get_setting(key, default) or default)
        except SERVICE_OPERATION_EXCEPTIONS:
            return str(default or "")

    def _value(self, key: str, default: str = "") -> str:
        canonical_default = CANONICAL_SETTINGS_DEFAULTS.get(key, default)
        value = self._raw_value(key, "")
        if value not in (None, ""):
            return str(value)
        for old_key, new_key in OLD_TO_CANONICAL_SETTINGS.items():
            if new_key == key:
                old_value = self._raw_value(old_key, "")
                if old_value not in (None, ""):
                    return self._convert_old_value(old_key, key, old_value)
        return str(canonical_default)

    @staticmethod
    def _convert_old_value(old_key: str, new_key: str, value: Any) -> str:
        if old_key == "notification_repeat_interval":
            try:
                seconds = int(value)
                return str(max(15, seconds // 60 if seconds > 60 else seconds))
            except (TypeError, ValueError):
                return CANONICAL_SETTINGS_DEFAULTS[new_key]
        if old_key == "notification_duration":
            return str(value)
        return str(value)

    def _bool(self, key: str, default: bool = False) -> bool:
        return parse_bool(self._value(key, _bool_text(default)), default)

    def _int(self, key: str, default: int, *, minimum: int, maximum: int) -> int:
        try:
            value = int(self._value(key, str(default)))
        except ValueError:
            value = int(default)
        return min(max(value, minimum), maximum)

    def current_language(self) -> str:
        return normalize_language_code(self._value("language", "ar"))

    def alert_snapshot(self) -> dict[str, str]:
        return {
            key: self._value(key, CANONICAL_SETTINGS_DEFAULTS.get(key, ""))
            for key in ALERT_SETTING_KEYS
        }

    @staticmethod
    def normalize_server_url(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        normalized = normalize_api_base_url(raw)
        parsed = urlparse(normalized)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("Invalid server URL.")
        return normalized

    def current_server_url(self) -> str:
        try:
            return self.normalize_server_url(current_api_base_url())
        except SERVICE_OPERATION_EXCEPTIONS:
            return str(current_api_base_url() or "").strip()

    def load(self) -> SettingsState:
        validation = validate_canonical_settings(self.alert_snapshot())
        v = validation.values
        set_language(v["language"])
        return SettingsState(
            language=v["language"],
            enable_alerts=parse_bool(v["enable_alerts"], True),
            enable_tray_background=parse_bool(v["enable_tray_background"], True),
            enable_desktop_notifications=parse_bool(
                v["enable_desktop_notifications"], True
            ),
            enable_smart_notifications=parse_bool(
                v["enable_smart_notifications"], True
            ),
            enable_sounds=parse_bool(v["enable_sounds"], True),
            expiry_expiring_soon_threshold_days=int(
                v["expiry_expiring_soon_threshold_days"]
            ),
            expiry_critical_threshold_days=int(v["expiry_critical_threshold_days"]),
            expiry_enable_status_colors=parse_bool(
                v["expiry_enable_status_colors"], True
            ),
            expiry_enable_status_icons=parse_bool(
                v["expiry_enable_status_icons"], True
            ),
            notification_once_per_day=parse_bool(v["notification_once_per_day"], True),
            notification_repeat_interval_minutes=int(
                v["notification_repeat_interval_minutes"]
            ),
            notification_duration_seconds=int(v["notification_duration_seconds"]),
            notification_max_per_cycle=int(v["notification_max_per_cycle"]),
            notification_summary_threshold=int(v["notification_summary_threshold"]),
            monitoring_active_check_interval_minutes=int(
                v["monitoring_active_check_interval_minutes"]
            ),
            monitoring_background_check_interval_minutes=int(
                v["monitoring_background_check_interval_minutes"]
            ),
            notification_sound_default=v["notification_sound_default"],
            notification_sound_expired=v["notification_sound_expired"],
            notification_sound_today=v["notification_sound_today"],
            notification_sound_critical=v["notification_sound_critical"],
            notification_sound_soon=v["notification_sound_soon"],
            date_format=self._raw_value("date_format", "yyyy-MM-dd"),
            usage_hide_total_zero=parse_bool(
                self._raw_value("usage_hide_total_zero", "False"), False
            ),
            start_with_windows=parse_bool(
                self._raw_value("start_with_windows", "False"), False
            ),
            tray_show_message_on_minimize=parse_bool(
                self._raw_value("tray_show_message_on_minimize", "False"), False
            ),
            server_url=self.current_server_url(),
            check_updates_on_startup=parse_bool(
                self._raw_value("check_updates_on_startup", "True"), True
            ),
            refresh_remote_ui_on_startup=parse_bool(
                self._raw_value("refresh_remote_ui_on_startup", "True"), True
            ),
            immediate_server_sync=parse_bool(
                self._raw_value("immediate_server_sync", "True"), True
            ),
            alert_snapshot=dict(v),
        )

    def save(
        self,
        values: Mapping[str, Any],
        *,
        original_alert_snapshot: Mapping[str, str] | None = None,
    ) -> SettingsSaveResult:
        original = dict(original_alert_snapshot or self.alert_snapshot())
        canonical_values = {
            key: values.get(key, self._value(key, default))
            for key, default in CANONICAL_SETTINGS_DEFAULTS.items()
        }
        alias_inputs = {
            "check_interval": "monitoring_active_check_interval_minutes",
            "background_check_interval": "monitoring_background_check_interval_minutes",
            "notification_duration": "notification_duration_seconds",
            "notification_repeat_interval": "notification_repeat_interval_minutes",
            "summary_notification_threshold": "notification_summary_threshold",
            "max_notifications_per_cycle": "notification_max_per_cycle",
            "notification_sound": "notification_sound_default",
            "expiring_soon_threshold": "expiry_expiring_soon_threshold_days",
            "critical_threshold": "expiry_critical_threshold_days",
        }
        for old_key, new_key in alias_inputs.items():
            if old_key in values and new_key not in values:
                val = values[old_key]
                if old_key == "notification_repeat_interval":
                    try:
                        val = max(15, int(val) // 60 if int(val) > 60 else int(val))
                    except (TypeError, ValueError):
                        val = CANONICAL_SETTINGS_DEFAULTS[new_key]
                canonical_values[new_key] = val
        validation = validate_canonical_settings(canonical_values)
        for key, value in validation.values.items():
            self.db_manager.set_setting(key, value)
        side_keys = {
            "date_format": values.get(
                "date_format", self._raw_value("date_format", "yyyy-MM-dd")
            ),
            "usage_hide_total_zero": values.get(
                "usage_hide_total_zero",
                self._raw_value("usage_hide_total_zero", "False"),
            ),
            "start_with_windows": values.get(
                "start_with_windows", self._raw_value("start_with_windows", "False")
            ),
            "tray_show_message_on_minimize": values.get(
                "tray_show_message_on_minimize",
                self._raw_value("tray_show_message_on_minimize", "False"),
            ),
            "check_updates_on_startup": values.get(
                "check_updates_on_startup",
                self._raw_value("check_updates_on_startup", "True"),
            ),
            "refresh_remote_ui_on_startup": values.get(
                "refresh_remote_ui_on_startup",
                self._raw_value("refresh_remote_ui_on_startup", "True"),
            ),
            "immediate_server_sync": values.get(
                "immediate_server_sync",
                self._raw_value("immediate_server_sync", "True"),
            ),
        }
        for key, value in side_keys.items():
            self.db_manager.set_setting(
                key, _bool_text(value) if isinstance(value, bool) else str(value)
            )
        set_language(validation.values["language"])
        server_url = self.current_server_url()
        normalize_startup_preferences(self.db_manager, persist=True)
        apply_startup_preferences(self.db_manager)
        return SettingsSaveResult(
            normalized_server_url=server_url,
            alert_settings_changed=validation.values != original,
            errors=validation.errors,
        )

    def reset_defaults(self) -> SettingsSaveResult:
        return self.save(
            dict(CANONICAL_SETTINGS_DEFAULTS),
            original_alert_snapshot=self.alert_snapshot(),
        )
