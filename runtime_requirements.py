from __future__ import annotations
from dataclasses import dataclass
import importlib.util
import os
import sys
from pathlib import Path


@dataclass(frozen=True)
class RuntimeRequirement:
    import_name: str
    pip_name: str
    purpose: str


REQUIRED_RUNTIME_REQUIREMENTS: tuple[RuntimeRequirement, ...] = (
    RuntimeRequirement("PyQt5", "PyQt5", "desktop user interface"),
    RuntimeRequirement("requests", "requests", "server communication"),
    RuntimeRequirement("packaging", "packaging", "version comparison"),
    RuntimeRequirement("openpyxl", "openpyxl", "Excel workbook support"),
    RuntimeRequirement("xlrd", "xlrd", "XLS workbook support"),
)


def source_root_dir() -> Path:
    return Path(__file__).resolve().parent


def requirements_file_path() -> Path:
    return source_root_dir() / "requirements.txt"


def is_dependency_available(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def missing_runtime_requirements() -> list[RuntimeRequirement]:
    return [
        requirement
        for requirement in REQUIRED_RUNTIME_REQUIREMENTS
        if not is_dependency_available(requirement.import_name)
    ]


def dependency_check_payload() -> list[dict[str, object]]:
    return [
        {
            "import_name": requirement.import_name,
            "pip_name": requirement.pip_name,
            "purpose": requirement.purpose,
            "available": is_dependency_available(requirement.import_name),
        }
        for requirement in REQUIRED_RUNTIME_REQUIREMENTS
    ]


def _python_command() -> str:
    executable = Path(sys.executable or "python")
    return f'"{executable}"' if " " in str(executable) else str(executable)


def _install_command() -> str:
    requirements_path = requirements_file_path()
    if requirements_path.exists():
        return f"{_python_command()} -m pip install -r requirements.txt"
    packages = " ".join((req.pip_name for req in REQUIRED_RUNTIME_REQUIREMENTS))
    return f"{_python_command()} -m pip install {packages}"


def format_missing_requirements_message(
    missing: list[RuntimeRequirement] | None = None,
) -> str:
    missing_items = missing if missing is not None else missing_runtime_requirements()
    if not missing_items:
        return ""
    lines = [
        "Herfy Client cannot start because required Python packages are missing.",
        "",
        "Missing packages:",
    ]
    for requirement in missing_items:
        lines.append(
            f"- {requirement.pip_name} (import: {requirement.import_name}, {requirement.purpose})"
        )
    lines.extend(
        [
            "",
            "Fix:",
            "1. Open Command Prompt in the application folder.",
            f"2. Run: {_install_command()}",
            "3. Run: python main.py",
        ]
    )
    return os.linesep.join(lines) + os.linesep


def main() -> int:
    import json

    payload = dependency_check_payload()
    missing = [item for item in payload if not bool(item.get("available"))]
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + os.linesep)
    if missing:
        sys.stderr.write(
            format_missing_requirements_message(
                [
                    requirement
                    for requirement in REQUIRED_RUNTIME_REQUIREMENTS
                    if any(
                        (
                            item.get("import_name") == requirement.import_name
                            for item in missing
                        )
                    )
                ]
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
