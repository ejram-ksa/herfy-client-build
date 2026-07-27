from __future__ import annotations
from collections.abc import Iterable


def normalize_branch(branch: str | None) -> str:
    return str(branch or "").strip()


def normalize_branch_list(branches: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for branch in branches or []:
        value = normalize_branch(branch)
        lowered = value.lower()
        if value and lowered not in seen:
            seen.add(lowered)
            cleaned.append(value)
    return cleaned
