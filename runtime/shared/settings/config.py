from __future__ import annotations
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from urllib.parse import urlsplit, urlunsplit
from typing import Any
from dataclasses import dataclass, field
from collections.abc import Iterable
from runtime.shared.booleans import parse_bool
import json
import logging
import math
import os
import sys
from functools import lru_cache
from pathlib import Path
from runtime.shared.errors import STATE_OPERATION_EXCEPTIONS

logger = logging.getLogger(__name__)
APP_DISPLAY_NAME = "Herfy Client"
APP_ORGANIZATION_NAME = "Herfy"
APP_RUNTIME_DIR_NAME = "HerfyClient"
APP_DESKTOP_APP_ID = "Herfy.HerfyClient"
APPDATA_DIR_NAME = APP_RUNTIME_DIR_NAME
DEFAULT_LANGUAGE = "ar"
DEFAULT_FONT_FAMILY = "Segoe UI"
DEFAULT_FONT_SIZE_PT = 10
DEFAULT_DATE_FORMAT = "yyyy-MM-dd"
DEFAULT_SERVER_BASE_URL = "https://herfy.online/api"
AUTHORITATIVE_SERVER_BASE_URL = DEFAULT_SERVER_BASE_URL
DEFAULT_UPDATES_BASE_URL = "https://herfy.online"
SERVER_URL = DEFAULT_SERVER_BASE_URL
UPDATES_URL = DEFAULT_UPDATES_BASE_URL
TRANSLATIONS_RELATIVE_PATH = ("runtime", "resources", "i18n")
THEME_QSS_RELATIVE_PATH = ("runtime", "resources", "theme.qss")
LOGO_RELATIVE_PATH = ("runtime", "resources", "images", "logo.png")
APP_ICON_RELATIVE_PATH = ("runtime", "resources", "images", "app_icon.ico")
NOTIFICATION_SOUND_DIR_RELATIVE_PATH = ("runtime", "resources", "sounds")
IS_WINDOWS = sys.platform.startswith("win")
translations: dict[str, str] = {}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resolve_or_none(value: str | Path | None) -> Path | None:
    if value in (None, ""):
        return None
    try:
        return Path(value).resolve()
    except STATE_OPERATION_EXCEPTIONS:
        return None


def source_root_dir() -> Path:
    try:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "main.py").exists() and ((parent / "runtime" / "resources").exists() or (parent / "resources").exists()):
                return parent
        candidate = current.parent
    except STATE_OPERATION_EXCEPTIONS:
        candidate = Path.home()
    except IndexError:
        candidate = Path.home()
    resolved = _resolve_or_none(candidate)
    return resolved or Path.home().resolve()


def bundled_root_dir() -> Path:
    if is_frozen():
        bundled = _resolve_or_none(getattr(sys, "_MEIPASS", None))
        if bundled is not None:
            return bundled
    return source_root_dir()


def executable_dir() -> Path:
    if is_frozen():
        executable = _resolve_or_none(sys.executable)
        if executable is not None:
            return executable.parent
    argv_path = _resolve_or_none(sys.argv[0] if sys.argv else None)
    return argv_path.parent if argv_path is not None else source_root_dir()


def _clean_parts(parts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple((str(part).strip("/\\") for part in parts if str(part)))


def bundled_or_source_path(*parts: str) -> Path:
    relative = Path(*_clean_parts(parts)) if parts else Path()
    for base in (bundled_root_dir(), executable_dir(), source_root_dir()):
        candidate = _resolve_or_none(base / relative)
        if candidate is not None and candidate.exists():
            return candidate
    return (source_root_dir() / relative).resolve()


def resource_path(*parts: str) -> str:
    return str(bundled_or_source_path(*parts))


def app_root_dir() -> Path:
    """Return the single writable runtime root.

    Windows always uses the user's Roaming profile:
    %APPDATA%\\HerfyClient

    Installation files stay under Program Files and are never mixed with
    settings, logs, cache, database, downloaded updates, or notification state.
    """
    if IS_WINDOWS:
        roaming = str(os.environ.get("APPDATA") or "").strip()
        target = (
            Path(roaming) / APPDATA_DIR_NAME
            if roaming
            else Path.home() / "AppData" / "Roaming" / APPDATA_DIR_NAME
        )
        try:
            from runtime.shared.settings.runtime_migration import (
                migrate_previous_localappdata,
                migrate_previous_settings_filename,
            )

            migrate_previous_localappdata(target)
            migrate_previous_settings_filename(target)
        except (ImportError, OSError, RuntimeError, ValueError):
            logger.debug("Previous runtime migration was skipped", exc_info=True)
        return target
    return Path.home() / ".config" / APPDATA_DIR_NAME


def ensure_runtime_dirs() -> Path:
    root = app_root_dir()
    for path in (root, root / "logs", root / "database", root / "cache"):
        path.mkdir(parents=True, exist_ok=True)
    return root


def app_data_path(*parts: str) -> str:
    return str(ensure_runtime_dirs().joinpath(*_clean_parts(parts)).resolve())


def log_file_path(name: str = "app.log") -> str:
    return app_data_path("logs", name)


def db_file_path(name: str = "products.db") -> str:
    return app_data_path("database", name)


def settings_ini_path() -> str:
    return app_data_path("settings.ini")


def server_url_path() -> str:
    return "<managed-by-release-config>"


def updates_url_path() -> str:
    return "<managed-by-release-config>"


def runtime_cache_path(name: str) -> str:
    return app_data_path("cache", name)


def prepare_runtime_environment() -> str:
    root = ensure_runtime_dirs()
    return str(root)


def _translation_service():
    from runtime.application.services import translations as service

    return service


def _catalog() -> dict[str, dict[str, str]]:
    """Return the central i18n catalog keyed by language code."""
    service = _translation_service()
    return {"ar": service.language_entries("ar"), "en": service.language_entries("en")}


def available_languages() -> list[str]:
    """Return canonical language codes supported by the application."""
    return _translation_service().available_languages()


def language_entries(language: str | None = None) -> dict[str, str]:
    """Return entries for a canonical or public language value."""
    return _translation_service().language_entries(language)


def is_rtl_language(language: str | None) -> bool:
    """Return whether the language uses RTL layout direction."""
    return _translation_service().is_rtl(language)


def load_translations(language: str = DEFAULT_LANGUAGE) -> None:
    """Select the active application language."""
    global translations
    service = _translation_service()
    active = service.set_language(language)
    translations = service.language_entries(active)


def _(text: str) -> str:
    """Translate a key or public source phrase using the central i18n service."""
    return _translation_service().tr(str(text or ""))


load_translations(DEFAULT_LANGUAGE)
_RELEASE_CONFIG_FILE = "version.json"


def _normalize_search_roots(search_roots: Iterable[str | Path] | None) -> list[Path]:
    normalized: list[Path] = []
    if not search_roots:
        return normalized
    for item in search_roots:
        if item in (None, ""):
            continue
        try:
            normalized.append(Path(item).resolve())
        except SERVICE_OPERATION_EXCEPTIONS:
            normalized.append(Path(item))
    return normalized


@dataclass(frozen=True)
class CacheTTL:
    metadata: int = 15
    catalog: int = 120
    alerts: int = 5


@dataclass(frozen=True)
class AppConfig:
    server_base_url: str
    updates_base_url: str
    http_timeout_seconds: float = 10.0
    request_verify_ssl: bool = True
    realtime_enabled: bool = True
    sync_pull_limit: int = 200
    cache_ttl_seconds: CacheTTL = field(default_factory=CacheTTL)
    production: bool = True


_DEFAULT_CONFIG_CACHE_MARKER = "default-config"


def _safe_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else float(default)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _safe_int(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    if minimum is not None:
        parsed = max(int(minimum), parsed)
    return parsed


def _default_remote_scheme() -> str:
    parts = urlsplit(str(DEFAULT_SERVER_BASE_URL or "").strip())
    return str(parts.scheme or "https").strip().lower() or "https"


def _prefer_https(host: str, current_scheme: str = "") -> str:
    normalized = str(host or "").strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"} or normalized.startswith(
        "192.168."
    ):
        return current_scheme or "http"
    return current_scheme or _default_remote_scheme()


def normalize_api_base_url(url: str, *, default: str = DEFAULT_SERVER_BASE_URL) -> str:
    raw = str(url or "").strip()
    if not raw:
        raw = str(default or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        bare = raw.lstrip("/")
        host = bare.split("/", 1)[0].split(":", 1)[0].strip().lower()
        raw = f"{_prefer_https(host)}://{bare}"
    parts = urlsplit(raw)
    scheme = _prefer_https(parts.hostname or "", parts.scheme)
    path = str(parts.path or "").rstrip("/")
    if not path.endswith("/api"):
        path = f"{path}/api" if path else "/api"
    return urlunsplit((scheme, parts.netloc, path, "", "")).rstrip("/")


def normalize_updates_base_url(
    url: str, *, fallback_server_base_url: str = DEFAULT_SERVER_BASE_URL
) -> str:
    raw = str(url or "").strip()
    if not raw:
        server_base = normalize_api_base_url(fallback_server_base_url)
        return server_base[:-4] if server_base.endswith("/api") else server_base
    if not raw.startswith(("http://", "https://")):
        bare = raw.lstrip("/")
        host = bare.split("/", 1)[0].split(":", 1)[0].strip().lower()
        raw = f"{_prefer_https(host)}://{bare}"
    parts = urlsplit(raw)
    scheme = _prefer_https(parts.hostname or "", parts.scheme)
    path = str(parts.path or "").rstrip("/")
    if path.endswith("/api"):
        path = path[:-4].rstrip("/")
    return urlunsplit((scheme, parts.netloc, path, "", "")).rstrip("/")


def _path_candidates(
    filename: str,
    *,
    search_roots: Iterable[str | Path] | None = None,
    include_runtime: bool = False,
) -> list[Path]:
    candidates: list[Path] = []
    if include_runtime:
        candidates.append(Path(app_data_path(filename)))
    for root in [
        *_normalize_search_roots(search_roots),
        executable_dir(),
        bundled_root_dir(),
    ]:
        candidates.append(root / filename)
    ordered: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
        except SERVICE_OPERATION_EXCEPTIONS:
            resolved = str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(candidate)
    return ordered


def _load_release_payload(
    *, search_roots: Iterable[str | Path] | None = None
) -> dict[str, Any]:
    for candidate in _path_candidates(_RELEASE_CONFIG_FILE, search_roots=search_roots):
        try:
            if candidate.exists():
                payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
                if isinstance(payload, dict):
                    return payload
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.warning(
                "Failed to read release config from %s", candidate, exc_info=True
            )
    return {}


def _resolve_server_base_url(
    release_payload: dict[str, Any],
    *,
    search_roots: Iterable[str | Path] | None = None,
    include_runtime: bool = True,
) -> str:
    """Use the real production server; local and environment overrides are disabled."""
    del release_payload, search_roots, include_runtime
    return AUTHORITATIVE_SERVER_BASE_URL


def _resolve_updates_base_url(
    release_payload: dict[str, Any],
    server_base_url: str,
    *,
    search_roots: Iterable[str | Path] | None = None,
    include_runtime: bool = True,
) -> str:
    del search_roots, include_runtime
    env = str(os.getenv("PTS_UPDATES_BASE_URL", "") or "").strip()
    if env:
        return normalize_updates_base_url(env, fallback_server_base_url=server_base_url)
    configured = str(release_payload.get("updates_base_url") or UPDATES_URL).strip()
    return normalize_updates_base_url(
        configured, fallback_server_base_url=server_base_url
    )


def _build_app_config(
    *, search_roots: Iterable[str | Path] | None = None, include_runtime: bool = True
) -> AppConfig:
    release_payload = _load_release_payload(search_roots=search_roots)
    server_base_url = _resolve_server_base_url(
        release_payload, search_roots=search_roots, include_runtime=include_runtime
    )
    updates_base_url = _resolve_updates_base_url(
        release_payload,
        server_base_url,
        search_roots=search_roots,
        include_runtime=include_runtime,
    )
    cache_payload = (
        release_payload.get("cache_ttl_seconds")
        if isinstance(release_payload.get("cache_ttl_seconds"), dict)
        else {}
    )
    production = parse_bool(
        os.getenv("PTS_PRODUCTION", release_payload.get("production", True)), True
    )
    request_verify_ssl = parse_bool(
        os.getenv(
            "PTS_REQUESTS_VERIFY", release_payload.get("request_verify_ssl", True)
        ),
        True,
    )
    if production and (not request_verify_ssl):
        logger.warning(
            "Ignoring request_verify_ssl=False while production mode is enabled"
        )
        request_verify_ssl = True
    return AppConfig(
        server_base_url=server_base_url,
        updates_base_url=updates_base_url,
        http_timeout_seconds=max(
            1.0,
            min(
                120.0,
                _safe_float(
                    os.getenv(
                        "PTS_HTTP_TIMEOUT",
                        release_payload.get("http_timeout_seconds", 10.0),
                    ),
                    10.0,
                ),
            ),
        ),
        request_verify_ssl=request_verify_ssl,
        realtime_enabled=parse_bool(
            os.getenv(
                "PTS_REALTIME_ENABLED", release_payload.get("realtime_enabled", True)
            ),
            True,
        ),
        sync_pull_limit=_safe_int(
            os.getenv(
                "PTS_SYNC_PULL_LIMIT", release_payload.get("sync_pull_limit", 200)
            ),
            200,
            minimum=1,
        ),
        cache_ttl_seconds=CacheTTL(
            metadata=_safe_int(cache_payload.get("metadata", 15), 15, minimum=1),
            catalog=_safe_int(cache_payload.get("catalog", 120), 120, minimum=1),
            alerts=_safe_int(cache_payload.get("alerts", 5), 5, minimum=1),
        ),
        production=production,
    )


@lru_cache(maxsize=1)
def _load_default_app_config(_token: str = _DEFAULT_CONFIG_CACHE_MARKER) -> AppConfig:
    return _build_app_config()


def load_app_config(
    *, search_roots: Iterable[str | Path] | None = None, include_runtime: bool = True
) -> AppConfig:
    if not search_roots and include_runtime:
        return _load_default_app_config()
    return _build_app_config(search_roots=search_roots, include_runtime=include_runtime)


def clear_app_config_cache() -> None:
    _load_default_app_config.cache_clear()


def get_app_config() -> AppConfig:
    return load_app_config()


def get_server_base_url() -> str:
    return get_app_config().server_base_url


def get_updates_base_url() -> str:
    return get_app_config().updates_base_url


def get_http_timeout_seconds() -> float:
    return get_app_config().http_timeout_seconds


def get_request_verify_ssl() -> bool:
    return get_app_config().request_verify_ssl


def get_cache_ttl() -> CacheTTL:
    return get_app_config().cache_ttl_seconds
