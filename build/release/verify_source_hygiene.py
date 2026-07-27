from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_TOP_LEVEL = {
    ".github",
    "00_BUILD_AND_PUBLISH.cmd",
    "00_INSTALL_BUILD_TOOLS.cmd",
    "00_VALIDATE.cmd",
    "00_VERIFY_DEPLOYED_RELEASE.cmd",
    "00_TEST_WINDOWS_NOTIFICATIONS.cmd",
    "__main__.py",
    "build",
    "cli.py",
    "main.py",
    "pyproject.toml",
    "pytest.ini",
    "requirements.txt",
    "requirements-build.txt",
    "requirements-test.txt",
    "requirements-quality.txt",
    "PACKAGE_MANIFEST.json",
    "SHA256SUMS.txt",
    "runtime",
    "runtime_health.py",
    "runtime_notification_health.py",
    "runtime_requirements.py",
    "tests",
    "version.json",
}
OPTIONAL_TOP_LEVEL: set[str] = set()
REQUIRED_TOP_LEVEL = set(ALLOWED_TOP_LEVEL)
FORBIDDEN_DIRS = {
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "dist",
    "publish",
    "output",
}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak"}
VERSIONED_RELEASE_FILENAME = re.compile(r"(?:^|[_-])\d+[._]\d+[._]\d+(?:[._-]|$)")
FORBIDDEN_FILENAME_PATTERNS = (
    re.compile(
        r"(?i)(?:^|[_-])"
        r"(?:phase[_-]?\d+|baseline|execution_report|implementation_report|changed_files)"
        r"(?:[_-]|$)"
    ),
    re.compile(r"(?i)(?:legacy|refactor|rebase|pass[_-]?\d+)"),
)
FORBIDDEN_SOURCE_HISTORY_PATTERNS = (
    re.compile(r"(?i)(?:^|[^A-Za-z0-9])legacy(?:$|[^A-Za-z0-9])"),
    re.compile(r"(?i)(?:phase[_ -]?\d+|refactor(?:ed|ing)?|rebas(?:e|ed|ing)|pass[_ -]?\d+)"),
)
SECRET_PATTERNS = (
    re.compile(r"BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY", re.I),
    re.compile(
        r"(?i)(?:password|passwd|secret)\s*[=:]\s*['\"]?(?:123456|18016|2614|29429|Hus-)"
    ),
)


def main() -> int:
    errors: list[str] = []
    actual = {path.name for path in ROOT.iterdir()}
    unexpected = sorted(actual - ALLOWED_TOP_LEVEL - OPTIONAL_TOP_LEVEL)
    missing = sorted(REQUIRED_TOP_LEVEL - actual)
    if unexpected:
        errors.append(f"unexpected top-level entries: {unexpected}")
    if missing:
        errors.append(f"missing top-level entries: {missing}")

    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if path.is_symlink():
            errors.append(f"symbolic link is not allowed: {relative}")
            continue
        if any(pattern.search(path.name) for pattern in FORBIDDEN_FILENAME_PATTERNS):
            errors.append(f"historical or report filename is forbidden: {relative}")
        if path.is_dir() and path.name in FORBIDDEN_DIRS:
            errors.append(f"forbidden directory: {relative}")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"forbidden artifact: {relative}")
        if path.is_file() and VERSIONED_RELEASE_FILENAME.search(path.name):
            errors.append(f"versioned release filename: {relative}")
        if path.is_file() and path.suffix.lower() in {
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
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if (
                path.name not in {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}
                and path.resolve() != Path(__file__).resolve()
            ):
                for pattern in FORBIDDEN_SOURCE_HISTORY_PATTERNS:
                    if pattern.search(text):
                        errors.append(f"historical transformation marker: {relative}")
                        break
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    errors.append(f"possible embedded credential: {relative}")
                    break

    if errors:
        raise RuntimeError("HERFY_SOURCE_HYGIENE_FAILED\n - " + "\n - ".join(errors))
    print("HERFY_SOURCE_HYGIENE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
