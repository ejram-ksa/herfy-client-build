from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from source_manifest import write_source_metadata
from validation_result import parse_validation_result

ROOT = Path(__file__).resolve().parents[2]
VALIDATORS = (
    "verify_structure_contract.py",
    "verify_dependency_contract.py",
    "verify_architecture.py",
    "verify_server_authority_contract.py",
    "verify_update_install_contract.py",
    "verify_canonical_paths_and_update.py",
    "verify_deep_runtime_contract.py",
    "verify_runtime_imports.py",
    "verify_pyqt5_runtime_compat.py",
    "verify_tracking_monitoring_notifications_contract.py",
    "verify_notification_runtime_contract.py",
    "verify_full_source_contract.py",
)
QUALITY_TARGETS = (
    "main.py",
    "__main__.py",
    "cli.py",
    "runtime_health.py",
    "runtime_notification_health.py",
    "runtime_requirements.py",
    "runtime",
    "build/release",
    "build/tools",
    "tests",
)
CACHE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "htmlcov",
}
CACHE_FILE_NAMES = {".coverage", "coverage.xml"}
CACHE_SUFFIXES = {".pyc", ".pyo"}


def _run(
    command: list[str], *, env: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    print("+", subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed


def _run_validator(
    validator: str, *, env: dict[str, str], require_complete: bool
) -> str:
    command = [sys.executable, str(Path("build/release") / validator)]
    print("+", subprocess.list2cmdline(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = str(completed.stdout or "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    parsed = parse_validation_result(output, default_name=validator)
    if require_complete and parsed.status != "passed":
        raise SystemExit(
            "HERFY_VALIDATOR_INCOMPLETE "
            f"validator={validator} status={parsed.status} details={parsed.details}"
        )
    return parsed.status


def _clean_source_caches() -> int:
    removed = 0
    for path in sorted(ROOT.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and path.name in CACHE_DIR_NAMES:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        elif path.is_file() and (
            path.name in CACHE_FILE_NAMES
            or path.name.startswith(".coverage.")
            or path.suffix.lower() in CACHE_SUFFIXES
        ):
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                pass
    return removed


def _verify_version(env: dict[str, str]) -> None:
    metadata = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    expected = str(metadata.get("app_version") or "").strip()
    if not expected:
        raise SystemExit("version.json does not contain app_version")
    completed = subprocess.run(
        [sys.executable, "main.py", "--version"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    actual = completed.stdout.strip()
    if completed.returncode != 0 or actual != expected:
        raise SystemExit(
            "HERFY_VERSION_CONTRACT_FAILED "
            f"expected={expected!r} actual={actual!r} stderr={completed.stderr.strip()!r}"
        )
    print(f"HERFY_VERSION_CONTRACT_OK version={expected}")


def _verify_python_311_syntax() -> int:
    checked = 0
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in CACHE_DIR_NAMES for part in path.relative_to(ROOT).parts):
            continue
        source = path.read_text(encoding="utf-8-sig")
        ast.parse(source, filename=str(path), feature_version=(3, 11))
        checked += 1
    print(f"HERFY_PYTHON_311_SYNTAX_OK files={checked}")
    return checked


def _run_compileall(env: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory(prefix="herfy-pycache-") as cache_dir:
        compile_env = dict(env)
        compile_env["PYTHONPYCACHEPREFIX"] = cache_dir
        _run([sys.executable, "-m", "compileall", "-q", "."], env=compile_env)
    print("HERFY_COMPILEALL_OK")


def _verify_source_archive_pipeline(env: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory(prefix="herfy-source-package-") as temp_dir:
        archive_path = Path(temp_dir) / "source.zip"
        _run(
            [
                sys.executable,
                "build/release/build_source_archive.py",
                str(ROOT),
                str(archive_path),
            ],
            env=env,
        )
        _run(
            [
                sys.executable,
                "build/release/verify_source_archive.py",
                str(archive_path),
                "--source-root",
                str(ROOT),
                "--verify-metadata",
            ],
            env=env,
        )
    print("HERFY_SOURCE_ARCHIVE_PIPELINE_OK")


def _run_tests(env: dict[str, str]) -> int:
    with tempfile.TemporaryDirectory(prefix="herfy-pytest-") as temp_dir:
        report_path = Path(temp_dir) / "pytest.xml"
        cache_dir = Path(temp_dir) / "cache"
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-o",
                f"cache_dir={cache_dir}",
                f"--junitxml={report_path}",
            ],
            env=env,
        )
        root = ET.parse(report_path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
        failures = sum(int(suite.attrib.get("failures", "0")) for suite in suites)
        errors = sum(int(suite.attrib.get("errors", "0")) for suite in suites)
        skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
        passed = tests - failures - errors - skipped
        if failures or errors or passed < 0:
            raise SystemExit("HERFY_PYTEST_REPORT_FAILED")
        print(f"HERFY_PYTEST_OK passed={passed} skipped={skipped}")
        return passed


def _quality_tool_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _run_quality(
    env: dict[str, str], *, require_tools: bool, enforce_format: bool
) -> dict[str, str]:
    ruff_available = _quality_tool_available("ruff")
    black_available = _quality_tool_available("black")
    if require_tools and not ruff_available:
        raise SystemExit("HERFY_QUALITY_TOOLS_FAILED: ruff is unavailable")
    if require_tools and enforce_format and not black_available:
        raise SystemExit("HERFY_QUALITY_TOOLS_FAILED: black is unavailable")

    results: dict[str, str] = {}
    if ruff_available:
        _run(
            [sys.executable, "-m", "ruff", "check", "--no-cache", *QUALITY_TARGETS],
            env=env,
        )
        results["ruff"] = "passed"
        print("HERFY_RUFF_OK")
    else:
        results["ruff"] = "skipped_tool_unavailable"
        print("HERFY_RUFF_SKIPPED reason=tool-unavailable")

    if enforce_format:
        if black_available:
            _run(
                [sys.executable, "-m", "black", "--check", *QUALITY_TARGETS],
                env=env,
            )
            results["black"] = "passed"
            print("HERFY_BLACK_OK")
        else:
            results["black"] = "skipped_tool_unavailable"
            print("HERFY_BLACK_SKIPPED reason=tool-unavailable")
    else:
        results["black"] = "not_requested"
        print("HERFY_BLACK_SKIPPED reason=format-gate-not-requested")
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--require-quality-tools", action="store_true")
    parser.add_argument("--enforce-format", action="store_true")
    parser.add_argument(
        "--require-complete-runtime",
        action="store_true",
        default=sys.platform.startswith("win"),
        help="Fail when a validator reports partial or skipped runtime coverage.",
    )
    args = parser.parse_args()

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("PYTHONUTF8", "1")

    _clean_source_caches()
    _verify_version(env)
    _verify_python_311_syntax()
    _run_compileall(env)
    pytest_passed = None if args.skip_tests else _run_tests(env)

    validator_results: dict[str, str] = {}
    for validator in VALIDATORS:
        validator_results[validator] = _run_validator(
            validator,
            env=env,
            require_complete=bool(args.require_complete_runtime),
        )

    quality_results = _run_quality(
        env,
        require_tools=args.require_quality_tools,
        enforce_format=args.enforce_format,
    )

    removed = _clean_source_caches()
    _run(
        [sys.executable, "build/release/verify_source_hygiene.py"],
        env=env,
    )
    manifest = write_source_metadata(
        pytest_passed=pytest_passed,
        validator_results=validator_results,
        quality_results=quality_results,
        platform=sys.platform,
    )
    _run(
        [sys.executable, "build/release/verify_source_manifest.py"],
        env=env,
    )
    _run(
        [sys.executable, "build/release/verify_source_hygiene.py"],
        env=env,
    )
    _verify_source_archive_pipeline(env)
    _clean_source_caches()
    print(
        "HERFY_FINAL_SOURCE_VALIDATION_OK "
        f"tests={'skipped' if args.skip_tests else pytest_passed} "
        f"files={manifest['file_count']} "
        f"platform={sys.platform} cache_entries_removed={removed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
