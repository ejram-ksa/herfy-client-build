from __future__ import annotations


def normalize_feedback_severity(severity: str | None, default: str = "info") -> str:
    token = str(severity or "").strip().lower()
    aliases = {
        "warn": "warning",
        "error": "danger",
        "critical": "danger",
        "ok": "success",
        "": default,
    }
    value = aliases.get(token, token)
    if value in {"info", "warning", "danger", "success", "neutral", "muted"}:
        return value
    return str(default or "info")
