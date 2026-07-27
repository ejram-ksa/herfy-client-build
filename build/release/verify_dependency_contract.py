from __future__ import annotations

import importlib.metadata
import os
import re
import subprocess
import sys
from pathlib import Path

from validation_result import format_validation_result

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENT_FILES = (
    "requirements.txt",
    "requirements-build.txt",
    "requirements-test.txt",
    "requirements-quality.txt",
)
_EXACT_PIN = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s;]+)$")
_REQUIRED_RUNTIME_PACKAGES = {
    "pyqt5",
    "pyqt5-qt5",
    "pyqt5-sip",
    "packaging",
    "requests",
    "defusedxml",
    "openpyxl",
    "xlrd",
}


def _normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", str(value or "").strip()).lower()


def _parse_file(path: Path) -> tuple[dict[str, str], list[str]]:
    pins: dict[str, str] = {}
    includes: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r ") or line.startswith("--requirement "):
            include = line.split(maxsplit=1)[1].strip()
            if not include or Path(include).is_absolute() or ".." in Path(include).parts:
                raise SystemExit(
                    f"HERFY_DEPENDENCY_CONTRACT_FAILED unsafe include "
                    f"{path.name}:{line_number}: {line}"
                )
            includes.append(include)
            continue
        if line.startswith(("-", "http://", "https://", "git+")):
            raise SystemExit(
                f"HERFY_DEPENDENCY_CONTRACT_FAILED unsupported requirement "
                f"{path.name}:{line_number}: {line}"
            )
        match = _EXACT_PIN.fullmatch(line)
        if not match:
            raise SystemExit(
                f"HERFY_DEPENDENCY_CONTRACT_FAILED unpinned requirement "
                f"{path.name}:{line_number}: {line}"
            )
        name = _normalize_name(match.group("name"))
        version = match.group("version")
        previous = pins.get(name)
        if previous is not None and previous != version:
            raise SystemExit(
                f"HERFY_DEPENDENCY_CONTRACT_FAILED conflicting pins for {name}: "
                f"{previous} vs {version}"
            )
        pins[name] = version
    return pins, includes


def _collect_pins() -> dict[str, str]:
    all_pins: dict[str, str] = {}
    for filename in REQUIREMENT_FILES:
        path = ROOT / filename
        if not path.is_file():
            raise SystemExit(f"HERFY_DEPENDENCY_CONTRACT_FAILED missing {filename}")
        pins, includes = _parse_file(path)
        if filename == "requirements-build.txt" and includes != ["requirements.txt"]:
            raise SystemExit(
                "HERFY_DEPENDENCY_CONTRACT_FAILED requirements-build.txt must include "
                "requirements.txt exactly once"
            )
        if filename != "requirements-build.txt" and includes:
            raise SystemExit(
                f"HERFY_DEPENDENCY_CONTRACT_FAILED unexpected include in {filename}"
            )
        for name, version in pins.items():
            previous = all_pins.get(name)
            if previous is not None and previous != version:
                raise SystemExit(
                    f"HERFY_DEPENDENCY_CONTRACT_FAILED conflicting cross-file pins "
                    f"for {name}: {previous} vs {version}"
                )
            all_pins[name] = version
    missing = sorted(_REQUIRED_RUNTIME_PACKAGES - set(all_pins))
    if missing:
        raise SystemExit(
            f"HERFY_DEPENDENCY_CONTRACT_FAILED missing runtime pins: {missing}"
        )
    return all_pins


def _verify_installed(pins: dict[str, str]) -> None:
    mismatches: list[str] = []
    missing: list[str] = []
    for name, expected in sorted(pins.items()):
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
            continue
        if actual != expected:
            mismatches.append(f"{name} expected={expected} actual={actual}")
    if missing or mismatches:
        raise SystemExit(
            "HERFY_DEPENDENCY_CONTRACT_FAILED installed environment mismatch "
            f"missing={missing} mismatches={mismatches}"
        )
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "HERFY_DEPENDENCY_CONTRACT_FAILED pip check failed: "
            + completed.stdout.strip()
        )


def main() -> int:
    pins = _collect_pins()
    verify_installed = sys.platform.startswith("win") or (
        os.environ.get("HERFY_VERIFY_INSTALLED_REQUIREMENTS") == "1"
    )
    if verify_installed:
        _verify_installed(pins)
        print(f"HERFY_DEPENDENCY_CONTRACT_OK pins={len(pins)} installed=verified")
        print(
            format_validation_result(
                "dependency-contract", "passed", f"pins={len(pins)},installed=verified"
            )
        )
    else:
        print(
            f"HERFY_DEPENDENCY_CONTRACT_OK pins={len(pins)} "
            "installed=not-verified-on-this-host"
        )
        print(
            format_validation_result(
                "dependency-contract",
                "partial",
                f"pins={len(pins)},installed=not-verified-on-this-host",
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
