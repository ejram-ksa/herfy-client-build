from __future__ import annotations

import re
from dataclasses import dataclass

_RESULT_PATTERN = re.compile(
    r"^HERFY_VALIDATOR_RESULT\s+name=(?P<name>[^\s]+)\s+"
    r"status=(?P<status>passed|partial|skipped)(?:\s+details=(?P<details>.*))?$",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    name: str
    status: str
    details: str = ""


def parse_validation_result(output: str, *, default_name: str) -> ValidationResult:
    text = str(output or "")
    matches = list(_RESULT_PATTERN.finditer(text))
    if not matches:
        upper = text.upper()
        if "SKIPPED" in upper or "PARTIAL" in upper:
            return ValidationResult(
                default_name,
                "partial",
                "unstructured-output-reported-incomplete",
            )
        return ValidationResult(default_name, "passed", "")
    match = matches[-1]
    return ValidationResult(
        name=str(match.group("name") or default_name),
        status=str(match.group("status") or "passed"),
        details=str(match.group("details") or "").strip(),
    )


def format_validation_result(
    name: str, status: str, details: str = ""
) -> str:
    normalized = str(status or "").strip().lower()
    if normalized not in {"passed", "partial", "skipped"}:
        raise ValueError(f"unsupported validation status: {status}")
    detail_text = " ".join(str(details or "").split())
    suffix = f" details={detail_text}" if detail_text else ""
    return f"HERFY_VALIDATOR_RESULT name={name} status={normalized}{suffix}"


__all__ = [
    "ValidationResult",
    "parse_validation_result",
    "format_validation_result",
]
