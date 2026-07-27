from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

from runtime.application.services.expiry_status import (
    ExpiryStatusKind,
    ExpiryThresholds,
    classify_expiry_days,
)
from runtime.application.services.notifications import NotificationEngine
from runtime.shared.settings.config import (
    APP_DESKTOP_APP_ID,
    APP_DISPLAY_NAME,
    NOTIFICATION_SOUND_DIR_RELATIVE_PATH,
    resource_path,
)
from runtime.shared.settings.paths_contract import (
    assert_runtime_path_contract,
    installed_executable,
    installed_root,
    roaming_root,
)
from runtime.shared.settings.version import __version__ as APP_VERSION

_SOUND_FILES = {
    "default": "default.wav",
    "expired": "expired.wav",
    "today": "expires_today.wav",
    "critical": "expiry_critical.wav",
    "soon": "expiry_soon.wav",
}

_THRESHOLD_CASES = {
    None: ExpiryStatusKind.UNKNOWN,
    8: ExpiryStatusKind.VALID,
    7: ExpiryStatusKind.EXPIRING_SOON,
    3: ExpiryStatusKind.EXPIRING_SOON,
    2: ExpiryStatusKind.EXPIRING_HIGH,
    1: ExpiryStatusKind.EXPIRES_TOMORROW,
    0: ExpiryStatusKind.EXPIRES_TODAY,
    -1: ExpiryStatusKind.EXPIRED,
}

_SOUND_CASES = {
    ExpiryStatusKind.UNKNOWN: "notification_sound_default",
    ExpiryStatusKind.VALID: "notification_sound_default",
    ExpiryStatusKind.EXPIRING_SOON: "notification_sound_soon",
    ExpiryStatusKind.EXPIRING_HIGH: "notification_sound_critical",
    ExpiryStatusKind.EXPIRES_TOMORROW: "notification_sound_critical",
    ExpiryStatusKind.EXPIRES_TODAY: "notification_sound_today",
    ExpiryStatusKind.EXPIRED: "notification_sound_expired",
}


def _emit(text: str) -> None:
    stream = getattr(sys, "stdout", None)
    if stream is not None:
        with suppress(OSError, RuntimeError, TypeError, ValueError):
            stream.write(text)
            stream.flush()


def _write_file(path: str | os.PathLike[str], text: str) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _sound_checks() -> tuple[dict[str, dict[str, Any]], list[str]]:
    checks: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for label, filename in _SOUND_FILES.items():
        path = Path(resource_path(*NOTIFICATION_SOUND_DIR_RELATIVE_PATH, filename))
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
        header = b""
        if exists:
            with path.open("rb") as handle:
                header = handle.read(12)
        is_wave = bool(
            len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
        )
        checks[label] = {
            "filename": filename,
            "path": str(path),
            "exists": exists,
            "size": size,
            "wave_header": is_wave,
        }
        if not exists or size <= 44 or not is_wave:
            errors.append(f"sound:{filename}")
    return checks, errors


def _threshold_checks() -> tuple[dict[str, dict[str, Any]], list[str]]:
    checks: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for days, expected in _THRESHOLD_CASES.items():
        result = classify_expiry_days(
            days,
            expiring_soon_threshold=7,
            critical_threshold=2,
        )
        key = "none" if days is None else str(days)
        checks[key] = {
            "expected": expected.value,
            "actual": result.kind.value,
            "severity_rank": result.severity_rank,
            "should_notify": result.should_notify_default,
        }
        if result.kind != expected:
            errors.append(
                f"threshold:{key}:expected={expected.value}:actual={result.kind.value}"
            )
    return checks, errors


class _ThresholdSettings:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


def _settings_threshold_checks() -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    policy = ExpiryThresholds.from_settings(
        _ThresholdSettings(
            {
                "expiry_expiring_soon_threshold_days": "10",
                "expiry_critical_threshold_days": "3",
            }
        )
    )
    expected = {
        11: ExpiryStatusKind.VALID,
        10: ExpiryStatusKind.EXPIRING_SOON,
        4: ExpiryStatusKind.EXPIRING_SOON,
        3: ExpiryStatusKind.EXPIRING_HIGH,
        2: ExpiryStatusKind.EXPIRING_HIGH,
        1: ExpiryStatusKind.EXPIRES_TOMORROW,
        0: ExpiryStatusKind.EXPIRES_TODAY,
        -1: ExpiryStatusKind.EXPIRED,
    }
    classifications: dict[str, str] = {}
    if policy.soon_days != 10 or policy.critical_days != 3:
        errors.append(
            "settings_thresholds:"
            f"soon={policy.soon_days}:critical={policy.critical_days}"
        )
    for days, expected_kind in expected.items():
        actual = classify_expiry_days(
            days,
            expiring_soon_threshold=policy.soon_days,
            critical_threshold=policy.critical_days,
        ).kind
        classifications[str(days)] = actual.value
        if actual != expected_kind:
            errors.append(
                "settings_threshold:"
                f"days={days}:expected={expected_kind.value}:actual={actual.value}"
            )
    return (
        {
            "soon_days": policy.soon_days,
            "critical_days": policy.critical_days,
            "classifications": classifications,
        },
        errors,
    )


def _sound_route_checks() -> tuple[dict[str, dict[str, str]], list[str]]:
    checks: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for kind, expected_key in _SOUND_CASES.items():
        actual_key = NotificationEngine.sound_setting_key({"status_kind": kind.value})
        checks[kind.value] = {
            "expected": expected_key,
            "actual": actual_key,
        }
        if actual_key != expected_key:
            errors.append(
                f"sound_route:{kind.value}:expected={expected_key}:actual={actual_key}"
            )
    return checks, errors


def _path_checks() -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        assert_runtime_path_contract()
        contract_ok = True
        contract_error = ""
    except (OSError, RuntimeError, ValueError) as exc:
        contract_ok = False
        contract_error = f"{type(exc).__name__}: {exc}"
        errors.append("path_contract")

    runtime_root = roaming_root().resolve()
    install_root = installed_root().resolve()
    executable = installed_executable().resolve()
    previous_root = None
    previous_exists = False
    if sys.platform.startswith("win"):
        local_base = str(os.environ.get("LOCALAPPDATA") or "").strip()
        if local_base:
            previous_root = Path(local_base) / "HerfyClient"
            previous_exists = previous_root.exists()
    if sys.platform.startswith("win"):
        normalized = str(runtime_root).replace("/", "\\").lower()
        if "\\appdata\\roaming\\herfyclient" not in normalized:
            errors.append("roaming_root")

    return (
        {
            "contract_ok": contract_ok,
            "contract_error": contract_error,
            "roaming_root": str(runtime_root),
            "install_root": str(install_root),
            "installed_executable": str(executable),
            "separate_roots": runtime_root != install_root,
            "previous_localappdata_root": str(previous_root or ""),
            "previous_localappdata_exists": previous_exists,
        },
        errors,
    )


def _qt_checks() -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    result: dict[str, Any] = {}
    previous_platform = os.environ.get("QT_QPA_PLATFORM")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt5.QtCore import QLibraryInfo
        from PyQt5.QtPrintSupport import QPrinter
        from PyQt5.QtWidgets import QApplication, QSystemTrayIcon

        app = QApplication.instance()
        created_app = app is None
        if app is None:
            app = QApplication([APP_DISPLAY_NAME, "--notification-self-check"])

        plugin_path = QLibraryInfo.location(QLibraryInfo.PluginsPath)
        multimedia_available = False
        multimedia_error = ""
        try:
            from PyQt5.QtMultimedia import QMediaPlayer

            media_player = QMediaPlayer()
            multimedia_available = media_player is not None
            media_player.stop()
        except (
            AttributeError,
            ImportError,
            ModuleNotFoundError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            multimedia_error = f"{type(exc).__name__}: {exc}"

        result = {
            "imports_ok": True,
            "created_application": created_app,
            "platform": os.environ.get("QT_QPA_PLATFORM", ""),
            "plugins_path": plugin_path,
            "plugins_path_exists": Path(plugin_path).is_dir(),
            "tray_class_available": QSystemTrayIcon is not None,
            "tray_available": bool(QSystemTrayIcon.isSystemTrayAvailable()),
            "tray_messages_supported": bool(QSystemTrayIcon.supportsMessages()),
            "multimedia_player_available": multimedia_available,
            "multimedia_error": multimedia_error,
            "print_support_available": QPrinter is not None,
        }
        if not result["plugins_path_exists"]:
            errors.append("qt_plugins_path")
        if not result["tray_class_available"]:
            errors.append("qt_tray_class")
        if sys.platform.startswith("win") and not multimedia_available:
            errors.append("qt_multimedia")
        if not result["print_support_available"]:
            errors.append("qt_print_support")
    except (
        AttributeError,
        ImportError,
        ModuleNotFoundError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        result = {
            "imports_ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        errors.append("qt_runtime")
    finally:
        if previous_platform is None:
            os.environ.pop("QT_QPA_PLATFORM", None)
        else:
            os.environ["QT_QPA_PLATFORM"] = previous_platform
    return result, errors


def notification_self_check_payload() -> dict[str, Any]:
    sound_files, sound_errors = _sound_checks()
    thresholds, threshold_errors = _threshold_checks()
    settings_thresholds, settings_threshold_errors = _settings_threshold_checks()
    sound_routes, route_errors = _sound_route_checks()
    paths, path_errors = _path_checks()
    qt, qt_errors = _qt_checks()

    winsound_available: bool | None = None
    if sys.platform.startswith("win"):
        winsound_available = importlib.util.find_spec("winsound") is not None
        if not winsound_available:
            qt_errors.append("winsound")

    errors = [
        *sound_errors,
        *threshold_errors,
        *settings_threshold_errors,
        *route_errors,
        *path_errors,
        *qt_errors,
    ]
    return {
        "status": "ok" if not errors else "failed",
        "verification_scope": "windows_notification_runtime_contract",
        "version": APP_VERSION,
        "frozen": bool(getattr(sys, "frozen", False)),
        "platform": sys.platform,
        "executable": sys.executable,
        "sound_files": sound_files,
        "thresholds": thresholds,
        "settings_thresholds": settings_thresholds,
        "sound_routes": sound_routes,
        "paths": paths,
        "qt": qt,
        "winsound_available": winsound_available,
        "errors": errors,
    }


def run_notification_self_check(output_file: str | None = None) -> int:
    payload = notification_self_check_payload()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _emit(text)
    if output_file:
        _write_file(output_file, text)
    return 0 if payload.get("status") == "ok" else 1


def _set_windows_app_id() -> None:
    if not sys.platform.startswith("win"):
        return
    with suppress(AttributeError, OSError):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_DESKTOP_APP_ID
        )


def run_notification_demo() -> int:
    if not sys.platform.startswith("win"):
        _emit("Notification demo is available only on Windows.\n")
        return 2

    os.environ.pop("QT_QPA_PLATFORM", None)
    try:
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication, QSystemTrayIcon

        from runtime.presentation.dialogs.sound import SoundNotifier
        from runtime.presentation.widgets import app_icon

        _set_windows_app_id()
        app = QApplication.instance() or QApplication(
            [APP_DISPLAY_NAME, "--notification-demo"]
        )
        app.setApplicationName(APP_DISPLAY_NAME)
        app.setOrganizationName("Herfy")
        app.setDesktopFileName(APP_DESKTOP_APP_ID)

        if not QSystemTrayIcon.isSystemTrayAvailable():
            _emit("Windows system tray is unavailable.\n")
            return 3

        tray = QSystemTrayIcon(app_icon(), app)
        tray.setToolTip(APP_DISPLAY_NAME)
        tray.show()

        sound = SoundNotifier(lambda key, default=None: default)
        sound.play({"status_kind": ExpiryStatusKind.EXPIRES_TODAY.value})

        tray.showMessage(
            APP_DISPLAY_NAME,
            (
                "Notification test: expiry thresholds, tray identity, "
                "and sound are working."
            ),
            app_icon(),
            7000,
        )
        QTimer.singleShot(8000, app.quit)
        exit_code = int(app.exec_())
        sound.stop()
        tray.hide()
        return exit_code
    except (
        AttributeError,
        ImportError,
        ModuleNotFoundError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        _emit(f"Notification demo failed: {type(exc).__name__}: {exc}\n")
        return 1
