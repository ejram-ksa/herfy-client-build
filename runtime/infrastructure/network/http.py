from __future__ import annotations
from runtime.shared.errors import RemoteRequestError, SessionExpiredError
from contextlib import suppress
import json
import logging
import random
import threading
import time
import uuid
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
import requests
from requests.adapters import HTTPAdapter
from runtime.shared.settings.config import DEFAULT_SERVER_BASE_URL, get_http_timeout_seconds, get_request_verify_ssl, normalize_api_base_url
from runtime.shared.settings.config import get_server_base_url as resolve_configured_server_base_url
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.settings.messages import canonical_error_message
logger = logging.getLogger(__name__)
_thread_local = threading.local()
_IDEMPOTENT_METHODS = {'GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE'}
_MUTATION_METHODS = {'POST', 'PATCH', 'PUT', 'DELETE'}
_SESSION_POOL_SIZE = 8
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_REDIRECT_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}
_SENSITIVE_REDIRECT_HEADERS = {'authorization', 'cookie', 'proxy-authorization'}

def redact_url_for_log(url: str) -> str:
    """Return a URL safe for logs by removing credentials, query, and fragment."""
    try:
        parsed = urlsplit(str(url or ''))
    except ValueError:
        return '<invalid-url>'
    hostname = parsed.hostname or ''
    if not hostname:
        return parsed.path or '<relative-url>'
    host = f'[{hostname}]' if ':' in hostname and (not hostname.startswith('[')) else hostname
    try:
        port = parsed.port
    except ValueError:
        return '<invalid-url>'
    if port is not None:
        host = f'{host}:{port}'
    return urlunsplit((parsed.scheme.lower(), host, parsed.path or '/', '', ''))

def _url_origin(url: str) -> tuple[str, str, int | None]:
    try:
        parsed = urlsplit(str(url or ''))
        port = parsed.port
    except ValueError as exc:
        raise RemoteRequestError('Invalid HTTP URL was rejected') from exc
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or '').lower()
    if port is None:
        port = 443 if scheme == 'https' else 80 if scheme == 'http' else None
    return (scheme, hostname, port)

def _validated_redirect_target(source_url: str, location: str) -> str:
    target = urljoin(source_url, str(location or '').strip())
    parsed = urlsplit(target)
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname:
        raise RemoteRequestError('Unsafe HTTP redirect target was rejected')
    if parsed.username is not None or parsed.password is not None:
        raise RemoteRequestError('Credential-bearing HTTP redirect was rejected')
    source_scheme = urlsplit(source_url).scheme.lower()
    if source_scheme == 'https' and parsed.scheme.lower() != 'https':
        raise RemoteRequestError('HTTPS downgrade redirect was rejected')
    return target

def _redirect_kwargs(source_url: str, target_url: str, request_kwargs: dict[str, Any]) -> dict[str, Any]:
    redirected = dict(request_kwargs)
    redirected.pop('params', None)
    if _url_origin(source_url) == _url_origin(target_url):
        return redirected
    headers = dict(redirected.get('headers') or {})
    redirected['headers'] = {key: value for key, value in headers.items() if str(key).strip().lower() not in _SENSITIVE_REDIRECT_HEADERS}
    redirected.pop('auth', None)
    redirected.pop('cookies', None)
    return redirected

def create_configured_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=_SESSION_POOL_SIZE, pool_maxsize=_SESSION_POOL_SIZE, max_retries=0, pool_block=True)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def _thread_session() -> requests.Session:
    session = getattr(_thread_local, 'session', None)
    if session is None:
        session = create_configured_session()
        _thread_local.session = session
    return session

def close_thread_session() -> None:
    session = getattr(_thread_local, 'session', None)
    if session is None:
        return
    try:
        session.close()
    except requests.RequestException:
        logger.debug('HTTP thread-session close skipped', exc_info=True)
    finally:
        with suppress(AttributeError):
            delattr(_thread_local, 'session')

def _default_retries_for(method: str) -> int:
    return 2 if str(method or 'GET').upper() in _IDEMPOTENT_METHODS else 0

def _backoff_wait(seconds: float) -> None:
    base = max(0.0, float(seconds or 0.0))
    jitter = random.uniform(0.0, min(0.35, base * 0.25)) if base else 0.0
    threading.Event().wait(base + jitter)

def _retry_after_seconds(response: requests.Response, fallback: float) -> float:
    raw = str(response.headers.get('Retry-After') or '').strip()
    if raw.isdigit():
        return min(30.0, max(0.0, float(raw)))
    return max(0.0, float(fallback))

def _headers_with_idempotency(method: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    request_kwargs = dict(kwargs)
    if str(method or '').upper() not in _MUTATION_METHODS:
        return request_kwargs
    headers = dict(request_kwargs.get('headers') or {})
    if 'Idempotency-Key' not in headers:
        headers['Idempotency-Key'] = str(uuid.uuid4())
    request_kwargs['headers'] = headers
    return request_kwargs

def _normalize_base(url: str) -> str:
    return normalize_api_base_url(url, default=DEFAULT_SERVER_BASE_URL)

def get_server_base_url(default: str=DEFAULT_SERVER_BASE_URL) -> str:
    configured = str(resolve_configured_server_base_url() or '').strip()
    if configured:
        return configured
    return _normalize_base(default)

def current_http_timeout() -> tuple[float, float]:
    """Return separate connect/read timeouts for variable-quality links."""
    read_timeout = max(1.0, float(get_http_timeout_seconds()))
    connect_timeout = min(5.0, read_timeout)
    return (connect_timeout, read_timeout)

def current_requests_verify() -> bool:
    return bool(get_request_verify_ssl())

def _detail_message(value: Any) -> str:
    if isinstance(value, list):
        messages: list[str] = []
        for item in value:
            if isinstance(item, dict):
                loc = item.get('loc')
                loc_text = '.'.join((str(x) for x in loc)) if isinstance(loc, list | tuple) else str(loc or '')
                msg = str(item.get('msg') or item.get('message') or '').strip()
                if loc_text and msg:
                    messages.append(f'{loc_text}: {msg}')
                elif msg:
                    messages.append(msg)
            else:
                text = str(item or '').strip()
                if text:
                    messages.append(text)
        return '; '.join(messages)
    if isinstance(value, dict):
        return str(value.get('detail') or value.get('message') or value.get('msg') or '').strip()
    return str(value or '').strip()

def _detail_from_response(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            return _detail_message(data.get('detail') or data.get('message') or data)
        return _detail_message(data)
    except SERVICE_OPERATION_EXCEPTIONS:
        logger.debug('_detail_from_response fallback failed', exc_info=True)
    return str(response.text or '').strip()

def _http_error_message(status_code: int, detail: str, url: str) -> str:
    clean_detail = str(detail or '').strip()
    lower_detail = clean_detail.lower()
    request_path = urlsplit(str(url or '')).path.lower()
    if '<html' in lower_detail or '<body' in lower_detail:
        clean_detail = ''
    if status_code == 404 and '/updates/packages/' in request_path:
        return 'The update package is missing on the update server. Upload the remote update package again and verify the package URL.'
    if status_code == 404:
        return 'The requested server resource was not found.'
    if status_code == 403:
        return clean_detail or canonical_error_message('permission_denied')
    return clean_detail or f'Server error (HTTP {status_code})'

def _close_response(response: requests.Response | None, *, context: str) -> None:
    if response is None:
        return
    try:
        response.close()
    except requests.RequestException:
        logger.debug('HTTP response close skipped: %s', context, exc_info=True)

def request_with_retry(method: str, url: str, *, session: requests.Session | None=None, timeout: float | tuple[float, float] | None=None, verify: bool | None=None, max_retries: int | None=None, optional_statuses: set[int] | tuple[int, ...] | list[int] | None=None, **kwargs: Any) -> requests.Response:
    method = str(method or 'GET').upper()
    optional_statuses = {int(code) for code in optional_statuses or []}
    if timeout is None:
        timeout = current_http_timeout()
    elif isinstance(timeout, tuple):
        timeout = (float(timeout[0]), float(timeout[1]))
    else:
        timeout = float(timeout)
    verify = current_requests_verify() if verify is None else bool(verify)
    max_retries = _default_retries_for(method) if max_retries is None else int(max_retries)
    request_kwargs = _headers_with_idempotency(method, kwargs)
    owns_thread_session = session is None
    sender = session.request if session is not None else _thread_session().request
    delays = [0.7, 1.5, 2.5]
    last_exc: Exception | None = None
    safe_url = redact_url_for_log(url)
    logger.debug('HTTP request started: method=%s url=%s', method, safe_url)
    for attempt in range(max_retries + 1):
        attempt_started = time.monotonic()
        try:
            response = sender(method, url, timeout=timeout, verify=verify, allow_redirects=False, **request_kwargs)
            if response.status_code in _REDIRECT_STATUS_CODES:
                status_code = response.status_code
                location = str(response.headers.get('location') or '').strip()
                _close_response(response, context='redirect')
                if method not in _REDIRECT_SAFE_METHODS:
                    raise RemoteRequestError(f'HTTP redirect rejected for non-read request ({status_code})', status_code=status_code)
                if not location:
                    raise RemoteRequestError(f'HTTP redirect did not include a destination ({status_code})', status_code=status_code)
                target_url = _validated_redirect_target(url, location)
                retry_kwargs = _redirect_kwargs(url, target_url, request_kwargs)
                logger.info('HTTP Redirect: %s -> %s', status_code, redact_url_for_log(target_url))
                response = sender(method, target_url, timeout=timeout, verify=verify, allow_redirects=False, **retry_kwargs)
                if response.status_code in _REDIRECT_STATUS_CODES:
                    second_status = response.status_code
                    _close_response(response, context='redirect chain')
                    raise RemoteRequestError('Multiple HTTP redirects were rejected', status_code=second_status)
            duration_ms = int((time.monotonic() - attempt_started) * 1000)
            log_method = logger.warning if duration_ms >= 3000 else logger.debug
            log_method(
                'HTTP request completed: method=%s status=%s duration_ms=%s url=%s',
                method, response.status_code, duration_ms, safe_url,
            )
        except requests.Timeout as exc:
            last_exc = exc
            logger.warning('Request timeout (attempt %s/%s; error=%s)', attempt + 1, max_retries + 1, type(exc).__name__)
            if attempt >= max_retries:
                if owns_thread_session:
                    close_thread_session()
                raise RemoteRequestError(canonical_error_message('server_timeout')) from exc
            if owns_thread_session:
                close_thread_session()
                sender = _thread_session().request
            _backoff_wait(delays[min(attempt, len(delays) - 1)])
            continue
        except requests.ConnectionError as exc:
            last_exc = exc
            logger.warning('Connection error (attempt %s/%s; error=%s)', attempt + 1, max_retries + 1, type(exc).__name__)
            if attempt >= max_retries:
                if owns_thread_session:
                    close_thread_session()
                raise RemoteRequestError(canonical_error_message('connection_failed')) from exc
            if owns_thread_session:
                close_thread_session()
                sender = _thread_session().request
            _backoff_wait(delays[min(attempt, len(delays) - 1)])
            continue
        except requests.RequestException as exc:
            if owns_thread_session:
                close_thread_session()
            logger.error('Request failed: %s', type(exc).__name__)
            raise RemoteRequestError(canonical_error_message('operation_failed')) from exc
        if response.status_code == 401:
            detail = _detail_from_response(response)
            _close_response(response, context='401')
            request_path = urlsplit(url).path.rstrip('/')
            is_login_request = request_path.endswith('/auth/login')
            if is_login_request:
                logger.warning('Authentication rejected - 401 received on login')
                raise RemoteRequestError(canonical_error_message('invalid_credentials'), status_code=401)
            logger.warning('Session expired - 401 received')
            raise SessionExpiredError(canonical_error_message('session_expired'), status_code=401)
        if response.status_code in (429, 502, 503, 504):
            logger.warning('Server error %s (attempt %s/%s)', response.status_code, attempt + 1, max_retries + 1)
            if attempt >= max_retries:
                status_code = response.status_code
                _close_response(response, context='final server error')
                raise RemoteRequestError(canonical_error_message('server_unavailable'), status_code=status_code)
            retry_delay = _retry_after_seconds(response, delays[min(attempt, len(delays) - 1)])
            _close_response(response, context='retryable server error')
            _backoff_wait(retry_delay)
            continue
        if response.status_code >= 400:
            status_code = response.status_code
            detail = _detail_from_response(response)
            _close_response(response, context=f'HTTP {status_code}')
            if status_code in optional_statuses:
                logger.info('Optional HTTP endpoint unavailable: %s', status_code)
            else:
                logger.error('HTTP request failed with status=%s', status_code)
            raise RemoteRequestError(_http_error_message(status_code, detail, url), status_code=status_code)
        return response
    if last_exc is not None:
        raise RemoteRequestError(canonical_error_message('operation_failed')) from last_exc
    raise RemoteRequestError('Request failed after all retries')

def fetch_json_dict(url: str, **kwargs) -> dict[str, Any]:
    response = request_with_retry('GET', str(url), **kwargs)
    try:
        try:
            data = response.json()
        except SERVICE_OPERATION_EXCEPTIONS:
            data = {}
        return data if isinstance(data, dict) else {}
    finally:
        response.close()

def resolve_api_url(path_or_url: str, base_url: str | None=None) -> str:
    value = str(path_or_url or '').strip()
    root = str(base_url or get_server_base_url()).rstrip('/')
    if not value:
        return root
    if value.startswith(('http://', 'https://')):
        return value
    if not value.startswith('/'):
        value = '/' + value
    if root.endswith('/api') and value.startswith('/api/'):
        value = value[4:]
    elif not root.endswith('/api') and (not value.startswith('/api/')):
        value = '/api' + value
    return f'{root}{value}'

def api_request(method: str, path_or_url: str, *, base_url: str | None=None, **kwargs: Any) -> requests.Response:
    return request_with_retry(method, resolve_api_url(path_or_url, base_url=base_url), **kwargs)

def api_fetch_json(path_or_url: str, *, base_url: str | None=None, **kwargs: Any) -> dict[str, Any]:
    response = api_request('GET', path_or_url, base_url=base_url, **kwargs)
    try:
        try:
            data = response.json()
        except SERVICE_OPERATION_EXCEPTIONS:
            data = {}
        return data if isinstance(data, dict) else {}
    finally:
        response.close()

def api_get_json(path_or_url: str, *, base_url: str | None=None, **kwargs: Any) -> dict[str, Any]:
    return api_fetch_json(path_or_url, base_url=base_url, **kwargs)

def _api_payload_json(method: str, path_or_url: str, payload: dict[str, Any], *, base_url: str | None=None, **kwargs: Any) -> dict[str, Any]:
    response = api_request(method, path_or_url, base_url=base_url, json=payload, **kwargs)
    try:
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise RemoteRequestError(canonical_error_message('malformed_response')) from exc
        except (TypeError, ValueError) as exc:
            raise RemoteRequestError(canonical_error_message('invalid_response')) from exc
        return data if isinstance(data, dict) else {}
    finally:
        response.close()

def api_post_json(path_or_url: str, payload: dict[str, Any], *, base_url: str | None=None, **kwargs: Any) -> dict[str, Any]:
    return _api_payload_json('POST', path_or_url, payload, base_url=base_url, **kwargs)

def api_download_bytes(path_or_url: str, *, base_url: str | None=None, **kwargs: Any) -> bytes:
    response = api_request('GET', path_or_url, base_url=base_url, **kwargs)
    try:
        return bytes(response.content or b'')
    finally:
        response.close()

def api_put_json(path_or_url: str, payload: dict[str, Any], *, base_url: str | None=None, **kwargs: Any) -> dict[str, Any]:
    return _api_payload_json('PUT', path_or_url, payload, base_url=base_url, **kwargs)
