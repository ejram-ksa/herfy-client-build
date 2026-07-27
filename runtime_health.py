from __future__ import annotations
import importlib
import importlib.util
import json
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import Any
import sys
from runtime.shared.settings.config import (
    APP_ICON_RELATIVE_PATH,
    LOGO_RELATIVE_PATH,
    THEME_QSS_RELATIVE_PATH,
    TRANSLATIONS_RELATIVE_PATH,
    bundled_or_source_path,
)
from runtime.shared.settings.logging_setup import (
    candidate_log_dirs,
    ensure_log_dir,
    setup_crash_logging,
)
from runtime_requirements import dependency_check_payload
from runtime.shared.settings.version import __version__ as APP_VERSION

CRITICAL_MODULES = {
    "runtime.bootstrap.runtime.app_bootstrap": ("run",),
    "runtime.bootstrap.runtime.dependency_container": (
        "DependencyContainer",
        "create_dependency_container",
    ),
    "runtime.infrastructure.network.api": ("ApiClient", "fetch_client_bootstrap"),
    "runtime.application.services.admin": ("AdminService",),
    "runtime.application.services.tracking": ("TrackingService",),
    "runtime.domain.runtime_state": ("RuntimeStateCore",),
    "runtime.presentation.main_window.window": ("HerfyMainWindow",),
}
PACKAGED_UI_MODULES = {
    "runtime.presentation.main_window.action_sections": ("MainWindowMenuBuilderMixin",),
    "runtime.presentation.main_window.cloud_sections": ("MainWindowUpdatesMixin",),
    "runtime.presentation.views.home_sections": ("HomeDashboardPage",),
    "runtime.presentation.tables.headers": (
        "TRACKING_HEADER_KEYS",
        "TRACKING_HEADERS",
        "USAGE_HEADER_KEYS",
        "HEADERS_USAGE",
    ),
}
REQUIRED_RESOURCES = {
    "theme_qss": THEME_QSS_RELATIVE_PATH,
    "translations": TRANSLATIONS_RELATIVE_PATH,
    "logo": LOGO_RELATIVE_PATH,
    "app_icon": APP_ICON_RELATIVE_PATH,
    "default_sound": ("resources", "sounds", "default.wav"),
    "expired_sound": ("resources", "sounds", "expired.wav"),
    "today_sound": ("resources", "sounds", "expires_today.wav"),
    "critical_sound": ("resources", "sounds", "expiry_critical.wav"),
    "soon_sound": ("resources", "sounds", "expiry_soon.wav"),
    "version_json": ("version.json",),
}


def _emit_cli_output(text: str, *, fallback_name: str = "cli_output.json") -> None:
    try:
        log_dir = ensure_log_dir()
        with open(
            os.path.join(log_dir, fallback_name), "w", encoding="utf-8"
        ) as handle:
            handle.write(text)
    except (OSError, RuntimeError, TypeError, ValueError):
        logging.debug("Unable to write CLI fallback output", exc_info=True)
    stream = getattr(sys, "stdout", None)
    if stream is not None:
        try:
            stream.write(text)
            with suppress(OSError, RuntimeError, TypeError, ValueError):
                stream.flush()
        except (OSError, RuntimeError, TypeError, ValueError):
            logging.debug("Unable to write CLI output to stdout", exc_info=True)


def _write_cli_file(path: str | os.PathLike[str], text: str) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _resource_check_entry(label: str, *parts: str) -> dict[str, object]:
    path = Path(bundled_or_source_path(*parts))
    executable_candidate = Path(sys.executable).resolve().parent.joinpath(*parts)
    return {
        "label": label,
        "path": str(path),
        "exists": path.exists(),
        "executable_adjacent_path": str(executable_candidate),
        "executable_adjacent_exists": executable_candidate.exists(),
    }


def _check_import_contracts(
    contracts: dict[str, tuple[str, ...]],
) -> dict[str, dict[str, object]]:
    checks: dict[str, dict[str, object]] = {}
    for module_name, required_names in sorted(contracts.items()):
        try:
            spec = importlib.util.find_spec(module_name)
        except (
            AttributeError,
            ImportError,
            ModuleNotFoundError,
            RuntimeError,
            ValueError,
        ) as exc:
            checks[module_name] = {
                "ok": False,
                "mode": "module_spec",
                "error": f"{type(exc).__name__}: {exc}",
            }
            continue
        if spec is None:
            checks[module_name] = {
                "ok": False,
                "mode": "module_spec",
                "error": "module not found",
            }
            continue
        try:
            module = importlib.import_module(module_name)
        except (
            AttributeError,
            ImportError,
            ModuleNotFoundError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            checks[module_name] = {
                "ok": False,
                "mode": "runtime_import",
                "error": f"{type(exc).__name__}: {exc}",
            }
            continue
        missing = [name for name in required_names if not hasattr(module, name)]
        checks[module_name] = {
            "ok": not missing,
            "mode": "runtime_import",
            "required_names": list(required_names),
            "missing": missing,
        }
    return checks


def _check_resource_contracts() -> tuple[dict[str, dict[str, object]], list[str]]:
    resources: dict[str, dict[str, object]] = {}
    missing: list[str] = []
    for key, parts in REQUIRED_RESOURCES.items():
        entry = _resource_check_entry(key, *parts)
        resources[key] = entry
        if not bool(entry["exists"] or entry["executable_adjacent_exists"]):
            missing.append(key)
    return (resources, missing)


def _runtime_state_check() -> dict[str, object]:
    try:
        from runtime.domain.runtime_state import RuntimeStateCore

        state = RuntimeStateCore()
        state.set_current_branch("H1004")
        state.set_allowed_branches(["H1004"])
        return {
            "ok": state.current_branch == "H1004",
            "current_branch": state.current_branch,
            "allowed_branches": state.allowed_branches,
        }
    except (ImportError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _remote_api_surface_check() -> dict[str, object]:
    try:
        from runtime.infrastructure.network.api import ApiClient, fetch_client_bootstrap

        client = ApiClient(
            id_token="smoke-token",
            user={"id": "smoke-user", "username": "smoke"},
            base_url="https://example.invalid",
        )
        required_methods = [
            "admin_dashboard",
            "admin_list_users",
            "admin_upsert_user",
            "admin_upsert_branch",
            "admin_set_role_permissions",
            "change_own_password",
            "list_stored_products",
            "list_usage_products",
            "upsert_stored_product",
            "delete_stored_product_remote",
            "add_item",
            "update_item",
            "delete_item",
            "list_items",
            "snapshot_items",
            "list_alerts",
            "mark_alert_seen",
            "meta_branches",
            "meta_regions",
            "meta_areas",
            "pull_now",
            "push_sync_changes",
            "stop_realtime",
        ]
        missing = [
            name
            for name in required_methods
            if not callable(getattr(client, name, None))
        ]
        return {
            "ok": bool(callable(fetch_client_bootstrap) and (not missing)),
            "missing": missing,
            "required_methods": required_methods,
            "has_fetch_client_bootstrap": callable(fetch_client_bootstrap),
        }
    except (ImportError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _latest_fatal_error_excerpt() -> dict[str, object]:
    candidates: list[str] = []
    for log_dir in candidate_log_dirs():
        candidates.append(os.path.join(log_dir, "fatal_error.log"))
    for path in candidates:
        try:
            target = Path(path)
            if target.is_file():
                text = target.read_text(encoding="utf-8", errors="ignore")[-4000:]
                return {"exists": True, "path": path, "tail": text}
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
    return {"exists": False, "checked": candidates}


def runtime_self_check_payload() -> dict[str, object]:
    resources, missing_resources = _check_resource_contracts()
    runtime_dependencies = dependency_check_payload()
    missing_dependencies = [
        str(item.get("pip_name") or item.get("import_name") or "")
        for item in runtime_dependencies
        if not bool(item.get("available"))
    ]
    critical_modules = _check_import_contracts(CRITICAL_MODULES)
    ui_modules = _check_import_contracts(PACKAGED_UI_MODULES)
    runtime_checks = {
        "runtime_state_core": _runtime_state_check(),
        "remote_api_public_surface": _remote_api_surface_check(),
    }
    critical_missing: list[str] = []
    critical_missing.extend(missing_resources)
    critical_missing.extend(
        (f"dependency:{name}" for name in missing_dependencies if name)
    )
    critical_missing.extend(
        (
            f"module:{name}"
            for name, result in critical_modules.items()
            if not bool(result.get("ok"))
        )
    )
    critical_missing.extend(
        (
            f"runtime:{name}"
            for name, result in runtime_checks.items()
            if not bool(result.get("ok"))
        )
    )
    warnings = [
        f"ui_module:{name}"
        for name, result in ui_modules.items()
        if not bool(result.get("ok"))
    ]
    return {
        "status": "ok" if not critical_missing else "failed",
        "verification_scope": "executable_runtime_contract",
        "version": APP_VERSION,
        "executable": sys.executable,
        "cwd": os.getcwd(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "bundle_dir": str(getattr(sys, "_MEIPASS", "")),
        "pyqt_available": importlib.util.find_spec("PyQt5") is not None,
        "runtime_dependencies": runtime_dependencies,
        "missing_dependencies": missing_dependencies,
        "candidate_log_dirs": candidate_log_dirs(),
        "resources": resources,
        "critical_modules": critical_modules,
        "packaged_ui_modules": ui_modules,
        "runtime_checks": runtime_checks,
        "fatal_error": _latest_fatal_error_excerpt(),
        "critical_missing": critical_missing,
        "warnings": warnings,
    }


def run_runtime_self_check(output_file: str | None = None) -> int:
    payload = runtime_self_check_payload()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _emit_cli_output(text, fallback_name="self_check.json")
    if output_file:
        _write_cli_file(output_file, text)
    return 0 if payload.get("status") == "ok" else 1


def run_runtime_diagnostics(output_file: str | None = None) -> int:
    setup_crash_logging()
    log_dir = ensure_log_dir()
    payload: dict[str, Any] = {
        "status": "ok",
        "verification_scope": "diagnostics",
        "version": APP_VERSION,
        "executable": sys.executable,
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "bundle_dir": str(getattr(sys, "_MEIPASS", "")),
        "log_dir": log_dir,
        "log_files": {
            "desktop_log": os.path.join(log_dir, "desktop.log"),
            "fatal_error_log": os.path.join(log_dir, "fatal_error.log"),
            "crash_log": os.path.join(log_dir, "crash.log"),
        },
        "runtime_health": runtime_self_check_payload(),
        "fatal_error": _latest_fatal_error_excerpt(),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _emit_cli_output(text, fallback_name="diagnose.json")
    if output_file:
        _write_cli_file(output_file, text)
    return 0
