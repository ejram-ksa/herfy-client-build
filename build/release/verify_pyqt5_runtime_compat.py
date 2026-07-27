from __future__ import annotations

import ast
import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

from validation_result import format_validation_result

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SKIPPED_ROOTS = {
    ".venv",
    ".venv-build",
    "venv",
    "build",
    "dist",
    "publish",
    "output",
    "__pycache__",
}


def _python_files() -> list[Path]:
    result: list[Path] = []
    for path in ROOT.rglob("*.py"):
        if set(path.relative_to(ROOT).parts) & SKIPPED_ROOTS:
            continue
        result.append(path)
    return sorted(result)


def _resolve_import(module_name: str, name: str) -> Any:
    module = importlib.import_module(module_name)
    return getattr(module, name)


def _assert_static_pyqt_attributes() -> int:
    checked = 0
    failures: list[str] = []

    for path in _python_files():
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        imported_names: dict[str, tuple[str, str]] = {}
        imported_modules: dict[str, str] = {}

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("PyQt5.")
            ):
                for alias in node.names:
                    imported_names[alias.asname or alias.name] = (
                        node.module,
                        alias.name,
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("PyQt5."):
                        local_name = alias.asname or alias.name.rsplit(".", 1)[-1]
                        imported_modules[local_name] = alias.name

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not isinstance(
                node.value, ast.Name
            ):
                continue

            base_name = node.value.id
            if base_name in imported_names:
                module_name, imported_name = imported_names[base_name]
                try:
                    owner = _resolve_import(module_name, imported_name)
                except (ImportError, AttributeError) as exc:
                    failures.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: "
                        f"cannot import {module_name}.{imported_name}: {exc}"
                    )
                    continue
                checked += 1
                if not hasattr(owner, node.attr):
                    failures.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: "
                        f"{module_name}.{imported_name}.{node.attr} is unavailable"
                    )
            elif base_name in imported_modules:
                module_name = imported_modules[base_name]
                try:
                    owner = importlib.import_module(module_name)
                except ImportError as exc:
                    failures.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: "
                        f"cannot import {module_name}: {exc}"
                    )
                    continue
                checked += 1
                if not hasattr(owner, node.attr):
                    failures.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: "
                        f"{module_name}.{node.attr} is unavailable"
                    )

    if failures:
        details = "\n".join(failures[:50])
        raise SystemExit(f"HERFY_PYQT5_RUNTIME_COMPAT_FAILED:\n{details}")
    return checked


def _assert_admin_change_event_smoke() -> bool:
    from PyQt5.QtCore import QEvent
    from PyQt5.QtWidgets import QApplication

    from runtime.presentation.views.admin_page import AdminDashboardDialog

    app = QApplication.instance() or QApplication([])
    original_refresh = AdminDashboardDialog.refresh_all_async
    AdminDashboardDialog.refresh_all_async = lambda self: None

    class _CloudService:
        pass

    dialog = None
    try:
        dialog = AdminDashboardDialog(_CloudService())
        dialog.show()
        app.processEvents()
        for event_type in (
            QEvent.ActivationChange,
            QEvent.WindowStateChange,
            QEvent.StyleChange,
            QEvent.LayoutDirectionChange,
        ):
            dialog.changeEvent(QEvent(event_type))
        app.processEvents()
    finally:
        AdminDashboardDialog.refresh_all_async = original_refresh
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
        app.processEvents()

    return hasattr(QEvent, "ScreenChangeInternal")


def _pyqt5_available() -> bool:
    return importlib.util.find_spec("PyQt5") is not None


def main() -> int:
    if not _pyqt5_available():
        if sys.platform.startswith("win"):
            raise SystemExit(
                "HERFY_PYQT5_RUNTIME_COMPAT_FAILED: PyQt5 is unavailable on Windows"
            )
        print(
            "HERFY_PYQT5_RUNTIME_COMPAT_SKIPPED "
            "reason=PyQt5-unavailable platform=non-Windows"
        )
        print(
            format_validation_result(
                "pyqt5-runtime-compat",
                "skipped",
                "PyQt5-unavailable,platform=non-Windows",
            )
        )
        return 0

    checked = _assert_static_pyqt_attributes()
    screen_change_internal = _assert_admin_change_event_smoke()
    print(
        "HERFY_PYQT5_RUNTIME_COMPAT_OK "
        f"references={checked} "
        f"screen_change_internal={str(screen_change_internal).lower()} "
        "admin_change_event=ok"
    )
    print(
        format_validation_result(
            "pyqt5-runtime-compat",
            "passed",
            f"references={checked},admin-change-event=ok",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
