from __future__ import annotations
from typing import Any
from packaging.version import InvalidVersion, Version
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.strings import normalize_text


def parse_semver(version: Any) -> tuple[int, int, int]:
    parts = []
    for part in normalize_text(version).split("."):
        try:
            parts.append(int(part))
        except SERVICE_OPERATION_EXCEPTIONS:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _packaging_version(value: Any) -> Version:
    text = normalize_text(value) or "0"
    try:
        return Version(text)
    except InvalidVersion:
        return Version(".".join((str(part) for part in parse_semver(text))))


def should_update(local_version: str, remote_version: str) -> bool:
    return _packaging_version(remote_version) > _packaging_version(local_version)
