from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

from validation_result import format_validation_result
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.dont_write_bytecode = True

_TRANSLATION_CALLS = {"_", "tr", "translate", "tr_for_language"}
_RESOURCE_SUFFIXES = {".png", ".ico", ".wav", ".bmp"}
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_OLD_VERSION_RE = re.compile(r"\b2\.(?:16|17)\.\d+\b")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def qt_available() -> bool:
    return importlib.util.find_spec("PyQt5") is not None


def module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def source_python_files() -> list[Path]:
    """Return importable application runtime modules only.

    Build and verification scripts are executable entry points and may have
    intentional process side effects, so importing them is not a valid runtime
    export check.
    """

    return sorted((ROOT / "runtime").rglob("*.py"))


def import_and_export_contract() -> tuple[int, int, int]:
    imported = 0
    exported = 0
    qt_skipped = 0
    failures: list[str] = []
    qt_is_available = qt_available()
    for path in source_python_files():
        name = module_name(path)
        if not name:
            continue
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if not qt_is_available and str(exc.name or "").startswith("PyQt5"):
                qt_skipped += 1
                continue
            failures.append(f"{name}: import: {type(exc).__name__}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - report every import failure.
            failures.append(f"{name}: import: {type(exc).__name__}: {exc}")
            continue
        imported += 1
        public = getattr(module, "__all__", ())
        if not isinstance(public, (list, tuple)):
            failures.append(f"{name}: __all__ must be a list or tuple")
            continue
        for symbol in public:
            if not isinstance(symbol, str):
                failures.append(f"{name}: invalid export: {symbol!r}")
                continue
            try:
                present = hasattr(module, symbol)
            except ModuleNotFoundError as exc:
                if not qt_is_available and str(exc.name or "").startswith("PyQt5"):
                    qt_skipped += 1
                    break
                failures.append(
                    f"{name}: export {symbol}: {type(exc).__name__}: {exc}"
                )
                break
            if not present:
                failures.append(f"{name}: missing export: {symbol!r}")
            else:
                exported += 1
    require(
        not failures, "Import/export contract failed:\n - " + "\n - ".join(failures)
    )
    return imported, exported, qt_skipped


def load_catalog(language: str) -> dict[str, str]:
    path = ROOT / "runtime" / "resources" / "i18n" / f"{language}.json"
    duplicates: list[str] = []

    def object_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                duplicates.append(str(key))
            value[key] = item
        return value

    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=object_hook,
    )
    require(not duplicates, f"Duplicate translation keys in {path}: {duplicates}")
    require(isinstance(payload, dict), f"Invalid translation catalog: {path}")
    return {str(key): str(value) for key, value in payload.items()}


def literal_translation_keys() -> set[str]:
    keys: set[str] = set()
    for path in sorted(ROOT.rglob("*.py")):
        if path.relative_to(ROOT).parts[0] == "release":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = ""
            if isinstance(node.func, ast.Name):
                function_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                function_name = node.func.attr
            if function_name not in _TRANSLATION_CALLS:
                continue
            index = 1 if function_name == "tr_for_language" else 0
            if len(node.args) <= index:
                continue
            argument = node.args[index]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                keys.add(" ".join(argument.value.split()))
    return keys


def translation_contract() -> tuple[int, int]:
    arabic = load_catalog("ar")
    english = load_catalog("en")
    require(set(arabic) == set(english), "Arabic/English key sets are different")

    placeholder_failures: list[str] = []
    for key in sorted(arabic):
        ar_placeholders = set(_PLACEHOLDER_RE.findall(arabic[key]))
        en_placeholders = set(_PLACEHOLDER_RE.findall(english[key]))
        if ar_placeholders != en_placeholders:
            placeholder_failures.append(
                f"{key}: ar={sorted(ar_placeholders)} en={sorted(en_placeholders)}"
            )
    require(
        not placeholder_failures,
        "Translation placeholder mismatch:\n - " + "\n - ".join(placeholder_failures),
    )

    literal_keys = literal_translation_keys()
    missing = sorted(key for key in literal_keys if key not in arabic)
    require(
        not missing,
        "Literal translation keys are missing:\n - " + "\n - ".join(missing),
    )
    return len(arabic), len(literal_keys)


def resource_contract() -> int:
    available = {
        path.name.casefold()
        for path in ROOT.rglob("*")
        if path.is_file() and path.suffix.casefold() in _RESOURCE_SUFFIXES
    }
    references: set[str] = set()
    missing: list[str] = []

    def inspect_value(path: Path, value: str) -> None:
        normalized = str(value or "").strip().replace("\\", "/")
        candidate = normalized.split("/")[-1]
        if not candidate or Path(candidate).suffix.casefold() not in _RESOURCE_SUFFIXES:
            return
        references.add(candidate)
        if candidate.casefold() not in available:
            missing.append(f"{path.relative_to(ROOT)}: {candidate}")

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.casefold()
        if suffix == ".py":
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    inspect_value(path, node.value)
            continue
        if suffix not in {".ps1", ".iss", ".json", ".txt", ".qss"}:
            continue
        source_text = path.read_text(encoding="utf-8", errors="ignore")
        quoted_pattern = r"""(?i)["']([^"'\r\n]+\.(?:png|ico|wav|bmp))["']"""
        for value in re.findall(quoted_pattern, source_text):
            inspect_value(path, value)

    require(
        not missing,
        "Referenced resources are missing:\n - " + "\n - ".join(sorted(set(missing))),
    )
    return len(references)



def style_resource_contract() -> int:
    path = ROOT / "runtime" / "resources" / "theme.qss"
    source = path.read_text(encoding="utf-8")
    require(
        source.count("{") == source.count("}"),
        "theme.qss has unbalanced braces",
    )
    without_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    seen: set[tuple[str, str]] = set()
    duplicates: list[str] = []
    blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", without_comments)
    for selector, body in blocks:
        normalized_selector = " ".join(selector.split())
        normalized_body = ";".join(
            " ".join(declaration.strip().split())
            for declaration in body.split(";")
            if declaration.strip()
        )
        key = (normalized_selector, normalized_body)
        if key in seen:
            duplicates.append(normalized_selector)
        seen.add(key)
    require(
        not duplicates,
        "theme.qss contains exact duplicate blocks:\n - "
        + "\n - ".join(sorted(set(duplicates))),
    )
    forbidden_markers = ("consolidated from", "next-pass")
    lowered = source.casefold()
    require(
        not any(marker in lowered for marker in forbidden_markers),
        "theme.qss contains transformation-stage comments",
    )
    return len(blocks)


class FakeSettings:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


def settings_threshold_contract() -> None:
    from runtime.application.services.expiry_status import (
        ExpiryStatusKind,
        ExpiryThresholds,
        classify_expiry_days,
    )
    from runtime.application.services.settings_schema import (
        canonicalize_value,
        validate_canonical_settings,
    )
    from runtime.application.services.translations import is_rtl

    require(is_rtl("ar"), "Arabic code is not RTL")
    require(is_rtl("Arabic"), "Arabic alias is not RTL")
    require(is_rtl("العربية"), "Arabic native alias is not RTL")
    require(not is_rtl("en"), "English code incorrectly reports RTL")
    require(not is_rtl("English"), "English alias incorrectly reports RTL")
    require(canonicalize_value("language", "") == "ar", "Empty language is not Arabic")

    policy = ExpiryThresholds.from_settings(
        FakeSettings(
            {
                "expiry_expiring_soon_threshold_days": "10",
                "expiry_critical_threshold_days": "3",
            }
        )
    )
    require(policy.soon_days == 10, "Configured soon threshold was not loaded")
    require(policy.critical_days == 3, "Configured critical threshold was not loaded")

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
    for days, kind in expected.items():
        result = classify_expiry_days(
            days,
            expiring_soon_threshold=policy.soon_days,
            critical_threshold=policy.critical_days,
        )
        require(
            result.kind == kind,
            f"Dynamic threshold mismatch: days={days} actual={result.kind.value}",
        )

    invalid = validate_canonical_settings(
        {
            "expiry_expiring_soon_threshold_days": "7",
            "expiry_critical_threshold_days": "20",
        }
    )
    require(
        invalid.values["expiry_critical_threshold_days"] == "7",
        "Invalid critical threshold was not clamped to the soon threshold",
    )
    require(
        "expiry_critical_threshold_days" in invalid.errors,
        "Invalid critical threshold did not produce a validation error",
    )


def monitoring_repeat_contract() -> None:
    from runtime.domain.tracking_models import (
        RemoteTrackingId,
        TrackingKey,
        TrackingRecord,
    )
    from runtime.application.services.expiry_status import ExpiryThresholds
    from runtime.application.services.monitoring_engine import MonitoringEngine

    now = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
    policy = ExpiryThresholds(soon_days=10, critical_days=3)

    alert_record = TrackingRecord(
        key=TrackingKey(
            branch_code="1019",
            material_number="10001",
            production_date=date(2026, 7, 1),
            expiry_date=date(2026, 7, 19),
        ),
        remote_id=RemoteTrackingId("alert-1"),
        product_name="Alert product",
        quantity=2,
        branch_name="Branch 1019",
        revision=1,
        updated_at=now,
    )
    engine = MonitoringEngine()
    first = engine.evaluate(records=(alert_record,), now=now, policy=policy)
    second = engine.evaluate(records=(alert_record,), now=now, policy=policy)
    require(len(first) == 1 and first[0].alert is not None, "Initial alert missing")
    require(len(second) == 1 and second[0].alert is not None, "Repeat alert missing")
    require(
        second[0].previous == second[0].current,
        "Repeat alert was not emitted for an unchanged notifiable state",
    )

    valid_record = TrackingRecord(
        key=TrackingKey(
            branch_code="1019",
            material_number="10002",
            production_date=date(2026, 7, 1),
            expiry_date=date(2026, 8, 20),
        ),
        remote_id=RemoteTrackingId("valid-1"),
        product_name="Valid product",
        quantity=3,
        branch_name="Branch 1019",
        revision=1,
        updated_at=now,
    )
    valid_engine = MonitoringEngine()
    valid_first = valid_engine.evaluate(records=(valid_record,), now=now, policy=policy)
    valid_second = valid_engine.evaluate(
        records=(valid_record,), now=now, policy=policy
    )
    require(
        len(valid_first) == 1 and valid_first[0].alert is None,
        "Initial valid state transition is incorrect",
    )
    require(not valid_second, "Unchanged valid state produced a redundant transition")


def database_contract() -> None:
    from runtime.infrastructure.persistence.database_sections import LocalDataStore
    from runtime.application.services.expiry_status import ExpiryThresholds

    previous_home = os.environ.get("HOME")
    with tempfile.TemporaryDirectory(prefix="herfy-local-store-") as temp:
        os.environ["HOME"] = temp
        store = LocalDataStore()
        try:
            database_path = Path(store.db_path).resolve()
            expected_root = Path(temp).resolve() / ".config" / "HerfyClient"
            require(
                expected_root in database_path.parents,
                f"Database path escaped the runtime root: {database_path}",
            )
            require(
                store.get_setting("language") == "ar", "Database default is not Arabic"
            )
            require(
                store.get_setting("expiry_expiring_soon_threshold_days") == "7",
                "Default soon threshold was not persisted",
            )
            require(
                store.get_setting("expiry_critical_threshold_days") == "2",
                "Default critical threshold was not persisted",
            )

            store.set_setting("expiry_expiring_soon_threshold_days", "10")
            store.set_setting("expiry_critical_threshold_days", "3")
            policy = ExpiryThresholds.from_settings(store)
            require(
                (policy.soon_days, policy.critical_days) == (10, 3),
                "Stored thresholds were not loaded dynamically",
            )

            alert_key = "1019::10001"
            store.set_alert_state(
                alert_key,
                last_date="2026-07-16",
                last_notified_at=1.5,
                last_seen_at=2.5,
                fingerprint="payload-a",
                severity_rank=3,
                status_text="expiring_soon",
                notify_count=1,
            )
            state = store.get_alert_state(alert_key)
            require(
                state.get("fingerprint") == "payload-a", "Alert state was not saved"
            )
            require(
                int(state.get("notify_count") or 0) == 1, "Alert count was not saved"
            )

            store.record_notification_ledger(
                alert_key,
                state="expiring_soon",
                severity=3,
                payload_hash="payload-a",
            )
            ledger = store.get_notification_ledger(alert_key)
            require(
                ledger.get("last_payload_hash") == "payload-a",
                "Notification ledger payload was not saved",
            )
            require(
                int(ledger.get("shown_count") or 0) == 1,
                "Notification ledger count was not initialized",
            )
        finally:
            store.close()
            if previous_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous_home


def roaming_migration_contract() -> None:
    from runtime.shared.settings import runtime_migration

    previous_platform = sys.platform
    previous_local = os.environ.get("LOCALAPPDATA")
    with tempfile.TemporaryDirectory(prefix="herfy-roaming-migration-") as temp:
        temp_root = Path(temp)
        local_base = temp_root / "Local"
        target = temp_root / "Roaming" / "HerfyClient"
        previous = local_base / "HerfyClient"
        (previous / "database").mkdir(parents=True)
        (previous / "cache").mkdir(parents=True)
        (previous / "logs").mkdir(parents=True)
        (previous / "runtime.shared.settings.ini").write_text("language=ar\n", encoding="utf-8")
        (previous / "database" / "products.db").write_bytes(b"database")
        (previous / "cache" / "old.zip").write_bytes(b"cache")
        (previous / "logs" / "old.log").write_text("log", encoding="utf-8")

        try:
            sys.platform = "win32"
            os.environ["LOCALAPPDATA"] = str(local_base)
            result = runtime_migration.migrate_previous_localappdata(target)
        finally:
            sys.platform = previous_platform
            if previous_local is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous_local

        require(bool(result.get("migrated")), "Previous data migration did not run")
        require(
            (target / "settings.ini").is_file(),
            "Previous settings were not moved to Roaming",
        )
        require(
            (target / "database" / "products.db").is_file(),
            "Previous database was not moved to Roaming",
        )
        require(
            not (target / "cache" / "old.zip").exists(),
            "Stale update cache was incorrectly migrated",
        )
        require(
            not (target / "logs" / "old.log").exists(),
            "Previous logs were incorrectly migrated",
        )
        require(
            (target / runtime_migration.MIGRATION_MARKER).is_file(),
            "Roaming migration marker was not written",
        )
        require(not previous.exists(), "Previous LOCALAPPDATA tree was not removed")


def notification_policy_contract() -> None:
    from runtime.application.services.notifications import (
        NotificationDecisionService,
        NotificationEngine,
    )

    class FakeDatabase:
        def __init__(self) -> None:
            self.settings = {
                "notification_once_per_day": "True",
                "notification_repeat_interval_minutes": "15",
            }
            self.states: dict[str, dict[str, Any]] = {}
            self.ledger: dict[str, dict[str, Any]] = {}

        def get_setting(self, key: str, default: Any = None) -> Any:
            return self.settings.get(key, default)

        def get_alert_state(self, key: str) -> dict[str, Any]:
            return dict(self.states.get(key, {}))

        def set_alert_state(self, key: str, **values: Any) -> None:
            self.states[key] = dict(values)

        def get_notification_ledger(self, key: str) -> dict[str, Any]:
            return dict(self.ledger.get(key, {}))

        def record_notification_ledger(
            self,
            key: str,
            *,
            state: str,
            severity: int,
            payload_hash: str,
        ) -> None:
            previous = self.ledger.get(key, {})
            self.ledger[key] = {
                "notification_key": key,
                "state": state,
                "severity": severity,
                "last_shown_at": datetime.now(timezone.utc).isoformat(),
                "last_payload_hash": payload_hash,
                "shown_count": int(previous.get("shown_count") or 0) + 1,
            }

    database = FakeDatabase()
    service = NotificationDecisionService(NotificationEngine())

    event = {
        "branch": "1019",
        "material_number": "10001",
        "product_name": "Sample",
        "production_date": "2026-07-01",
        "expiry_date": "2026-07-19",
        "status": "Expiring high",
        "status_kind": "expiring_high",
        "severity_rank": 3,
        "days_remaining": 3,
        "quantity": 2,
    }

    first = service.evaluate(
        database, event, repeat_minutes=15, once_per_day=True
    )
    second = service.evaluate(
        database, event, repeat_minutes=15, once_per_day=True
    )
    require(first.should_notify, "First eligible notification was suppressed")
    require(
        not second.should_notify,
        "Once-per-day policy did not suppress a duplicate",
    )

    key = service.engine.alert_key(event)
    database.settings["notification_once_per_day"] = "False"
    database.states[key]["last_notified_at"] = time.time() - 901
    third = service.evaluate(
        database, event, repeat_minutes=15, once_per_day=False
    )
    require(
        third.should_notify,
        "Configured repeat interval did not permit a later notification",
    )


def ui_smoke_contract() -> bool:
    if not qt_available():
        return False

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QSpinBox

    from runtime.bootstrap.runtime.dependency_container import create_dependency_container
    from runtime.presentation.main_window.window import HerfyMainWindow
    from runtime.presentation.views.settings_page import SettingsDialog

    previous_home = os.environ.get("HOME")
    with tempfile.TemporaryDirectory(prefix="herfy-ui-smoke-") as temp:
        os.environ["HOME"] = temp
        app = QApplication.instance() or QApplication(
            ["HerfyClient", "--full-source-ui-smoke"]
        )
        container = create_dependency_container()
        try:
            for key, value in {
                "check_updates_on_startup": "False",
                "refresh_remote_ui_on_startup": "False",
                "immediate_server_sync": "False",
                "enable_alerts": "False",
                "enable_tray_background": "False",
            }.items():
                container.db_manager.set_setting(key, value)

            window = HerfyMainWindow(container)
            window._startup_flow_started = True
            require(window.objectName() == "MainWindow", "Main window was not built")
            require(
                window.layoutDirection() == Qt.RightToLeft,
                "Arabic main-window direction was not applied",
            )
            require(
                window.content_stack.indexOf(window.login_page) == 0,
                "Login page is not the initial content page",
            )

            dialog = SettingsDialog(container.db_manager, window)
            require(
                not dialog.alert_settings_changed,
                "Settings dialog starts with a false alert-change state",
            )
            dialog.on_apply()
            require(
                not dialog.alert_settings_changed,
                "Unchanged settings incorrectly reset notification state",
            )

            soon_widget = dialog.widgets.get("expiry_expiring_soon_threshold_days")
            require(
                isinstance(soon_widget, QSpinBox), "Soon threshold widget is missing"
            )
            soon_widget.setValue(min(60, soon_widget.value() + 1))
            dialog.on_apply()
            require(
                dialog.alert_settings_changed,
                "Threshold change was not exposed to the main window",
            )
            dialog.close()
            window.close()
            window.deleteLater()
            app.processEvents()
        finally:
            container.db_manager.close()
            if previous_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous_home
    return True


def update_url_contract() -> None:
    from runtime.application.services.updates import UpdateManager

    manager = UpdateManager(
        "2.18.1",
        base_url="https://herfy.online",
        api_base_url="https://herfy.online/api",
    )
    payload = {
        "available": True,
        "update_available": True,
        "latest_version": "2.18.2",
        "target_version": "2.18.2",
        "package_name": "HerfyClient_Setup_2.18.2.exe",
        "download_url": "/updates/packages/HerfyClient_Setup_2.18.2.exe",
        "sha256": "a" * 64,
        "size_bytes": 1024,
        "mandatory": True,
    }

    api_info = manager._update_info_from_payload(payload)
    require(api_info.available, "API installer update was not recognized")
    require(
        api_info.url == "https://herfy.online/api/updates/packages/"
        "HerfyClient_Setup_2.18.2.exe",
        f"API-relative update URL is incorrect: {api_info.url}",
    )

    static_info = manager._update_info_from_payload(
        payload,
        payload_base_url=manager.base_url,
    )
    require(
        static_info.url == "https://herfy.online/updates/packages/"
        "HerfyClient_Setup_2.18.2.exe",
        f"Static-relative update URL is incorrect: {static_info.url}",
    )


def compatibility_contract() -> bool:
    if not qt_available():
        return False

    from runtime.presentation.usage.print_support import UsagePrintContext
    from runtime.presentation.views.home_sections import HomeDashboardPage, HomePage

    require(HomePage is HomeDashboardPage, "HomePage compatibility alias is broken")
    context = UsagePrintContext(
        title="Usage",
        generated_at_text="2026-07-16",
        branch_text="1019",
        row_count=1,
        headers=("Item",),
        rows=(("Sample",),),
        numeric_columns=(),
        column_ratios=(1,),
        logo_path="",
    )
    require(context.row_count == 1, "UsagePrintContext constructor is broken")
    return True



def security_static_contract() -> int:
    findings: list[str] = []
    scanned = 0
    forbidden_calls = {
        "eval",
        "exec",
        "os.system",
        "tempfile.mktemp",
        "pickle.load",
        "pickle.loads",
        "yaml.load",
    }

    def dotted_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = dotted_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return ""

    for path in sorted((ROOT / "runtime").rglob("*.py")):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_name = dotted_name(node.func)
            if call_name in forbidden_calls:
                findings.append(f"{relative}:{node.lineno}: forbidden call {call_name}")
            if call_name.startswith("subprocess."):
                for keyword in node.keywords:
                    if (
                        keyword.arg == "shell"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                    ):
                        findings.append(
                            f"{relative}:{node.lineno}: subprocess shell=True"
                        )
            for keyword in node.keywords:
                if (
                    keyword.arg == "verify"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is False
                ):
                    findings.append(f"{relative}:{node.lineno}: TLS verify=False")
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"execute", "executemany"}
                and node.args
            ):
                statement = node.args[0]
                if isinstance(statement, ast.JoinedStr):
                    findings.append(f"{relative}:{node.lineno}: SQL f-string")
                if isinstance(statement, ast.BinOp) and isinstance(
                    statement.op, (ast.Add, ast.Mod)
                ):
                    findings.append(
                        f"{relative}:{node.lineno}: dynamically concatenated SQL"
                    )

    require(
        not findings,
        "Static security contract failed:\n - " + "\n - ".join(findings),
    )
    return scanned


def dependency_pin_contract() -> None:
    requirement_files = (
        ROOT / "requirements.txt",
        ROOT / "requirements-build.txt",
        ROOT / "requirements-test.txt",
        ROOT / "requirements-quality.txt",
    )
    parsed: dict[str, list[tuple[str, str]]] = {}
    includes: dict[str, set[str]] = {}
    invalid: list[str] = []

    for requirement_file in requirement_files:
        require(requirement_file.is_file(), f"Missing requirements file: {requirement_file.name}")
        includes[requirement_file.name] = set()
        for raw_line in requirement_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-r "):
                includes[requirement_file.name].add(line[3:].strip())
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
            if match is None:
                invalid.append(f"{requirement_file.name}: {line}")
                continue
            package = re.sub(r"[-_.]+", "-", match.group(1)).casefold()
            parsed.setdefault(package, []).append((match.group(2), requirement_file.name))

    require(not invalid, "Requirements must use exact == pins:\n - " + "\n - ".join(invalid))
    conflicts = {
        package: entries
        for package, entries in parsed.items()
        if len({version for version, _ in entries}) > 1
    }
    require(not conflicts, f"Conflicting dependency pins: {conflicts}")
    require(
        "requirements.txt" in includes["requirements-build.txt"],
        "requirements-build.txt must include requirements.txt",
    )

    pinned = {package: entries[0][0] for package, entries in parsed.items()}
    required_runtime = {
        "pyqt5": "5.15.11",
        "pyqt5-qt5": "5.15.2",
        "pyqt5-sip": "12.18.0",
        "defusedxml": "0.7.1",
        "openpyxl": "3.1.5",
    }
    require(
        all(pinned.get(package) == version for package, version in required_runtime.items()),
        "Windows-compatible PyQt5 runtime pins are incomplete",
    )
    require(
        pinned.get("pyqt5-qt5") != "5.15.19",
        "PyQt5-Qt5 5.15.19 has no Windows wheel and cannot be used",
    )
    require(
        pinned.get("pyinstaller") == "6.21.0",
        "Pinned PyInstaller build dependency is missing",
    )
    for quality_package in ("ruff", "black", "pip-audit"):
        require(
            quality_package in pinned,
            f"Pinned quality dependency is missing: {quality_package}",
        )


def version_contract() -> None:
    payload = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    app_version = str(payload.get("app_version") or "")
    settings_version = (
        ROOT / "runtime" / "shared" / "settings" / "version.py"
    ).read_text(encoding="utf-8")
    installer = (ROOT / "build" / "installer" / "HerfyClient_Custom_Installer.iss").read_text(
        encoding="utf-8"
    )

    fallback_match = re.search(r'_VERSION_FALLBACK\s*=\s*"([^"]+)"', settings_version)
    setup_match = re.search(r'#define SetupVersion\s+"([^"]+)"', installer)
    require(bool(app_version), "version.json app_version is empty")
    require(
        fallback_match is not None and fallback_match.group(1) == app_version,
        "settings/version.py fallback does not match version.json",
    )
    require(
        setup_match is not None and setup_match.group(1) == app_version,
        "Installer default version does not match version.json",
    )


def stale_source_contract() -> None:
    failures: list[str] = []
    direction_files = {
        "runtime/presentation/dialogs/confirm_delete_tracked_product.py",
        "runtime/presentation/dialogs/edit_tracked_product.py",
        "runtime/presentation/dialogs/manage_catalog_products.py",
        "runtime/presentation/dialogs/usage_products.py",
        "runtime/presentation/main_window/window.py",
        "runtime/presentation/views/home_sections/home_page.py",
    }
    for path in sorted(ROOT.rglob("*")):
        if path.resolve() == Path(__file__).resolve():
            continue
        if not path.is_file() or path.suffix.casefold() not in {
            ".py",
            ".ps1",
            ".cmd",
            ".iss",
            ".json",
            ".txt",
            ".toml",
            ".yml",
            ".yaml",
            ".qss",
        }:
            continue
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "herfy_client." in text or "import herfy_client" in text:
            failures.append(f"{relative}: nested obsolete import")
        if _OLD_VERSION_RE.search(text):
            failures.append(f"{relative}: stale version reference")
        if '.lower() == "arabic"' in text:
            failures.append(f"{relative}: hardcoded Arabic comparison")
        if 'get_setting("language", "English")' in text:
            failures.append(f"{relative}: English language fallback")
        if 'language: str = "English"' in text:
            failures.append(f"{relative}: English function default")
        if 'language or "English"' in text:
            failures.append(f"{relative}: English fallback expression")
        if relative in direction_files and "is_rtl" not in text:
            failures.append(f"{relative}: canonical RTL helper is missing")
    require(not failures, "Stale source contract failed:\n - " + "\n - ".join(failures))


def main() -> int:
    for path in sorted(ROOT.rglob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    modules, exports, qt_import_skips = import_and_export_contract()
    translations, literal_keys = translation_contract()
    resources = resource_contract()
    style_blocks = style_resource_contract()
    settings_threshold_contract()
    monitoring_repeat_contract()
    database_contract()
    roaming_migration_contract()
    notification_policy_contract()
    ui_checked = ui_smoke_contract()
    update_url_contract()
    compatibility_checked = compatibility_contract()
    security_files = security_static_contract()
    dependency_pin_contract()
    version_contract()
    stale_source_contract()

    print(
        "HERFY_FULL_SOURCE_CONTRACT_OK "
        f"modules={modules} exports={exports} "
        f"translations={translations} literal_keys={literal_keys} "
        f"resources={resources} style_blocks={style_blocks} "
        "thresholds=dynamic monitoring=repeat-ready "
        "database=ok roaming=migrated notification_policy=ok "
        f"qt_import_skips={qt_import_skips} "
        f"ui={'offscreen-ok' if ui_checked else 'SKIPPED(PyQt5-unavailable)'} "
        f"compatibility={'ok' if compatibility_checked else 'SKIPPED(PyQt5-unavailable)'} "
        f"update_url=api-aware security_files={security_files} "
        "dependencies=windows-wheel-compatible"
    )
    complete = qt_import_skips == 0 and ui_checked and compatibility_checked
    print(
        format_validation_result(
            "full-source-contract",
            "passed" if complete else "partial",
            (
                f"modules={modules},qt-import-skips={qt_import_skips},"
                f"ui={'ok' if ui_checked else 'not-run'},"
                f"compatibility={'ok' if compatibility_checked else 'not-run'}"
            ),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
