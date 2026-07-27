from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "PACKAGE_MANIFEST.json"
CHECKSUMS_PATH = ROOT / "SHA256SUMS.txt"

_EXCLUDED_FILES = {
    MANIFEST_PATH.name,
    CHECKSUMS_PATH.name,
}
_EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "output",
    "publish",
    "venv",
    "htmlcov",
}
_EXCLUDED_FILE_NAMES = {".coverage", "coverage.xml"}


def _generated_at_utc() -> str:
    """Return a reproducible manifest timestamp.

    Release builders may supply ``SOURCE_DATE_EPOCH`` from the source commit.
    A fixed default keeps repeated validations of identical source byte-for-byte
    reproducible instead of rewriting the package solely because time passed.
    """

    raw = str(os.environ.get("SOURCE_DATE_EPOCH") or "").strip()
    try:
        epoch = int(raw) if raw else 946684800  # 2000-01-01T00:00:00Z
        value = datetime.fromtimestamp(max(0, epoch), tz=timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError):
        value = datetime(2000, 1, 1, tzinfo=timezone.utc)
    return value.isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_source_files(root: Path = ROOT) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in _EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
            continue
        if path.is_symlink():
            raise RuntimeError(f"Symbolic links are not allowed: {relative}")
        if not path.is_file() or relative.as_posix() in _EXCLUDED_FILES:
            continue
        if path.name in _EXCLUDED_FILE_NAMES or path.name.startswith(".coverage."):
            continue
        yield path


def build_file_entries(root: Path = ROOT) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in iter_source_files(root):
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return entries


def write_source_metadata(
    *,
    pytest_passed: int | None,
    validator_results: dict[str, str],
    quality_results: dict[str, str],
    platform: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    version_data = json.loads((root / "version.json").read_text(encoding="utf-8"))
    entries = build_file_entries(root)
    normalized_validators = dict(sorted(validator_results.items()))
    normalized_quality = dict(sorted(quality_results.items()))
    validator_status_values = set(normalized_validators.values())
    complete_runtime_validation = bool(normalized_validators) and (
        validator_status_values == {"passed"}
    )
    complete_quality_validation = bool(normalized_quality) and all(
        status == "passed" for status in normalized_quality.values()
    )
    pytest_status = "passed" if pytest_passed is not None else "skipped"
    source_gate = (
        "passed"
        if pytest_status == "passed" and complete_runtime_validation
        else "partial"
    )
    validation = {
        "compileall": "passed",
        "pytest": (
            {"status": "passed", "passed": int(pytest_passed)}
            if pytest_passed is not None
            else {"status": "skipped", "passed": None}
        ),
        "validators": normalized_validators,
        "quality": normalized_quality,
        "host_platform": platform,
        "complete_runtime_validation": complete_runtime_validation,
        "complete_quality_validation": complete_quality_validation,
        "source_gate": source_gate,
        "windows_build": "not_run",
        "windows_runtime_validation": "not_run",
        "code_signing": "not_run",
        "release_gate": "not_ready",
    }
    production_requested = bool(version_data.get("production", False))
    production_ready = (
        production_requested
        and source_gate == "passed"
        and complete_quality_validation
        and platform.startswith("win")
        and validation["windows_build"] == "passed"
        and validation["windows_runtime_validation"] == "passed"
        and validation["code_signing"] == "passed"
    )
    manifest: dict[str, Any] = {
        "schema_version": 3,
        "package": str(version_data.get("package_name") or "").strip(),
        "version": str(version_data.get("app_version") or "").strip(),
        "artifact_kind": str(version_data.get("artifact_kind") or "").strip(),
        "target": "Windows 10/11 x64",
        "python": "3.11 x64",
        "production_requested": production_requested,
        "production": production_ready,
        "generated_at_utc": _generated_at_utc(),
        "python_file_count": sum(
            1 for entry in entries if str(entry["path"]).endswith(".py")
        ),
        "file_count": len(entries),
        "source_validation": validation,
        "files": entries,
    }
    manifest_path = root / MANIFEST_PATH.name
    checksums_path = root / CHECKSUMS_PATH.name
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    checksums_path.write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries),
        encoding="utf-8",
    )
    return manifest


def verify_source_metadata(root: Path = ROOT) -> dict[str, Any]:
    manifest_path = root / MANIFEST_PATH.name
    checksums_path = root / CHECKSUMS_PATH.name
    if not manifest_path.is_file() or not checksums_path.is_file():
        raise RuntimeError("Source manifest or checksum list is missing")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version_data = json.loads((root / "version.json").read_text(encoding="utf-8"))
    expected_entries = build_file_entries(root)
    actual_entries = list(manifest.get("files") or [])

    errors: list[str] = []
    if int(manifest.get("schema_version") or 0) != 3:
        errors.append("unsupported manifest schema")
    if str(manifest.get("version") or "") != str(version_data.get("app_version") or ""):
        errors.append("manifest application version does not match version.json")
    if str(manifest.get("package") or "") != str(version_data.get("package_name") or ""):
        errors.append("manifest package name does not match version.json")
    if actual_entries != expected_entries:
        expected = {str(item["path"]): item for item in expected_entries}
        actual = {str(item.get("path")): item for item in actual_entries}
        missing = sorted(set(expected) - set(actual))
        stale = sorted(set(actual) - set(expected))
        changed = sorted(
            path
            for path in set(expected) & set(actual)
            if expected[path] != actual[path]
        )
        if missing:
            errors.append(f"manifest missing files: {missing}")
        if stale:
            errors.append(f"manifest contains stale files: {stale}")
        if changed:
            errors.append(f"manifest contains changed file metadata: {changed}")

    expected_checksums = "".join(
        f"{entry['sha256']}  {entry['path']}\n" for entry in expected_entries
    )
    actual_checksums = checksums_path.read_text(encoding="utf-8")
    if actual_checksums != expected_checksums:
        errors.append("SHA256SUMS.txt does not match current source files")

    if int(manifest.get("file_count") or -1) != len(expected_entries):
        errors.append("manifest file_count is incorrect")
    expected_python_count = sum(
        1 for entry in expected_entries if str(entry["path"]).endswith(".py")
    )
    if int(manifest.get("python_file_count") or -1) != expected_python_count:
        errors.append("manifest python_file_count is incorrect")

    validation = manifest.get("source_validation") or {}
    validators = validation.get("validators") or {}
    if not isinstance(validators, dict) or not validators:
        errors.append("manifest validator results are missing")
    else:
        invalid_statuses = sorted(
            {str(value) for value in validators.values()}
            - {"passed", "partial", "skipped"}
        )
        if invalid_statuses:
            errors.append(f"manifest has invalid validator statuses: {invalid_statuses}")
        expected_complete = all(value == "passed" for value in validators.values())
        if bool(validation.get("complete_runtime_validation")) != expected_complete:
            errors.append("manifest complete_runtime_validation is inconsistent")
        pytest_result = validation.get("pytest") or {}
        expected_source_gate = (
            "passed"
            if pytest_result.get("status") == "passed" and expected_complete
            else "partial"
        )
        if validation.get("source_gate") != expected_source_gate:
            errors.append("manifest source_gate is inconsistent")
    if bool(manifest.get("production")):
        required_release_states = (
            validation.get("source_gate") == "passed",
            validation.get("complete_quality_validation") is True,
            str(validation.get("host_platform") or "").startswith("win"),
            validation.get("windows_build") == "passed",
            validation.get("windows_runtime_validation") == "passed",
            validation.get("code_signing") == "passed",
            validation.get("release_gate") == "passed",
        )
        if not all(required_release_states):
            errors.append("manifest production=true without complete release gates")

    if errors:
        raise RuntimeError("HERFY_SOURCE_MANIFEST_FAILED\n - " + "\n - ".join(errors))
    return manifest
