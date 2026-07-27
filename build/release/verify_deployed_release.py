from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
_METADATA_LIMIT_BYTES = 2 * 1024 * 1024
_DEFAULT_ARTIFACT_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ReleaseVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseDescriptor:
    source: str
    version: str
    production: bool
    mandatory: bool
    current_supported: bool
    package_name: str
    download_url: str
    sha256: str
    size: int


@dataclass(slots=True)
class VerificationReport:
    status: str
    expected_version: str
    base_url: str
    api_base_url: str
    metadata_only: bool
    homepage_checked: bool
    api_checked: bool
    descriptors: list[dict[str, Any]] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)
    api: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_origin: tuple[str, str, int | None]) -> None:
        super().__init__()
        self._allowed_origin = allowed_origin

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int | None]:
        parts = urlsplit(url)
        try:
            port = parts.port
        except ValueError as exc:
            raise ReleaseVerificationError(f"Invalid URL port: {url}") from exc
        scheme = parts.scheme.lower()
        if port is None:
            port = 443 if scheme == "https" else 80 if scheme == "http" else None
        return (scheme, (parts.hostname or "").lower(), port)

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if self._origin(newurl) != self._allowed_origin:
            raise ReleaseVerificationError(
                f"Cross-origin redirect was rejected: {req.full_url} -> {newurl}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as exc:
        raise ReleaseVerificationError(f"Invalid URL port: {url}") from exc
    scheme = parts.scheme.lower()
    if port is None:
        port = 443 if scheme == "https" else 80 if scheme == "http" else None
    return (scheme, (parts.hostname or "").lower(), port)


def _normalize_base_url(value: str, *, label: str) -> str:
    text = str(value or "").strip().rstrip("/")
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() not in {"http", "https"} or not host:
        raise ReleaseVerificationError(f"{label} must be an absolute HTTP(S) URL.")
    if parts.username is not None or parts.password is not None:
        raise ReleaseVerificationError(f"{label} must not contain credentials.")
    try:
        _ = parts.port
    except ValueError as exc:
        raise ReleaseVerificationError(f"{label} contains an invalid port.") from exc
    if parts.scheme.lower() != "https" and host not in _LOCAL_HOSTS:
        raise ReleaseVerificationError(f"{label} must use HTTPS outside loopback testing.")
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc,
            parts.path.rstrip("/"),
            "",
            "",
        )
    )


def _join(base_url: str, path: str) -> str:
    return urljoin(f"{base_url.rstrip('/')}/", str(path or "").lstrip("/"))


def _request(
    url: str,
    *,
    timeout: float,
    method: str = "GET",
    accept: str = "application/json",
):
    origin = _origin(url)
    context = ssl.create_default_context()
    opener = build_opener(
        _SameOriginRedirectHandler(origin),
        # urllib uses the default verified context for HTTPS; the explicit
        # context is retained on Request handlers through the global opener.
    )
    request = Request(
        url,
        method=method,
        headers={
            "Accept": accept,
            "User-Agent": "HerfyReleaseVerifier/1",
            "Cache-Control": "no-cache",
        },
    )
    try:
        # Build a dedicated HTTPS handler only when needed so TLS verification
        # is explicit and cannot be disabled by caller input.
        if urlsplit(url).scheme.lower() == "https":
            from urllib.request import HTTPSHandler

            opener = build_opener(
                _SameOriginRedirectHandler(origin), HTTPSHandler(context=context)
            )
        return opener.open(request, timeout=timeout)
    except HTTPError as exc:
        raise ReleaseVerificationError(f"HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise ReleaseVerificationError(f"Connection failed for {url}: {exc.reason}") from exc


def _read_limited(stream: BinaryIO, *, limit: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(64 * 1024, limit + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise ReleaseVerificationError(f"{label} exceeded {limit} bytes.")
    return b"".join(chunks)


def _fetch_bytes(url: str, *, timeout: float, limit: int, accept: str) -> bytes:
    with _request(url, timeout=timeout, accept=accept) as response:
        final_url = response.geturl()
        if _origin(final_url) != _origin(url):
            raise ReleaseVerificationError(f"Response changed origin: {url} -> {final_url}")
        raw_length = response.headers.get("Content-Length")
        if raw_length:
            try:
                declared = int(raw_length)
            except ValueError as exc:
                raise ReleaseVerificationError(
                    f"Invalid Content-Length for {url}: {raw_length}"
                ) from exc
            if declared < 0 or declared > limit:
                raise ReleaseVerificationError(
                    f"Declared response size is invalid for {url}: {declared}"
                )
        return _read_limited(response, limit=limit, label=url)


def _fetch_json(url: str, *, timeout: float) -> dict[str, Any]:
    payload = _fetch_bytes(
        url,
        timeout=timeout,
        limit=_METADATA_LIMIT_BYTES,
        accept="application/json",
    )
    try:
        decoded = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"Invalid JSON from {url}: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ReleaseVerificationError(f"JSON root must be an object: {url}")
    return decoded


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise ReleaseVerificationError(f"Invalid boolean value in release metadata: {value!r}")


def _positive_int(value: Any, *, field_name: str, source: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ReleaseVerificationError(
            f"{source} has invalid {field_name}: {value!r}"
        ) from exc
    if result <= 0:
        raise ReleaseVerificationError(f"{source} has non-positive {field_name}: {result}")
    return result


def _safe_package_url(base_url: str, value: str, package_name: str) -> str:
    candidate = str(value or "").strip()
    if not candidate and package_name:
        candidate = f"/updates/packages/{package_name}"
    if not candidate:
        raise ReleaseVerificationError("Release metadata does not contain a package URL.")
    resolved = candidate if urlsplit(candidate).scheme else _join(base_url, candidate)
    parts = urlsplit(resolved)
    if parts.username is not None or parts.password is not None:
        raise ReleaseVerificationError("Package URL contains credentials.")
    if _origin(resolved) != _origin(base_url):
        raise ReleaseVerificationError(f"Package URL changed origin: {resolved}")
    raw_path = str(parts.path or "").replace("\\", "/")
    decoded_path = unquote(unquote(raw_path)).replace("\\", "/")
    normalized_path = re.sub(r"/+", "/", decoded_path)
    approved_paths = {
        f"/updates/packages/{package_name}",
        f"/api/updates/packages/{package_name}",
    }
    if normalized_path not in approved_paths:
        raise ReleaseVerificationError(
            f"Package URL is outside the approved update package path: {resolved}"
        )
    return urlunsplit((parts.scheme, parts.netloc, normalized_path, parts.query, ""))


def _descriptor(
    payload: dict[str, Any],
    *,
    source: str,
    expected_version: str,
    base_url: str,
) -> ReleaseDescriptor:
    nested = payload.get("update") if isinstance(payload.get("update"), dict) else {}
    version = _first_text(
        nested,
        "latest_version",
        "target_version",
        "version",
        "latest",
    ) or _first_text(
        payload,
        "latest_version",
        "target_version",
        "version",
        "latest",
    )
    if version != expected_version:
        raise ReleaseVerificationError(
            f"{source} version mismatch: expected {expected_version}, found {version or '<missing>'}."
        )
    available = _bool(payload.get("available"), False)
    update_available = _bool(payload.get("update_available"), available)
    production = available and update_available
    if not production:
        raise ReleaseVerificationError(
            f"{source} is not marked as an available production release."
        )
    mandatory_raw = payload.get("mandatory")
    force_raw = payload.get("force_update")
    supported_raw = payload.get("current_supported")
    if not isinstance(mandatory_raw, bool) or not isinstance(force_raw, bool):
        raise ReleaseVerificationError(
            f"{source} mandatory and force_update values must be booleans."
        )
    if mandatory_raw != force_raw:
        raise ReleaseVerificationError(
            f"{source} force_update does not match mandatory."
        )
    if not isinstance(supported_raw, bool) or supported_raw is not (not mandatory_raw):
        raise ReleaseVerificationError(
            f"{source} current_supported is inconsistent with mandatory."
        )

    package_name = _first_text(
        nested, "package_name", "setup_package", "package", "filename"
    ) or _first_text(
        payload, "package_name", "setup_package", "package", "filename"
    )
    if not package_name or Path(package_name).name != package_name:
        raise ReleaseVerificationError(f"{source} has an unsafe package name: {package_name!r}")
    if not package_name.lower().endswith(".exe"):
        raise ReleaseVerificationError(f"{source} package is not a Windows installer: {package_name}")

    raw_url = _first_text(nested, "installer_url", "download_url", "url") or _first_text(
        payload, "installer_url", "download_url", "url"
    )
    download_url = _safe_package_url(base_url, raw_url, package_name)
    sha256 = (
        _first_text(nested, "setup_sha256", "sha256", "checksum")
        or _first_text(payload, "setup_sha256", "sha256", "checksum")
    ).lower()
    if not _SHA256_PATTERN.fullmatch(sha256):
        raise ReleaseVerificationError(f"{source} has an invalid SHA-256 value.")
    size_raw = nested.get("setup_size") or nested.get("size") or payload.get(
        "setup_size"
    ) or payload.get("size")
    size = _positive_int(size_raw, field_name="size", source=source)
    return ReleaseDescriptor(
        source=source,
        version=version,
        production=production,
        mandatory=mandatory_raw,
        current_supported=supported_raw,
        package_name=package_name,
        download_url=download_url,
        sha256=sha256,
        size=size,
    )


def _assert_descriptors_match(descriptors: list[ReleaseDescriptor]) -> ReleaseDescriptor:
    if not descriptors:
        raise ReleaseVerificationError("No release descriptors were loaded.")
    canonical = descriptors[0]
    for descriptor in descriptors[1:]:
        comparable = (
            descriptor.version,
            descriptor.mandatory,
            descriptor.current_supported,
            descriptor.package_name,
            descriptor.download_url,
            descriptor.sha256,
            descriptor.size,
        )
        expected = (
            canonical.version,
            canonical.mandatory,
            canonical.current_supported,
            canonical.package_name,
            canonical.download_url,
            canonical.sha256,
            canonical.size,
        )
        if comparable != expected:
            raise ReleaseVerificationError(
                f"Release metadata disagreement: {canonical.source} != {descriptor.source}."
            )
    return canonical


def _verify_homepage(
    *, base_url: str, descriptor: ReleaseDescriptor, timeout: float
) -> dict[str, Any]:
    html = _fetch_bytes(
        f"{base_url}/",
        timeout=timeout,
        limit=_METADATA_LIMIT_BYTES,
        accept="text/html,application/xhtml+xml",
    ).decode("utf-8", errors="replace")
    if descriptor.version not in html:
        raise ReleaseVerificationError(
            f"Homepage does not advertise version {descriptor.version}."
        )
    if descriptor.package_name not in html:
        raise ReleaseVerificationError(
            f"Homepage does not reference package {descriptor.package_name}."
        )
    return {"version_present": True, "package_present": True}


def _verify_api(
    *, api_base_url: str, expected_version: str, timeout: float
) -> dict[str, Any]:
    health = _fetch_json(_join(api_base_url, "/health"), timeout=timeout)
    bootstrap_url = _join(api_base_url, "/meta/client-bootstrap")
    bootstrap_url = f"{bootstrap_url}?{urlencode({'client_version': expected_version})}"
    bootstrap = _fetch_json(bootstrap_url, timeout=timeout)
    upgrade_plan = bootstrap.get("upgrade_plan")
    if upgrade_plan is not None and not isinstance(upgrade_plan, dict):
        raise ReleaseVerificationError("API bootstrap upgrade_plan must be an object.")
    if isinstance(upgrade_plan, dict) and upgrade_plan:
        target = _first_text(
            upgrade_plan,
            "latest_version",
            "target_version",
            "version",
            "latest",
        )
        if target and target != expected_version:
            raise ReleaseVerificationError(
                f"API bootstrap version mismatch: expected {expected_version}, found {target}."
            )
    return {
        "health_keys": sorted(str(key) for key in health),
        "bootstrap_keys": sorted(str(key) for key in bootstrap),
        "upgrade_plan_present": bool(upgrade_plan),
    }


def _verify_artifact(
    descriptor: ReleaseDescriptor,
    *,
    timeout: float,
    maximum_bytes: int,
) -> dict[str, Any]:
    if descriptor.size > maximum_bytes:
        raise ReleaseVerificationError(
            f"Published installer exceeds the verifier limit: {descriptor.size} > {maximum_bytes}."
        )
    digest = hashlib.sha256()
    total = 0
    with _request(
        descriptor.download_url,
        timeout=timeout,
        accept="application/octet-stream,application/x-msdownload",
    ) as response:
        final_url = response.geturl()
        if _origin(final_url) != _origin(descriptor.download_url):
            raise ReleaseVerificationError(
                f"Installer response changed origin: {descriptor.download_url} -> {final_url}"
            )
        _safe_package_url(
            descriptor.download_url,
            final_url,
            descriptor.package_name,
        )
        raw_length = response.headers.get("Content-Length")
        if raw_length:
            try:
                declared = int(raw_length)
            except ValueError as exc:
                raise ReleaseVerificationError(
                    f"Installer has invalid Content-Length: {raw_length}"
                ) from exc
            if declared != descriptor.size:
                raise ReleaseVerificationError(
                    f"Installer Content-Length mismatch: expected {descriptor.size}, found {declared}."
                )
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_bytes:
                raise ReleaseVerificationError(
                    f"Installer download exceeded {maximum_bytes} bytes."
                )
            digest.update(chunk)
    actual_sha = digest.hexdigest()
    if total != descriptor.size:
        raise ReleaseVerificationError(
            f"Installer size mismatch: expected {descriptor.size}, downloaded {total}."
        )
    if actual_sha != descriptor.sha256:
        raise ReleaseVerificationError(
            f"Installer SHA-256 mismatch: expected {descriptor.sha256}, found {actual_sha}."
        )
    return {"downloaded": True, "size": total, "sha256": actual_sha}


def verify_deployed_release(
    *,
    base_url: str,
    api_base_url: str,
    expected_version: str,
    timeout: float = 30.0,
    metadata_only: bool = False,
    skip_api: bool = False,
    skip_homepage: bool = False,
    maximum_artifact_bytes: int = _DEFAULT_ARTIFACT_LIMIT_BYTES,
) -> VerificationReport:
    base = _normalize_base_url(base_url, label="base_url")
    api = _normalize_base_url(api_base_url, label="api_base_url")
    version = str(expected_version or "").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ReleaseVerificationError(f"Invalid expected version: {version!r}")
    if timeout <= 0 or timeout > 600:
        raise ReleaseVerificationError("timeout must be between 0 and 600 seconds.")
    if maximum_artifact_bytes <= 0:
        raise ReleaseVerificationError("maximum_artifact_bytes must be positive.")

    report = VerificationReport(
        status="running",
        expected_version=version,
        base_url=base,
        api_base_url=api,
        metadata_only=bool(metadata_only),
        homepage_checked=not skip_homepage,
        api_checked=not skip_api,
    )
    descriptors: list[ReleaseDescriptor] = []
    for name in ("latest.json", "manifest.json", "upgrade-plan.json"):
        url = _join(base, f"/updates/{name}")
        payload = _fetch_json(url, timeout=timeout)
        descriptors.append(
            _descriptor(
                payload,
                source=name,
                expected_version=version,
                base_url=base,
            )
        )
    canonical = _assert_descriptors_match(descriptors)
    report.descriptors = [asdict(item) for item in descriptors]

    if not skip_homepage:
        report.api["homepage"] = _verify_homepage(
            base_url=base, descriptor=canonical, timeout=timeout
        )
    if not skip_api:
        report.api["server"] = _verify_api(
            api_base_url=api, expected_version=version, timeout=timeout
        )
    if metadata_only:
        report.artifact = {"downloaded": False, "reason": "metadata_only"}
    else:
        report.artifact = _verify_artifact(
            canonical,
            timeout=timeout,
            maximum_bytes=maximum_artifact_bytes,
        )
    report.status = "ok"
    return report


def _read_release_defaults() -> tuple[str, str, str]:
    payload = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    return (
        str(payload.get("updates_base_url") or "https://herfy.online"),
        str(payload.get("server_base_url") or "https://herfy.online/api"),
        str(payload.get("app_version") or payload.get("version") or ""),
    )


def _write_report(path: str | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path:
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    default_base, default_api, default_version = _read_release_defaults()
    parser = argparse.ArgumentParser(
        description="Verify the deployed Herfy Windows release metadata and installer."
    )
    parser.add_argument("--base-url", default=default_base)
    parser.add_argument("--api-base-url", default=default_api)
    parser.add_argument("--expected-version", default=default_version)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--skip-homepage", action="store_true")
    parser.add_argument(
        "--maximum-artifact-bytes",
        type=int,
        default=_DEFAULT_ARTIFACT_LIMIT_BYTES,
    )
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    try:
        report = verify_deployed_release(
            base_url=args.base_url,
            api_base_url=args.api_base_url,
            expected_version=args.expected_version,
            timeout=args.timeout,
            metadata_only=args.metadata_only,
            skip_api=args.skip_api,
            skip_homepage=args.skip_homepage,
            maximum_artifact_bytes=args.maximum_artifact_bytes,
        )
        payload = asdict(report)
        _write_report(args.output, payload)
        print(
            "HERFY_DEPLOYED_RELEASE_OK "
            f"version={report.expected_version} artifact_downloaded={not report.metadata_only}"
        )
        return 0
    except (ReleaseVerificationError, OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {
            "status": "failed",
            "expected_version": str(args.expected_version),
            "base_url": str(args.base_url),
            "api_base_url": str(args.api_base_url),
            "error": str(exc),
        }
        _write_report(args.output, payload)
        print(f"HERFY_DEPLOYED_RELEASE_FAILED error={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
