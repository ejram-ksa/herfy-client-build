from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from validation_result import format_validation_result

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE_MODULES = (
    "runtime.application.ports",
    "runtime.bootstrap.runtime.dependency_container",
    "runtime.application.services.auth",
    "runtime.application.services.sync",
    "runtime.application.services.updates",
    "runtime.services.session",
)

QT_MODULES = (
    "main",
    "runtime.presentation.main_window",
    "runtime.presentation.main_window.window",
    "runtime.presentation.main_window.cloud_sections",
    "runtime.presentation.views.tracking_support",
    "runtime.presentation.updates.update_flow",
)


def _pyqt5_available() -> bool:
    try:
        importlib.import_module("PyQt5.QtCore")
    except ModuleNotFoundError:
        return False
    return True


def main() -> int:
    for name in CORE_MODULES:
        importlib.import_module(name)

    ports = importlib.import_module("runtime.application.ports")
    sync = importlib.import_module("runtime.application.services.sync")
    for symbol in (
        "fetch_cloud_snapshot_payload",
        "configure_cloud_runtime",
    ):
        owner = sync if symbol == "fetch_cloud_snapshot_payload" else ports
        if not callable(getattr(owner, symbol, None)):
            raise RuntimeError(f"Missing runtime symbol: {owner.__name__}.{symbol}")

    if not _pyqt5_available():
        print(
            "HERFY_RUNTIME_IMPORTS_OK "
            f"core_modules={len(CORE_MODULES)} qt_modules=SKIPPED reason=PyQt5-unavailable"
        )
        print(
            format_validation_result(
                "runtime-imports",
                "partial",
                f"core-modules={len(CORE_MODULES)},qt-modules=not-imported",
            )
        )
        return 0

    for name in QT_MODULES:
        importlib.import_module(name)
    print(
        "HERFY_RUNTIME_IMPORTS_OK "
        f"core_modules={len(CORE_MODULES)} qt_modules={len(QT_MODULES)}"
    )
    print(
        format_validation_result(
            "runtime-imports",
            "passed",
            f"core-modules={len(CORE_MODULES)},qt-modules={len(QT_MODULES)}",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
