from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any
from runtime.shared.errors import FILESYSTEM_OPERATION_EXCEPTIONS, PARSE_OPERATION_EXCEPTIONS

logger = logging.getLogger(__name__)
_LANGUAGE = "ar"
_LANG_META = {
    "ar": {"label_key": "settings.language.ar", "direction": "RTL"},
    "en": {"label_key": "settings.language.en", "direction": "LTR"},
}
_LANGUAGE_ALIASES = {
    "arabic": "ar",
    "عربي": "ar",
    "العربية": "ar",
    "ar_sa": "ar",
    "ar-sa": "ar",
    "ar": "ar",
    "english": "en",
    "en_us": "en",
    "en-us": "en",
    "en": "en",
}
_CATALOG: dict[str, dict[str, str]] = {}


def normalize_language_code(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "ar"
    return _LANGUAGE_ALIASES.get(
        raw.lower(), raw.lower() if raw.lower() in _LANG_META else "ar"
    )


def _resource_root() -> Path:
    return Path(__file__).resolve().parents[2] / "resources"


def _i18n_dir() -> Path:
    return _resource_root() / "i18n"


def _load_language(language_code: str) -> dict[str, str]:
    path = _i18n_dir() / f"{language_code}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (*FILESYSTEM_OPERATION_EXCEPTIONS, *PARSE_OPERATION_EXCEPTIONS):
        logger.exception("Failed to load i18n catalog: %s", path)
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def _catalog() -> dict[str, dict[str, str]]:
    global _CATALOG
    if not _CATALOG:
        _CATALOG = {code: _load_language(code) for code in _LANG_META}
    return _CATALOG


def reload_catalog() -> None:
    global _CATALOG
    _CATALOG = {}
    _catalog()


def available_languages() -> list[str]:
    return ["ar", "en"]


def language_metadata(language_code: str | None = None) -> dict[str, str]:
    code = normalize_language_code(language_code or _LANGUAGE)
    return {"code": code, **_LANG_META.get(code, _LANG_META["ar"])}


def is_rtl(language_code: str | None = None) -> bool:
    return language_metadata(language_code).get("direction") == "RTL"


def get_language() -> str:
    return _LANGUAGE


def set_language(language_code: str | None) -> str:
    global _LANGUAGE
    _LANGUAGE = normalize_language_code(language_code)
    return _LANGUAGE


def language_entries(language_code: str | None = None) -> dict[str, str]:
    code = normalize_language_code(language_code or _LANGUAGE)
    catalog = _catalog()
    return dict(catalog.get(code) or catalog.get("en") or {})


_PLACEHOLDER_RE = re.compile("\\{([A-Za-z_][A-Za-z0-9_]*)\\}")


def placeholders(value: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(str(value or "")))


def tr_for_language(language_code: str | None, key: str, **params: Any) -> str:
    """Translate without mutating the process-wide active language."""
    raw_key = str(key or "")
    if not raw_key:
        return ""
    catalog = _catalog()
    language = normalize_language_code(language_code)
    selected = catalog.get(language, {})
    fallback_catalog = catalog.get("en", {})
    normalized = " ".join(raw_key.split())
    value = selected.get(raw_key)
    if value is None and normalized != raw_key:
        value = selected.get(normalized)
    if value is None:
        value = fallback_catalog.get(raw_key)
    if value is None and normalized != raw_key:
        value = fallback_catalog.get(normalized)
    if value is None:
        value = raw_key
    if params:
        try:
            value = value.format(**params)
        except (KeyError, IndexError, ValueError):
            logger.debug(
                "Translation placeholder mismatch for key=%s language=%s",
                raw_key,
                language,
                exc_info=True,
            )
    return value


def tr(key: str, **params: Any) -> str:
    return tr_for_language(_LANGUAGE, key, **params)


def format_days_text(
    days: int | None, *, expired: bool = False, language_code: str | None = None
) -> str:
    language = normalize_language_code(language_code or get_language())

    def translate(key: str, **params: Any) -> str:
        return tr_for_language(language, key, **params)

    if days is None:
        return translate("expiry.detail.unknown")
    n = abs(int(days))
    if expired:
        if n == 1:
            return translate("expiry.detail.expired_day_ago")
        if n == 2:
            return translate("expiry.detail.expired_two_days_ago")
        if language == "ar" and n > 10:
            return f"قد مضى {n} يوم"
        return translate("expiry.detail.expired_days_ago", days=n)
    if n == 0:
        return translate("expiry.detail.expires_today")
    if n == 1:
        return translate("expiry.detail.remaining_day")
    if n == 2:
        return translate("expiry.detail.remaining_two_days")
    if language == "ar" and n > 10:
        return f"تبقى {n} يوم"
    return translate("expiry.detail.remaining_days", days=n)
