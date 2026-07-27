from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

from validation_result import format_validation_result

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


cli = (ROOT / "cli.py").read_text(encoding="utf-8")
runtime = (ROOT / "runtime_notification_health.py").read_text(encoding="utf-8")
spec = (ROOT / "build" / "installer" / "pyinstaller" / "HerfyClient.spec").read_text(
    encoding="utf-8"
)
builder = (ROOT / "build" / "installer" / "BUILD_CUSTOM_INSTALLER.ps1").read_text(
    encoding="utf-8"
)
print_support = (ROOT / "runtime" / "presentation" / "usage" / "print_support" / "rendering.py").read_text(
    encoding="utf-8"
)

require("--notification-self-check" in cli, "Notification self-check CLI is missing")
require("--notification-demo" in cli, "Windows notification demo CLI is missing")
require(
    "HERFY_NOTIFICATION_SELF_CHECK_FILE" in cli,
    "Frozen notification output environment contract is missing",
)
require(
    "notification_self_check_payload" in runtime,
    "Notification runtime payload is missing",
)
require(
    "QSystemTrayIcon" in runtime and "QMediaPlayer" in runtime,
    "Qt notification runtime checks are incomplete",
)
require(
    "winsound_available" in runtime,
    "Windows sound fallback check is missing",
)
require(
    "settings_thresholds" in runtime and "_settings_threshold_checks" in runtime,
    "Dynamic settings threshold runtime check is missing",
)
require(
    "PyQt5.QtPrintSupport" in spec,
    "QtPrintSupport hidden import is missing",
)
require(
    'contents_directory="."' in spec,
    "PyInstaller runtime is not root-level",
)
require(
    "HERFY_FROZEN_NOTIFICATION_RUNTIME_OK" in builder,
    "Frozen notification build gate is missing",
)
require(
    "@dataclass(frozen=True, slots=True)\nclass UsagePrintContext" in print_support,
    "UsagePrintContext constructor fix is missing",
)

for name in (
    "default.wav",
    "expired.wav",
    "expires_today.wav",
    "expiry_critical.wav",
    "expiry_soon.wav",
):
    path = ROOT / "runtime" / "resources" / "sounds" / name
    require(path.is_file() and path.stat().st_size > 44, f"Invalid sound: {name}")
    header = path.read_bytes()[:12]
    require(
        len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE",
        f"Invalid WAVE header: {name}",
    )

for py_file in ROOT.rglob("*.py"):
    ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))

qt_status = "not-requested"
if os.environ.get("HERFY_SKIP_PYQT_RUNTIME_CHECK") != "1":
    from runtime_notification_health import notification_self_check_payload

    payload = notification_self_check_payload()
    errors = {str(item) for item in payload.get("errors", [])}
    qt_errors = {item for item in errors if item.startswith("qt_")}
    non_qt_errors = errors - qt_errors
    require(
        not non_qt_errors,
        f"Notification non-Qt runtime checks failed: {payload}",
    )
    if qt_errors:
        require(
            not sys.platform.startswith("win"),
            f"Notification Qt runtime failed on Windows: {payload}",
        )
        qt_status = "skipped(non-Windows-or-PyQt-unavailable)"
    else:
        require(payload.get("status") == "ok", f"Notification runtime failed: {payload}")
        qt_status = "ok"

print(f"HERFY_NOTIFICATION_RUNTIME_CONTRACT_OK qt={qt_status}")
if qt_status == "ok":
    print(
        format_validation_result(
            "notification-runtime-contract", "passed", "qt-runtime=ok"
        )
    )
else:
    print(
        format_validation_result(
            "notification-runtime-contract",
            "partial",
            f"qt-runtime={qt_status}",
        )
    )
