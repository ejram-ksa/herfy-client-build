from __future__ import annotations

# ruff: noqa: E402  # Consolidated module keeps section-local imports.

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeUpdateFlowDecision:
    clear_pending_optional_check: bool
    schedule_optional_check: bool
    schedule_mandatory_check: bool


class RuntimeUpdateFlowService:

    @staticmethod
    def after_startup_contract(
        *,
        session_active: bool,
        pending_optional_login_check: bool,
        force_logout: bool,
        mandatory_update_required: bool,
    ) -> RuntimeUpdateFlowDecision:
        if mandatory_update_required:
            return RuntimeUpdateFlowDecision(
                clear_pending_optional_check=bool(pending_optional_login_check),
                schedule_optional_check=False,
                schedule_mandatory_check=True,
            )
        if not session_active or force_logout:
            return RuntimeUpdateFlowDecision(
                clear_pending_optional_check=bool(pending_optional_login_check),
                schedule_optional_check=False,
                schedule_mandatory_check=False,
            )
        if pending_optional_login_check:
            return RuntimeUpdateFlowDecision(
                clear_pending_optional_check=True,
                schedule_optional_check=True,
                schedule_mandatory_check=False,
            )
        return RuntimeUpdateFlowDecision(
            clear_pending_optional_check=False,
            schedule_optional_check=False,
            schedule_mandatory_check=False,
        )


from collections.abc import Callable
from typing import Any



def fetch_preferred_update(
    *,
    current_version: str,
    skipped_version: str,
    patch_fetcher: Callable[[str], Any],
    installer_fetcher: Callable[[str, str], Any],
) -> tuple[str, Any]:
    patch_info = patch_fetcher(current_version)
    patch_package = str(getattr(patch_info, "package_name", "") or "").strip()
    patch_url = str(getattr(patch_info, "download_url", "") or "").strip()
    if bool(getattr(patch_info, "available", False)) and (patch_package or patch_url):
        return ("patch", patch_info)
    return ("installer", installer_fetcher(current_version, skipped_version))


def normalize_update_payload(payload: Any) -> tuple[str, Any]:
    if isinstance(payload, tuple) and len(payload) == 2:
        return (payload[0], payload[1])
    return ("installer", payload)


from collections.abc import Iterable
from runtime.domain.versions import parse_semver, should_update



@dataclass(frozen=True)
class StartupContractDecision:
    clear_cached_session: bool
    show_banner_message: str
    force_logout: bool
    schedule_update_check: bool


class StartupContractService:

    @staticmethod
    def _normalized_roles(values: Iterable[Any] | None) -> set[str]:
        return {str(value).strip() for value in values or [] if str(value).strip()}

    @staticmethod
    def evaluate(
        *,
        startup_config: dict[str, Any] | None,
        upgrade_plan: dict[str, Any] | None,
        session_active: bool,
        role: str = "",
        current_version: str = "0.0.0",
    ) -> StartupContractDecision:
        startup = dict(startup_config or {})
        upgrade = dict(upgrade_plan or {})
        banner = dict(startup.get("startup_banner") or {})
        maintenance = dict(startup.get("maintenance_mode") or {})
        client_runtime = dict(startup.get("client_runtime") or {})
        clear_cached_session = bool(
            not parse_bool(client_runtime.get("allow_cached_login"), True)
            and (not session_active)
        )
        banner_message = ""
        if session_active and parse_bool(banner.get("enabled"), False):
            banner_message = str(banner.get("message") or "").strip()
        force_logout = False
        if session_active and parse_bool(maintenance.get("enabled"), False):
            allowed_roles = StartupContractService._normalized_roles(
                maintenance.get("allow_roles")
            )
            current_role = str(role or "").strip()
            force_logout = not allowed_roles or current_role not in allowed_roles
        minimum_client = str(
            client_runtime.get("force_logout_below_version") or ""
        ).strip()
        if (
            session_active
            and minimum_client
            and (parse_semver(current_version) < parse_semver(minimum_client))
        ):
            force_logout = True
        target_version = str(
            upgrade.get("target_version")
            or upgrade.get("latest_version")
            or upgrade.get("version")
            or upgrade.get("latest")
            or current_version
        ).strip()
        remote_is_newer = should_update(current_version, target_version)
        flag_allows_update = parse_bool(upgrade.get("requires_update"), False)
        schedule_update_check = bool(
            remote_is_newer
            and flag_allows_update
            and parse_bool(upgrade.get("mandatory"), False)
        )
        return StartupContractDecision(
            clear_cached_session=clear_cached_session,
            show_banner_message=banner_message,
            force_logout=force_logout,
            schedule_update_check=schedule_update_check,
        )


import hashlib
import re
import tempfile
from pathlib import Path
from runtime.shared.settings.config import (
    get_http_timeout_seconds,
    get_request_verify_ssl,
    get_updates_base_url,
)
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.application.ports import api_fetch_json, get_server_base_url
from runtime.domain.updates import resolve_download_url
from runtime.infrastructure.network.http import redact_url_for_log



@dataclass(frozen=True)
class UpdateTransportConfig:
    current_version: str
    base_url: str
    api_base_url: str
    http_timeout: float
    verify_ssl: bool


def build_update_transport_config(
    current_version: str, base_url: str | None, api_base_url: str | None
) -> UpdateTransportConfig:
    return UpdateTransportConfig(
        current_version=str(current_version or "0.0.0"),
        base_url=(base_url or get_updates_base_url()).rstrip("/"),
        api_base_url=(api_base_url or get_server_base_url()).rstrip("/"),
        http_timeout=float(get_http_timeout_seconds()),
        verify_ssl=bool(get_request_verify_ssl()),
    )


class UpdateTransportConfigured:

    def __init__(
        self,
        current_version: str,
        base_url: str | None = None,
        api_base_url: str | None = None,
    ) -> None:
        transport = build_update_transport_config(
            current_version, base_url, api_base_url
        )
        self.current_version = transport.current_version
        self.base_url = transport.base_url
        self.api_base_url = transport.api_base_url
        self.http_timeout = transport.http_timeout
        self.verify_ssl = transport.verify_ssl

    def _static_update_json(self, relative_path: str) -> dict[str, Any]:
        """Fetch optional static update metadata from the configured update host."""
        static_url = resolve_download_url(relative_path, self.base_url)
        if not static_url:
            return {}
        try:
            return api_fetch_json(
                static_url, timeout=self.http_timeout, verify=self.verify_ssl
            )
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            logger.info(
                "Static update metadata unavailable %s: %s",
                redact_url_for_log(static_url),
                exc,
            )
            return {}


_MAX_UPDATE_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024


def emit_progress_event(
    progress_callback: Callable[[object], None] | None, *, label: str, **payload: Any
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.exception("%s progress callback raised an exception", label)


def validate_sha256_checksum(value: str, *, package_label: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized and (not re.fullmatch("[0-9a-f]{64}", normalized)):
        raise RuntimeError(f"Invalid SHA256 checksum format for {package_label}")
    return normalized


def download_response_to_target(
    *,
    response,
    target: Path,
    temp_dir: Path,
    temp_prefix: str,
    expected_sha: str,
    expected_size: int,
    progress_callback: Callable[[object], None] | None,
    package_label: str,
    chunk_size: int,
    validate_temp: Callable[[Path], None] | None = None,
) -> Path:
    try:
        declared_size = int(response.headers.get("content-length") or 0)
    except (TypeError, ValueError) as exc:
        response.close()
        raise RuntimeError(f"Invalid Content-Length for {package_label}") from exc
    expected_size = int(expected_size or 0)
    if declared_size < 0 or expected_size < 0:
        response.close()
        raise RuntimeError(f"Invalid declared size for {package_label}")
    if declared_size and expected_size and declared_size != expected_size:
        response.close()
        raise RuntimeError(
            f"{package_label.title()} metadata size mismatch. "
            f"content_length={declared_size} expected={expected_size}"
        )
    total = expected_size or declared_size
    if total > _MAX_UPDATE_DOWNLOAD_BYTES:
        response.close()
        raise RuntimeError(f"{package_label.title()} exceeds the maximum allowed size")
    emit_progress_event(
        progress_callback,
        label=package_label,
        stage="download",
        downloaded=0,
        total=total,
        percent=0,
    )
    digest = hashlib.sha256()
    downloaded = 0
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=temp_prefix, suffix=".tmp", dir=str(temp_dir), delete=False
        ) as stream:
            temp_path = Path(stream.name)
            for chunk in response.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > _MAX_UPDATE_DOWNLOAD_BYTES:
                    raise RuntimeError(
                        f"{package_label.title()} exceeded the maximum allowed size"
                    )
                if expected_size and downloaded > expected_size:
                    raise RuntimeError(
                        f"{package_label.title()} exceeded its declared metadata size"
                    )
                stream.write(chunk)
                digest.update(chunk)
                emit_progress_event(
                    progress_callback,
                    label=package_label,
                    stage="download",
                    downloaded=downloaded,
                    total=total,
                    percent=int(downloaded / total * 100) if total > 0 else 0,
                )
            stream.flush()
            os.fsync(stream.fileno())
        if declared_size > 0 and downloaded != declared_size:
            raise RuntimeError(
                f"{package_label.title()} size mismatch. "
                f"content_length={declared_size} downloaded={downloaded}"
            )
        if expected_size > 0 and downloaded != expected_size:
            raise RuntimeError(
                f"{package_label.title()} size mismatch. "
                f"expected={expected_size} downloaded={downloaded}"
            )
        if expected_sha and digest.hexdigest().lower() != expected_sha:
            raise RuntimeError(f"SHA256 mismatch for {package_label}")
        if validate_temp is not None:
            validate_temp(temp_path)
        temp_path.replace(target)
        emit_progress_event(
            progress_callback,
            label=package_label,
            stage="download",
            downloaded=downloaded,
            total=max(total, downloaded),
            percent=100,
        )
        return target
    except SERVICE_OPERATION_EXCEPTIONS:
        try:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "Ignored %s temporary-file cleanup failure",
                package_label,
                exc_info=True,
            )
        raise
    finally:
        try:
            response.close()
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "Ignored %s response close failure", package_label, exc_info=True
            )


import os
from urllib.parse import unquote, urlparse
from runtime.shared.settings.config import runtime_cache_path
from runtime.shared.booleans import parse_bool, should_require_update_sha256
from runtime.shared.processes import launch_detached, launch_file
from runtime.shared.files import sha256_file
from runtime.domain.update_archive import validate_patch_zip
from runtime.application.ports import api_request
from runtime.domain.updates import (
    normalize_version_payload,
    parse_update_payload,
    safe_update_filename,
)



@dataclass(frozen=True)
class UpdateInfo:
    available: bool
    latest: str
    url: str
    sha256: str = ""
    notes: str = ""
    size: int = 0
    mandatory: bool = False
    skipped: bool = False


class UpdateManager(UpdateTransportConfigured):

    def __init__(
        self,
        current_version: str,
        base_url: str | None = None,
        api_base_url: str | None = None,
    ):
        super().__init__(current_version, base_url, api_base_url)

    def _update_info_from_payload(
        self,
        payload: dict[str, Any],
        skipped_version: str = "",
        *,
        payload_base_url: str | None = None,
    ) -> UpdateInfo:
        descriptor = parse_update_payload(
            payload,
            current_version=self.current_version,
            base_url=payload_base_url or self.api_base_url,
            skipped_version=skipped_version,
        )
        return UpdateInfo(
            available=descriptor.available,
            latest=descriptor.target_version,
            url=descriptor.download_url,
            notes=descriptor.notes,
            mandatory=descriptor.mandatory,
            skipped=descriptor.skipped,
            sha256=descriptor.sha256,
            size=descriptor.size,
        )

    def _server_payload_says_current_is_not_older(
        self,
        payload: dict[str, Any],
        *,
        payload_base_url: str | None = None,
    ) -> bool:
        descriptor = parse_update_payload(
            payload,
            current_version=self.current_version,
            base_url=payload_base_url or self.api_base_url,
        )
        return bool(
            descriptor.target_version
            and (not should_update(self.current_version, descriptor.target_version))
        )

    def fetch(self, skipped_version: str = "") -> UpdateInfo:
        errors: list[str] = []
        try:
            bootstrap = api_fetch_json(
                "/meta/client-bootstrap",
                base_url=self.api_base_url,
                params={"client_version": self.current_version},
            )
            plan = (
                bootstrap.get("upgrade_plan") if isinstance(bootstrap, dict) else None
            )
            if isinstance(plan, dict) and plan:
                info = self._update_info_from_payload(
                    plan, skipped_version=skipped_version
                )
                if (
                    info.available
                    or str(plan.get("reason") or "").strip() == "up_to_date"
                    or self._server_payload_says_current_is_not_older(plan)
                ):
                    return info
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            errors.append(f"bootstrap: {exc}")
        try:
            plan = api_fetch_json(
                "/updates/upgrade-plan",
                base_url=self.api_base_url,
                params={"client_version": self.current_version},
            )
            info = self._update_info_from_payload(plan, skipped_version=skipped_version)
            if info.available:
                return info
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            message = str(exc or "")
            if "404" not in message and "not found" not in message.lower():
                errors.append(f"upgrade-plan: {exc}")
        static_plan = self._static_update_json("/updates/upgrade-plan.json")
        if static_plan:
            info = self._update_info_from_payload(
                static_plan,
                skipped_version=skipped_version,
                payload_base_url=self.base_url,
            )
            if info.available:
                return info
        try:
            manifest = api_fetch_json(
                "/updates/manifest",
                base_url=self.api_base_url,
                params={"client_version": self.current_version},
            )
            info = self._update_info_from_payload(
                manifest, skipped_version=skipped_version
            )
            if info.available:
                return info
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            message = str(exc or "")
            if "404" not in message and "not found" not in message.lower():
                errors.append(f"manifest: {exc}")
        static_manifest = self._static_update_json("/updates/manifest.json")
        if static_manifest:
            info = self._update_info_from_payload(
                static_manifest,
                skipped_version=skipped_version,
                payload_base_url=self.base_url,
            )
            if info.available:
                return info
        static_meta = self._static_update_json("/meta/version.json")
        if static_meta:
            info = self._update_info_from_payload(
                static_meta,
                skipped_version=skipped_version,
                payload_base_url=self.base_url,
            )
            if info.available:
                return info
        try:
            response = api_request(
                "GET",
                "/meta/version",
                base_url=self.api_base_url,
                timeout=self.http_timeout,
                verify=self.verify_ssl,
            )
            try:
                try:
                    data = response.json() if response.content else {}
                except SERVICE_OPERATION_EXCEPTIONS:
                    data = {}
                payload = normalize_version_payload(data, self.api_base_url)
            finally:
                response.close()
            latest = payload.latest
            available = bool(payload.latest) and should_update(
                self.current_version, payload.latest
            )
            skipped = bool(
                skipped_version
                and skipped_version == payload.latest
                and (not payload.mandatory)
            )
            if skipped:
                available = False
            return UpdateInfo(
                available=available,
                latest=latest,
                url=payload.url,
                notes=payload.notes,
                mandatory=payload.mandatory,
                skipped=skipped,
                sha256=getattr(payload, "sha256", ""),
                size=getattr(payload, "size", 0),
            )
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            message = str(exc or "")
            if "404" in message or "not found" in message.lower():
                logger.info(
                    "Version metadata endpoint is unavailable; skipping installer update check"
                )
                return UpdateInfo(available=False, latest="", url="")
            logger.warning(
                "Installer update check failed: %s", "; ".join(errors + [message])
            )
            return UpdateInfo(available=False, latest="", url="")

    @staticmethod
    def _download_dir() -> Path:
        target = Path(runtime_cache_path("updates"))
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _filename_from_headers(url: str, headers: dict | None = None) -> str:
        headers = headers or {}
        cd = str(
            headers.get("content-disposition")
            or headers.get("Content-Disposition")
            or ""
        )
        m = re.search('filename\\*?=(?:UTF-8\\\'\\\')?"?([^";]+)"?', cd)
        if m:
            return safe_update_filename(
                m.group(1), "HerfyUpdate.exe", allowed_suffixes=(".exe", ".msi", ".zip")
            )
        path_name = Path(unquote(urlparse(url).path)).name
        return safe_update_filename(
            path_name or "HerfyUpdate.exe",
            "HerfyUpdate.exe",
            allowed_suffixes=(".exe", ".msi", ".zip"),
        )

    def download_installer(
        self,
        info_or_url: UpdateInfo | str,
        progress_callback: Callable[[object], None] | None = None,
    ) -> Path:
        if isinstance(info_or_url, UpdateInfo):
            url = str(info_or_url.url or "").strip()
            expected_sha = validate_sha256_checksum(
                info_or_url.sha256, package_label="installer package"
            )
            expected_size = int(info_or_url.size or 0)
        else:
            url = str(info_or_url or "").strip()
            expected_sha = ""
            expected_size = 0
        if should_require_update_sha256() and (not expected_sha):
            raise RuntimeError(
                "Update server did not provide the required SHA256 checksum for the installer"
            )
        url = resolve_download_url(url, self.api_base_url)
        if not url:
            raise RuntimeError(
                "No safe installer URL was provided by the update server"
            )
        response = api_request(
            "GET",
            url,
            timeout=max(self.http_timeout, 90),
            verify=self.verify_ssl,
            stream=True,
        )
        filename = self._filename_from_headers(url, dict(response.headers))
        download_dir = self._download_dir()
        target = (download_dir / filename).resolve()
        if target.parent != download_dir.resolve():
            raise RuntimeError("Unsafe installer filename was rejected")
        return download_response_to_target(
            response=response,
            target=target,
            temp_dir=download_dir,
            temp_prefix="installer_",
            expected_sha=expected_sha,
            expected_size=expected_size,
            progress_callback=progress_callback,
            package_label="installer package",
            chunk_size=1024 * 512,
        )

    @classmethod
    def _launch_installer_silent(cls, path: Path) -> bool:
        try:
            path = Path(path).resolve()
            trusted_download_dir = cls._download_dir().resolve()
            if path.parent != trusted_download_dir or not path.is_file():
                raise RuntimeError(
                    "Installer must be a verified file in the application update directory"
                )
            suffix = path.suffix.lower()
            if suffix not in {".exe", ".msi", ".zip"}:
                raise RuntimeError("Unsupported installer type")
            if os.name == "nt" and suffix == ".exe":
                launch_detached(
                    [
                        path,
                        "/SILENT",
                        "/SUPPRESSMSGBOXES",
                        "/NORESTART",
                        "/CLOSEAPPLICATIONS",
                        "/RESTARTAPPLICATIONS",
                        "/AUTORESTARTAPP=1",
                    ],
                    cwd=path.parent,
                )
            elif os.name == "nt" and suffix == ".msi":
                msiexec = (
                    Path(os.environ.get("SYSTEMROOT", "C:\\Windows"))
                    / "System32"
                    / "msiexec.exe"
                ).resolve()
                launch_detached(
                    [msiexec, "/i", path, "/passive", "/norestart"], cwd=path.parent
                )
            elif os.name == "nt":
                launch_file(path)
            else:
                raise RuntimeError(
                    "Automatic installer launch is supported on Windows only"
                )
            return True
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.exception("Failed to launch installer: %s", path)
            return False


import sys
from runtime.shared.settings.config import executable_dir, source_root_dir
from runtime.shared.errors import RemoteRequestError
from runtime.domain.updates import parse_manifest_patch_payload
from runtime.application.services.sync import ServerRuntimeService



@dataclass(frozen=True)
class PatchUpdateInfo:
    available: bool
    current_version: str
    target_version: str
    package_name: str = ""
    notes: str = ""
    mandatory: bool = False
    sha256: str = ""
    size: int = 0
    popup_title: str = "New update available"
    popup_message: str = ""
    download_url: str = ""
    current_supported: bool = True
    reason: str = "up_to_date"


class PatchUpdateService(UpdateTransportConfigured):

    def __init__(
        self,
        current_version: str,
        base_url: str | None = None,
        api_base_url: str | None = None,
    ):
        super().__init__(current_version, base_url, api_base_url)
        self.pending_root = Path(runtime_cache_path("updates/pending"))
        self.pending_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _not_found(exc: Exception) -> bool:
        message = str(exc or "").lower()
        return "404" in message or "not found" in message

    @staticmethod
    def _empty_info(
        current_version: str, reason: str = "up_to_date"
    ) -> PatchUpdateInfo:
        return PatchUpdateInfo(
            available=False,
            current_version=current_version,
            target_version=current_version,
            reason=reason,
        )

    @staticmethod
    def _is_patch_descriptor(package_name: str, download_url: str) -> bool:
        package = str(package_name or "").strip().lower()
        if package.endswith(".zip"):
            return True
        path = urlparse(str(download_url or "")).path.lower()
        return path.endswith(".zip")

    @classmethod
    def patch_runtime_available(cls) -> bool:
        if not getattr(sys, "frozen", False):
            return False
        root = cls.installed_app_root().resolve()
        return (root / "HerfyClient.exe").is_file() and (
            root / "HerfyClientUpdateAgent.exe"
        ).is_file()

    def _patch_runtime_or_empty(self, info: PatchUpdateInfo) -> PatchUpdateInfo:
        if not info.available:
            return info
        if self.patch_runtime_available():
            return info
        logger.info(
            "Patch update is available but the packaged update agent is missing; falling back to installer-style update discovery."
        )
        return self._empty_info(
            self.current_version, reason="patch_runtime_unavailable"
        )

    def _upgrade_plan(self) -> dict[str, Any]:
        try:
            payload = (
                ServerRuntimeService(self.api_base_url)
                .fetch_client_bootstrap(self.current_version)
                .upgrade_plan
            )
            if isinstance(payload, dict) and payload:
                return payload
        except RemoteRequestError as exc:
            if not self._not_found(exc):
                logger.info("Upgrade plan bootstrap unavailable: %s", exc)
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if not self._not_found(exc):
                logger.info("Upgrade plan bootstrap skipped: %s", exc)
        try:
            return api_fetch_json(
                "/updates/upgrade-plan",
                base_url=self.api_base_url,
                params={"client_version": self.current_version},
            )
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if self._not_found(exc):
                logger.info(
                    "Optional patch upgrade-plan endpoint is unavailable; trying static update metadata"
                )
                return self._static_update_json("/updates/upgrade-plan.json")
            static_plan = self._static_update_json("/updates/upgrade-plan.json")
            if static_plan:
                return static_plan
            raise

    def _direct_manifest(self) -> dict[str, Any]:
        try:
            return api_fetch_json(
                "/updates/manifest",
                base_url=self.api_base_url,
                params={"client_version": self.current_version},
            )
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if self._not_found(exc):
                logger.info(
                    "Optional patch manifest endpoint is unavailable; trying static update metadata"
                )
                return self._static_update_json("/updates/manifest.json")
            static_manifest = self._static_update_json("/updates/manifest.json")
            if static_manifest:
                return static_manifest
            raise

    def fetch(self) -> PatchUpdateInfo:
        plan = self._upgrade_plan()
        if isinstance(plan, dict) and plan:
            descriptor = parse_update_payload(
                plan,
                current_version=self.current_version,
                base_url=self.api_base_url,
            )
            if descriptor.target_version and (
                not should_update(self.current_version, descriptor.target_version)
            ):
                return self._empty_info(self.current_version, reason="up_to_date")
            if self._is_patch_descriptor(
                descriptor.package_name, descriptor.download_url
            ):
                return self._patch_runtime_or_empty(
                    PatchUpdateInfo(
                        available=descriptor.available,
                        current_version=self.current_version,
                        target_version=descriptor.target_version,
                        package_name=descriptor.package_name,
                        notes=descriptor.notes,
                        mandatory=descriptor.mandatory,
                        sha256=descriptor.sha256,
                        size=descriptor.size,
                        popup_title=descriptor.popup_title,
                        popup_message=descriptor.popup_message,
                        download_url=descriptor.download_url,
                        current_supported=descriptor.current_supported,
                        reason=descriptor.reason,
                    )
                )
            if descriptor.available and descriptor.download_url:
                logger.info(
                    "Installer-style update plan detected; deferring to UpdateManager"
                )
                return self._empty_info(
                    self.current_version, reason="installer_update_available"
                )
        try:
            manifest = self._direct_manifest()
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            if self._not_found(exc):
                logger.info("Optional patch manifest endpoint is unavailable")
                return self._empty_info(self.current_version)
            raise
        descriptor = parse_manifest_patch_payload(
            manifest,
            current_version=self.current_version,
            base_url=self.api_base_url,
        )
        if not self._is_patch_descriptor(
            descriptor.package_name, descriptor.download_url
        ):
            return self._empty_info(
                self.current_version, reason="no_patch_package_for_current_version"
            )
        return self._patch_runtime_or_empty(
            PatchUpdateInfo(
                available=descriptor.available,
                current_version=self.current_version,
                target_version=descriptor.target_version,
                package_name=descriptor.package_name,
                notes=descriptor.notes,
                mandatory=descriptor.mandatory,
                sha256=descriptor.sha256,
                size=descriptor.size,
                popup_title=descriptor.popup_title,
                popup_message=descriptor.popup_message,
                download_url=descriptor.download_url,
                current_supported=descriptor.current_supported,
                reason=descriptor.reason,
            )
        )

    @staticmethod
    def _filename_from_url(url: str, fallback: str = "HerfyClient_patch.zip") -> str:
        candidate = Path(unquote(urlparse(str(url or "")).path)).name.strip()
        return safe_update_filename(
            candidate or fallback, fallback, allowed_suffixes=(".zip",)
        )

    @staticmethod
    def _resolve_pending_target(root: Path, filename: str) -> Path:
        base = root.resolve()
        target = (root / filename).resolve()
        if target.parent != base:
            raise RuntimeError("Unsafe patch package filename was rejected")
        return target

    @staticmethod
    def _validate_zip(path: Path) -> None:
        validate_patch_zip(path)

    def download_patch(
        self,
        info: PatchUpdateInfo,
        progress_callback: Callable[[object], None] | None = None,
    ) -> Path:
        download_url = str(info.download_url or "").strip()
        package_name = (
            safe_update_filename(
                info.package_name, "HerfyClient_patch.zip", allowed_suffixes=(".zip",)
            )
            if str(info.package_name or "").strip()
            else ""
        )
        expected_sha = validate_sha256_checksum(
            info.sha256, package_label="patch package"
        )
        expected_size = int(info.size or 0)
        if not expected_sha:
            raise RuntimeError(
                "Update server did not provide the required SHA256 checksum for the patch package"
            )
        if expected_size <= 0:
            raise RuntimeError(
                "Update server did not provide a positive size for the patch package"
            )
        if not download_url and package_name:
            download_url = resolve_download_url(
                f"/updates/packages/{package_name}", self.api_base_url
            )
        else:
            download_url = resolve_download_url(download_url, self.api_base_url)
        if not download_url:
            raise RuntimeError(
                "No safe patch package URL was provided by the update server"
            )
        if not package_name:
            package_name = self._filename_from_url(download_url)
        target = self._resolve_pending_target(self.pending_root, package_name)
        response = api_request(
            "GET",
            download_url,
            timeout=max(self.http_timeout, 90),
            verify=self.verify_ssl,
            stream=True,
        )
        return download_response_to_target(
            response=response,
            target=target,
            temp_dir=self.pending_root,
            temp_prefix="patch_",
            expected_sha=expected_sha,
            expected_size=expected_size,
            progress_callback=progress_callback,
            package_label="patch package",
            chunk_size=1024 * 256,
            validate_temp=self._validate_zip,
        )

    @staticmethod
    def installed_app_root() -> Path:
        if getattr(sys, "frozen", False):
            return executable_dir()
        return source_root_dir()

    def validate_install_runtime(self) -> tuple[Path, Path, Path]:
        root = self.installed_app_root().resolve()
        agent_exe = (root / "HerfyClientUpdateAgent.exe").resolve()
        restart_target = (root / "HerfyClient.exe").resolve()
        if not getattr(sys, "frozen", False):
            raise RuntimeError(
                "Online patch updates can be installed only from the packaged HerfyClient.exe release, not from python main.py. Build and run the EXE package during production update testing."
            )
        if agent_exe.parent != root or restart_target.parent != root:
            raise RuntimeError(
                "Update executables must be located inside the packaged application root"
            )
        if not agent_exe.exists():
            raise RuntimeError(
                f"Update agent executable was not found next to HerfyClient.exe: {agent_exe}"
            )
        if not restart_target.exists():
            raise RuntimeError(
                f"Application executable was not found next to the update agent: {restart_target}"
            )
        return (root, agent_exe, restart_target)

    def launch_update_agent(self, patch_zip: Path, info: PatchUpdateInfo) -> None:
        root, agent_exe, restart_target = self.validate_install_runtime()
        patch_zip = Path(patch_zip).resolve()
        pending_root = self.pending_root.resolve()
        if patch_zip.parent != pending_root or patch_zip.suffix.lower() != ".zip":
            raise RuntimeError(
                "Patch package must be a verified archive in the pending update directory"
            )
        if not patch_zip.exists():
            raise RuntimeError(f"Downloaded patch package not found: {patch_zip}")
        expected_sha = validate_sha256_checksum(
            info.sha256, package_label="patch package"
        )
        expected_size = int(info.size or 0)
        if not expected_sha or expected_size <= 0:
            raise RuntimeError(
                "Patch activation requires an exact SHA256 checksum and positive size"
            )
        actual_size = patch_zip.stat().st_size
        if actual_size != expected_size:
            raise RuntimeError(
                f"Patch size changed before activation. expected={expected_size} actual={actual_size}"
            )
        actual_sha = sha256_file(patch_zip).lower()
        if actual_sha != expected_sha:
            raise RuntimeError(
                "Patch checksum changed before activation. "
                f"expected={expected_sha} actual={actual_sha}"
            )
        self._validate_zip(patch_zip)
        launch_detached(
            [
                agent_exe,
                "--apply",
                patch_zip,
                "--root",
                root,
                "--restart",
                restart_target,
                "--wait",
                "60",
                "--sha256",
                expected_sha,
                "--expected-size",
                str(expected_size),
            ],
            cwd=root,
        )
