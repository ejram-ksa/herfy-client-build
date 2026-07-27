from __future__ import annotations
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from runtime.shared.booleans import parse_bool
from runtime.shared.objects import first_value, normalize_int, safe_get
from runtime.shared.strings import normalize_text
from runtime.domain.versions import should_update

@dataclass(frozen=True)
class VersionPayload:
    latest: str
    url: str
    notes: str
    mandatory: bool
    sha256: str = ''
    size: int = 0

def normalize_version_payload(data: Any, base_url: str) -> VersionPayload:
    payload = data if isinstance(data, dict) else {}
    latest = normalize_text(safe_get(payload, 'latest') or safe_get(payload, 'version'))
    url = normalize_text(safe_get(payload, 'url') or safe_get(payload, 'download_url') or f"{base_url.rstrip('/')}/meta/download/{latest}" if latest else '')
    return VersionPayload(latest=latest, url=url, notes=normalize_text(safe_get(payload, 'notes') or safe_get(payload, 'release_notes')), mandatory=parse_bool(safe_get(payload, 'mandatory'), False), sha256=normalize_text(safe_get(payload, 'sha256') or safe_get(payload, 'checksum')).lower(), size=normalize_int(safe_get(payload, 'size_bytes') or safe_get(payload, 'size')))
_LOCAL_UPDATE_HOSTS = {'localhost', '127.0.0.1', '::1'}
_LOCAL_UPDATE_PREFIXES = ('127.', '10.', '192.168.', *(f'172.{index}.' for index in range(16, 32)))
_DEFAULT_ALLOWED_UPDATE_HOSTS = {'herfy.online', 'updates.herfy.online'}
_SAFE_FILENAME_PATTERN = re.compile('[^\\w.\\- ]+', re.UNICODE)

def _hostname(value: str) -> str:
    return str(urlsplit(str(value or '')).hostname or '').strip().lower()

def _is_local_update_host(hostname: str) -> bool:
    host = str(hostname or '').strip().lower()
    return host in _LOCAL_UPDATE_HOSTS or host.startswith(_LOCAL_UPDATE_PREFIXES)

def _configured_update_hosts() -> set[str]:
    hosts: set[str] = set()
    extra = os.getenv('PTS_UPDATE_ALLOWED_HOSTS', '')
    for item in str(extra or '').split(','):
        host = item.strip().lower()
        if host:
            hosts.add(host)
    return hosts

def _allowed_update_hosts(base_url: str) -> set[str]:
    hosts = set(_DEFAULT_ALLOWED_UPDATE_HOSTS)
    base_host = _hostname(base_url)
    if base_host:
        hosts.add(base_host)
    hosts.update(_configured_update_hosts())
    return hosts

def _is_allowed_download_url(url: str, base_url: str) -> bool:
    parts = urlsplit(str(url or ''))
    scheme = str(parts.scheme or '').lower()
    host = str(parts.hostname or '').lower()
    if scheme not in {'http', 'https'} or not host:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    try:
        _ = parts.port
    except ValueError:
        return False
    if _is_local_update_host(host):
        base_host = _hostname(base_url)
        return _is_local_update_host(base_host) or host in _configured_update_hosts()
    if scheme != 'https':
        return False
    return host in _allowed_update_hosts(base_url)

def resolve_download_url(value: Any, base_url: str) -> str:
    text = str(value or '').replace('\\', '/').strip()
    if not text or text.startswith('//'):
        return ''
    normalized_base = str(base_url or '').strip().rstrip('/')
    if text.lower().startswith(('http://', 'https://')):
        candidate = text
    else:
        if not normalized_base:
            return ''
        base_parts = urlsplit(normalized_base)
        base_path = str(base_parts.path or '').rstrip('/')
        is_api_base = base_path == '/api' or base_path.startswith('/api/')
        already_prefixed = bool(base_path and (text == base_path or text.startswith(f'{base_path}/')))
        if is_api_base and text.startswith('/') and (not already_prefixed):
            candidate = urljoin(f'{normalized_base}/', text.lstrip('/'))
        else:
            candidate = urljoin(f'{normalized_base}/', text)
    parts = urlsplit(candidate)
    normalized = urlunsplit((str(parts.scheme or '').lower(), parts.netloc, parts.path or '/', parts.query, ''))
    return normalized if _is_allowed_download_url(normalized, normalized_base) else ''

def safe_update_filename(value: Any, fallback: str, *, allowed_suffixes: tuple[str, ...]=()) -> str:
    fallback_raw = str(fallback or 'update.bin').replace('\\', '/')
    fallback_name = Path(fallback_raw).name.strip()
    fallback_name = _SAFE_FILENAME_PATTERN.sub('_', fallback_name)
    fallback_name = re.sub('_+', '_', fallback_name).strip(' ._') or 'update.bin'
    raw = unquote(str(value or '')).replace('\\', '/').replace('\x00', '').strip()
    raw = raw.strip('"\'').split('?', 1)[0].split('#', 1)[0]
    name = Path(raw).name.strip() if raw else fallback_name
    name = _SAFE_FILENAME_PATTERN.sub('_', name)
    name = re.sub('_+', '_', name).strip(' ._')
    if not name or name in {'.', '..'}:
        name = fallback_name
    allowed = tuple((s.lower() for s in allowed_suffixes if s))
    if allowed:
        suffix = Path(name).suffix.lower()
        fallback_suffix = Path(fallback_name).suffix.lower()
        if not suffix and fallback_suffix in allowed:
            name = f'{name}{fallback_suffix}'
            suffix = fallback_suffix
        if suffix not in allowed:
            return fallback_name
    return name or fallback_name

def _notes_from_value(value: Any) -> str:
    if isinstance(value, dict):
        items = value.get('items')
        if isinstance(items, list):
            joined = '\n'.join((str(item).strip() for item in items if str(item).strip()))
            if joined:
                return joined
        return str(value.get('title') or value.get('message') or value.get('detail') or '')
    if isinstance(value, list):
        return '\n'.join((str(item).strip() for item in value if str(item).strip()))
    return str(value or '')

def _first_package(data: dict[str, Any]) -> dict[str, Any]:
    packages = data.get('packages')
    if isinstance(packages, list):
        for entry in packages:
            if isinstance(entry, dict):
                return dict(entry)
    return {}

@dataclass(frozen=True)
class ParsedUpdateDescriptor:
    available: bool
    target_version: str
    download_url: str
    package_name: str = ''
    notes: str = ''
    mandatory: bool = False
    skipped: bool = False
    sha256: str = ''
    size: int = 0
    current_supported: bool = True
    reason: str = 'up_to_date'
    popup_title: str = 'New update available'
    popup_message: str = ''

def parse_update_payload(payload: dict[str, Any] | None, *, current_version: str, base_url: str, skipped_version: str='') -> ParsedUpdateDescriptor:
    data = dict(payload or {})
    if isinstance(data.get('patches'), list):
        patch_descriptor = parse_manifest_patch_payload(data, current_version=current_version, base_url=base_url)
        if patch_descriptor.available:
            skipped = bool(skipped_version and skipped_version == patch_descriptor.target_version and (not patch_descriptor.mandatory))
            if skipped:
                return ParsedUpdateDescriptor(available=False, target_version=patch_descriptor.target_version, download_url=patch_descriptor.download_url, package_name=patch_descriptor.package_name, notes=patch_descriptor.notes, mandatory=patch_descriptor.mandatory, skipped=True, sha256=patch_descriptor.sha256, size=patch_descriptor.size, current_supported=patch_descriptor.current_supported, reason='skipped', popup_title=patch_descriptor.popup_title, popup_message=patch_descriptor.popup_message)
            return patch_descriptor
    nested = data.get('update') if isinstance(data.get('update'), dict) else {}
    primary = _first_package(data)
    target_version = str(first_value(nested, 'latest_version', 'version', 'latest', 'target_version') or first_value(data, 'latest_version', 'target_version', 'version', 'latest') or current_version).strip()
    raw_package_name = str(first_value(primary, 'filename', 'package', 'name') or first_value(data, 'package_name', 'package', 'filename')).strip()
    package_name = safe_update_filename(raw_package_name, raw_package_name) if raw_package_name else ''
    download_url = resolve_download_url(first_value(nested, 'installer_url', 'download_url', 'url') or first_value(primary, 'download_url', 'installer_url', 'url') or first_value(data, 'installer_url', 'download_url', 'url'), base_url)
    if not download_url and package_name:
        download_url = resolve_download_url(f'/updates/packages/{package_name}', base_url)
    notes = _notes_from_value(first_value(nested, 'notes', 'release_notes') or first_value(data, 'notes', 'release_notes', 'reason') or first_value(primary, 'notes', 'release_notes')).strip()
    mandatory = any((parse_bool(nested.get('mandatory'), False), parse_bool(primary.get('mandatory'), False), parse_bool(data.get('mandatory'), False), parse_bool(data.get('force_update'), False)))
    sha256 = str(first_value(nested, 'sha256', 'checksum') or first_value(primary, 'sha256', 'checksum') or first_value(data, 'sha256', 'checksum')).strip().lower()
    size = normalize_int(first_value(nested, 'size_bytes', 'size') or first_value(primary, 'size_bytes', 'size') or first_value(data, 'size_bytes', 'size'))
    available_flag = data.get('update_available')
    if available_flag is None:
        available_flag = data.get('requires_update')
    flag_allows_update = True if available_flag is None else parse_bool(available_flag, False)
    remote_is_newer = should_update(current_version, target_version)
    available = bool(flag_allows_update and remote_is_newer and download_url)
    skipped = bool(skipped_version and skipped_version == target_version and (not mandatory))
    if skipped:
        available = False
    reason = str(data.get('reason') or nested.get('reason') or 'up_to_date')
    popup_title = 'Mandatory update required' if mandatory else 'New update available'
    popup_message = notes or (f'Version {target_version} is available.' if target_version else '')
    return ParsedUpdateDescriptor(available=available, target_version=target_version, download_url=download_url, package_name=package_name, notes=notes, mandatory=mandatory, skipped=skipped, sha256=sha256, size=size, current_supported=parse_bool(data.get('current_supported'), True), reason=reason, popup_title=popup_title, popup_message=popup_message)

def _patch_applies_to_current(raw_patch: dict[str, Any], current_version: str) -> bool:
    current = str(current_version or '').strip()
    if not current:
        return False
    min_from = str(raw_patch.get('min_from_version') or '').strip()
    max_from = str(raw_patch.get('max_from_version') or '').strip()
    if min_from and should_update(current, min_from):
        return False
    if max_from and should_update(max_from, current):
        return False
    from_version = str(raw_patch.get('from_version') or '').strip()
    if from_version in {'*', 'any', 'all'}:
        return True
    if from_version and from_version == current:
        return True
    from_versions = raw_patch.get('from_versions')
    if isinstance(from_versions, list | tuple | set):
        normalized = {str(item or '').strip() for item in from_versions}
        if current in normalized or '*' in normalized:
            return True
    return bool(min_from or max_from)

def parse_manifest_patch_payload(payload: dict[str, Any] | None, *, current_version: str, base_url: str) -> ParsedUpdateDescriptor:
    data = dict(payload or {})
    latest_version = str(data.get('latest_version') or data.get('version') or current_version)
    mandatory = parse_bool(data.get('mandatory'), False)
    notes = str(data.get('notes') or '')
    popup_title = str(data.get('popup_title') or 'New update available')
    popup_message = str(data.get('popup_message') or notes or f'Version {latest_version} is available.')
    patches = data.get('patches')
    if isinstance(patches, list):
        for raw_patch in patches:
            if not isinstance(raw_patch, dict):
                continue
            if not _patch_applies_to_current(raw_patch, current_version):
                continue
            raw_package_name = str(raw_patch.get('package') or raw_patch.get('filename') or '').strip()
            package_name = safe_update_filename(raw_package_name, raw_package_name) if raw_package_name else ''
            download_url = resolve_download_url(raw_patch.get('download_url') or '', base_url)
            if not download_url and package_name:
                download_url = resolve_download_url(f'/updates/packages/{package_name}', base_url)
            patch_notes = str(raw_patch.get('notes') or notes)
            patch_title = str(raw_patch.get('popup_title') or popup_title)
            patch_message = str(raw_patch.get('popup_message') or popup_message or patch_notes)
            target_version = str(raw_patch.get('to_version') or latest_version).strip()
            remote_is_newer = should_update(current_version, target_version)
            if not remote_is_newer:
                continue
            return ParsedUpdateDescriptor(available=bool(remote_is_newer and (package_name or download_url)), target_version=target_version, download_url=download_url, package_name=package_name, notes=patch_notes, mandatory=parse_bool(raw_patch.get('mandatory'), mandatory), sha256=str(raw_patch.get('sha256') or '').strip().lower(), size=normalize_int(raw_patch.get('size') or raw_patch.get('size_bytes') or 0), current_supported=parse_bool(raw_patch.get('current_supported'), parse_bool(data.get('current_supported'), True)), reason=str(raw_patch.get('reason') or data.get('reason') or 'update_available'), popup_title=patch_title, popup_message=patch_message)
    return ParsedUpdateDescriptor(available=False, target_version=latest_version, download_url='', notes=notes, mandatory=mandatory, current_supported=parse_bool(data.get('current_supported'), True), reason=str(data.get('reason') or 'up_to_date'), popup_title=popup_title, popup_message=popup_message)
