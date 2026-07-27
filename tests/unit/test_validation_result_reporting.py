from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOLS = ROOT / "build" / "release"
if str(RELEASE_TOOLS) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOLS))

import source_manifest  # noqa: E402
import verify_all  # noqa: E402
from validation_result import (  # noqa: E402
    format_validation_result,
    parse_validation_result,
)


def test_validation_result_parser_uses_last_structured_result() -> None:
    output = "\n".join(
        [
            format_validation_result("first", "partial", "qt=not-run"),
            "ordinary output",
            format_validation_result("final", "passed", "qt=ok"),
        ]
    )
    result = parse_validation_result(output, default_name="fallback")
    assert result.name == "final"
    assert result.status == "passed"
    assert result.details == "qt=ok"




def test_unstructured_skipped_output_cannot_be_reported_as_passed() -> None:
    result = parse_validation_result(
        "HERFY_SOMETHING_OK qt=SKIPPED(PyQt5-unavailable)",
        default_name="unstructured-validator.py",
    )
    assert result.status == "partial"
    assert result.details == "unstructured-output-reported-incomplete"


def test_validator_partial_status_is_not_reported_as_passed(monkeypatch) -> None:
    monkeypatch.setattr(
        verify_all.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=format_validation_result("dummy", "partial", "qt=not-run"),
        ),
    )
    status = verify_all._run_validator(
        "dummy.py", env={}, require_complete=False
    )
    assert status == "partial"


def test_complete_runtime_gate_rejects_partial_validator(monkeypatch) -> None:
    monkeypatch.setattr(
        verify_all.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=format_validation_result("dummy", "partial", "qt=not-run"),
        ),
    )
    with pytest.raises(SystemExit, match="HERFY_VALIDATOR_INCOMPLETE"):
        verify_all._run_validator("dummy.py", env={}, require_complete=True)


def test_source_manifest_records_partial_validation_truthfully(tmp_path: Path) -> None:
    (tmp_path / "version.json").write_text(
        json.dumps(
            {
                "app_version": "2.18.1",
                "package_name": "test-source",
                "artifact_kind": "source",
                "production": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    manifest = source_manifest.write_source_metadata(
        pytest_passed=10,
        validator_results={"qt.py": "partial", "static.py": "passed"},
        quality_results={"ruff": "passed", "black": "not_requested"},
        platform="linux",
        root=tmp_path,
    )

    assert manifest["schema_version"] == 3
    assert manifest["production"] is False
    assert manifest["source_validation"]["complete_runtime_validation"] is False
    assert manifest["source_validation"]["source_gate"] == "partial"
    verified = source_manifest.verify_source_metadata(tmp_path)
    assert verified["source_validation"]["validators"]["qt.py"] == "partial"
