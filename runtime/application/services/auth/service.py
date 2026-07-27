from __future__ import annotations
import logging
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any
from runtime.shared.booleans import parse_bool
logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class LoginRemoteNotice:
    message: str
    severity: str

class LoginRemoteNoticeService:

    @staticmethod
    def evaluate(settings: Mapping[str, Any] | None) -> LoginRemoteNotice:
        data = dict(settings or {})
        maintenance_enabled = parse_bool(data.get('remote_maintenance_enabled'), False)
        maintenance_message = str(data.get('remote_maintenance_message', '') or '').strip()
        login_message = str(data.get('remote_login_message', '') or '').strip()
        banner_message = str(data.get('remote_startup_banner', '') or '').strip()
        banner_severity = str(data.get('remote_startup_banner_severity', 'info') or 'info').strip() or 'info'
        if maintenance_enabled and maintenance_message:
            return LoginRemoteNotice(message=maintenance_message, severity='warning')
        if login_message:
            return LoginRemoteNotice(message=login_message, severity='info')
        if banner_message:
            return LoginRemoteNotice(message=banner_message, severity=banner_severity)
        return LoginRemoteNotice(message='', severity='neutral')
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.settings.messages import canonical_error_message
from runtime.domain.user import AuthSession
from runtime.domain.access import PermissionContext

class AuthError(RuntimeError):
    """Authentication failure with restore-safe lifecycle metadata."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool | None = None,
        clear_remembered_session: bool = False,
        reason: str = "auth_failed",
    ) -> None:
        super().__init__(str(message or ""))
        self.status_code = status_code
        self.retryable = retryable
        self.clear_remembered_session = bool(clear_remembered_session)
        self.reason = str(reason or "auth_failed")

def _flatten_auth_payload(data: dict[str, Any], *, fallback_identifier: str='') -> dict[str, Any]:
    payload = dict(data or {})
    nested_user = payload.get('user') if isinstance(payload.get('user'), dict) else {}
    merged = {**nested_user, **payload}
    for key in ('access_token', 'token', 'token_type', 'refresh_token', 'expires_in'):
        if key in payload:
            merged[key] = payload[key]
    if fallback_identifier and (not merged.get('username')):
        merged['username'] = str(fallback_identifier).strip()
    return merged

def _unwrap_auth_response(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data or {})
    for key in ('data', 'result', 'session', 'auth'):
        nested = payload.get(key)
        if isinstance(nested, dict) and (nested.get('access_token') or nested.get('token') or nested.get('user') or nested.get('session')):
            merged = dict(nested)
            for token_key in ('access_token', 'token', 'token_type', 'refresh_token', 'expires_in'):
                if token_key in payload and token_key not in merged:
                    merged[token_key] = payload[token_key]
            return merged
    return payload

def _response_json(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
    except SERVICE_OPERATION_EXCEPTIONS as exc:
        raise AuthError(canonical_error_message('malformed_response'), retryable=True, reason='malformed_response') from exc
    return data if isinstance(data, dict) else {}

def _normalized_expires_in(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 3600
    if seconds <= 0:
        return 3600
    return min(seconds, 7 * 24 * 60 * 60)

def _normalize_login_identifier(identifier: str) -> str:
    """Normalize branch-style usernames without changing general identities."""

    value = str(identifier or '').strip()
    if len(value) > 1 and value[0] in {'h', 'H'} and value[1:].isdigit():
        return 'H' + value[1:]
    return value


def _canonical_login_request(identifier: str, password: str) -> dict[str, Any]:
    """Build the single server-supported login payload.

    The authoritative API accepts JSON with ``username`` and ``password``.
    Sending several alternative payloads can trigger account lockout counters
    and can turn one valid sign-in attempt into a misleading 403 response.
    """
    user = _normalize_login_identifier(identifier)
    secret = str(password or '')
    return {'json': {'username': user, 'password': secret}, 'headers': {'Accept': 'application/json', 'Content-Type': 'application/json', 'Cache-Control': 'no-store'}, 'max_retries': 0}

def _parse_auth_session(data: dict, identifier: str='') -> AuthSession:
    data = _unwrap_auth_response(dict(data or {}))
    token = str(data.get('access_token') or data.get('token') or '').strip()
    if not token:
        raise AuthError(canonical_error_message('invalid_response'), retryable=True, reason='invalid_response')
    hydrated = _flatten_auth_payload(dict(data or {}), fallback_identifier=identifier)
    permission_context = PermissionContext.from_payload(hydrated, active_branch=str(hydrated.get('active_branch') or '').strip())
    branches = list(permission_context.scope.branches or [])
    active_branch = str(permission_context.active_branch or (branches[0] if len(branches) == 1 else '')).strip()
    role = permission_context.role
    logger.info('Authentication authority accepted by server')
    return AuthSession(id_token=token, uid=str(identifier or hydrated.get('uid') or hydrated.get('username') or permission_context.user_id or permission_context.username or '').strip(), role=role, branches=branches, active_branch=active_branch, token_type=str(hydrated.get('token_type') or 'bearer'), refresh_token=str(hydrated.get('refresh_token') or ''), expires_in=_normalized_expires_in(hydrated.get('expires_in')), permission_context=permission_context)
from runtime.domain.user import UserProfile

@dataclass(frozen=True)
class SessionRestoreCandidate:
    refresh_token: str = ''
    username: str = ''
    user_id: str = ''

def build_restore_candidate(snapshot: Any | None) -> SessionRestoreCandidate | None:
    """Create a candidate only when the real server can re-authorize it.

    Stored access tokens, cached roles, branches, and permissions are never
    authentication authority. A remembered session requires a refresh token
    and must be accepted by the server before the application opens.
    """
    if snapshot is None or not bool(getattr(snapshot, 'remember', False)):
        return None
    refresh_token = str(getattr(snapshot, 'refresh_token', '') or '').strip()
    if not refresh_token:
        return None
    return SessionRestoreCandidate(refresh_token=refresh_token, username=str(getattr(snapshot, 'username', '') or '').strip(), user_id=str(getattr(snapshot, 'user_id', '') or '').strip())

def load_user_profile_from_session(session: AuthSession, fallback_username: str='') -> UserProfile:
    """Build a profile only from permission data returned by the server."""
    del fallback_username
    ctx = getattr(session, 'permission_context', None)
    if not isinstance(ctx, PermissionContext):
        raise AuthError(canonical_error_message('profile_missing'))
    if not (str(ctx.username or '').strip() or str(ctx.user_id or '').strip()):
        raise AuthError(canonical_error_message('profile_missing'))
    if str(getattr(ctx, 'authority_source', '') or '').strip() != 'postgresql.role_permissions':
        raise AuthError(canonical_error_message('profile_missing'))
    if not bool(getattr(ctx, 'is_active', True)):
        raise AuthError(canonical_error_message('account_inactive'), clear_remembered_session=True, reason='account_inactive')
    return UserProfile.from_permission_context(ctx)
import requests
from runtime.shared.settings.config import get_http_timeout_seconds, get_request_verify_ssl
from runtime.shared.settings.messages import user_error_message
from runtime.shared.errors import RemoteRequestError, SessionExpiredError
from runtime.application.ports import api_post_json, api_request
from runtime.infrastructure.network.http import create_configured_session
_LOGIN_ENDPOINTS = ('/auth/login', '/client/v1/auth/login')
_REFRESH_ENDPOINTS = ('/auth/refresh', '/client/v1/auth/refresh')
_LOGIN_ALIAS_RETRY_STATUS_CODES = {404, 405, 422}
_LOGIN_INACTIVE_MARKERS = ('inactive', 'disabled', 'deactivated', 'suspended', 'blocked')
_LOGIN_INVALID_CREDENTIAL_MARKERS = ('invalid username or password', 'incorrect username or password', 'bad credentials', 'invalid credentials')

def _login_rejection_message(error: BaseException) -> str:
    text = str(error or '').strip()
    lowered = text.lower()
    if any((marker in lowered for marker in _LOGIN_INVALID_CREDENTIAL_MARKERS)):
        return canonical_error_message('invalid_credentials')
    if any((marker in lowered for marker in _LOGIN_INACTIVE_MARKERS)):
        return canonical_error_message('account_inactive')
    return canonical_error_message('login_access_denied')

def _merge_authenticated_profile(auth_payload: dict[str, Any], profile_payload: dict[str, Any]) -> dict[str, Any]:
    """Merge /auth/me authority into the token response without losing tokens."""
    auth_data = _unwrap_auth_response(dict(auth_payload or {}))
    profile_data = _unwrap_auth_response(dict(profile_payload or {}))
    nested_user = profile_data.get('user') if isinstance(profile_data.get('user'), dict) else {}
    merged = dict(auth_data)
    merged.update(nested_user)
    merged.update(profile_data)
    for key in ('access_token', 'token', 'token_type', 'refresh_token', 'expires_in'):
        if auth_data.get(key) not in (None, ''):
            merged[key] = auth_data[key]
    return merged

def _contains_server_authority(payload: dict[str, Any]) -> bool:
    """Return True only for explicit identity and authorization from the API."""
    data = _unwrap_auth_response(dict(payload or {}))
    nested_user = data.get('user') if isinstance(data.get('user'), dict) else {}
    merged = {**nested_user, **data}
    identity = str(merged.get('user_id') or merged.get('uid') or merged.get('username') or merged.get('id') or '').strip()
    has_authorization = any((key in merged for key in ('role', 'permissions', 'scope', 'branches', 'branch_scope', 'assigned_branch_ids')))
    return bool(identity and has_authorization)

def _hydrate_authenticated_profile(auth_payload: dict[str, Any], *, session: requests.Session) -> dict[str, Any]:
    """Use authorization returned by the real server, never local JWT decoding."""
    if _contains_server_authority(auth_payload):
        logger.info('Authenticated authority supplied by login/refresh response')
        return auth_payload
    token = str(auth_payload.get('access_token') or auth_payload.get('token') or '').strip()
    if not token:
        raise AuthError(canonical_error_message('invalid_response'), retryable=True, reason='invalid_response')
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json', 'Cache-Control': 'no-store'}
    last_error: BaseException | None = None
    for endpoint in ('/auth/me', '/client/v1/auth/me'):
        try:
            response = api_request('GET', endpoint, session=session, timeout=get_http_timeout_seconds(), verify=get_request_verify_ssl(), headers=headers, max_retries=0)
            try:
                profile_payload = _response_json(response)
            finally:
                response.close()
            if not _contains_server_authority(profile_payload):
                raise AuthError(canonical_error_message('profile_missing'))
            logger.info('Authenticated profile hydrated endpoint=%s', endpoint)
            return _merge_authenticated_profile(auth_payload, profile_payload)
        except SessionExpiredError as exc:
            raise AuthError(canonical_error_message('invalid_credentials'), status_code=getattr(exc, 'status_code', 401), clear_remembered_session=True, reason='session_rejected') from exc
        except RemoteRequestError as exc:
            last_error = exc
            status_code = getattr(exc, 'status_code', None)
            if status_code in {403, 404, 405} and endpoint != '/client/v1/auth/me':
                logger.warning('Authenticated profile endpoint rejected endpoint=%s status=%s', endpoint, status_code)
                continue
            raise AuthError(user_error_message(exc, context='login'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_login_failure') from exc
        except AuthError:
            raise
        except SERVICE_OPERATION_EXCEPTIONS as exc:
            raise AuthError(user_error_message(exc, context='login'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_login_failure') from exc
    if last_error is not None:
        raise AuthError(user_error_message(last_error, context='login')) from last_error
    raise AuthError(canonical_error_message('profile_missing'))

def _post_login(identifier: str, password: str) -> dict[str, Any]:
    last_error: RemoteRequestError | None = None
    request_kwargs = _canonical_login_request(identifier, password)
    with create_configured_session() as session:
        for endpoint in _LOGIN_ENDPOINTS:
            try:
                response = api_request('POST', endpoint, session=session, timeout=get_http_timeout_seconds(), verify=get_request_verify_ssl(), **request_kwargs)
                try:
                    auth_payload = _unwrap_auth_response(_response_json(response))
                finally:
                    response.close()
                logger.info('Login accepted endpoint=%s mode=json-username', endpoint)
                return _hydrate_authenticated_profile(auth_payload, session=session)
            except SessionExpiredError as exc:
                raise AuthError(canonical_error_message('invalid_credentials'), status_code=getattr(exc, 'status_code', 401), clear_remembered_session=True, reason='session_rejected') from exc
            except RemoteRequestError as exc:
                status_code = getattr(exc, 'status_code', None)
                if status_code == 401:
                    logger.error('Login rejected by server status=401')
                    raise AuthError(canonical_error_message('invalid_credentials'), status_code=getattr(exc, 'status_code', 401), clear_remembered_session=True, reason='session_rejected') from exc
                if status_code == 403:
                    logger.error('Login access rejected by server status=403')
                    raise AuthError(_login_rejection_message(exc)) from exc
                if status_code in _LOGIN_ALIAS_RETRY_STATUS_CODES:
                    logger.warning('Login endpoint unavailable endpoint=%s status=%s', endpoint, status_code)
                    last_error = exc
                    continue
                raise AuthError(user_error_message(exc, context='login'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_login_failure') from exc
            except SERVICE_OPERATION_EXCEPTIONS as exc:
                raise AuthError(user_error_message(exc, context='login'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_login_failure') from exc
    if last_error is not None:
        raise AuthError(_login_rejection_message(last_error)) from last_error
    raise AuthError(canonical_error_message('connection_failed'))

def _post_refresh(refresh_token: str) -> dict[str, Any]:
    """Refresh the token and permissions against the production API."""
    secret = str(refresh_token or '').strip()
    if not secret:
        raise AuthError(canonical_error_message('invalid_response'), retryable=True, reason='invalid_response')
    request_kwargs = {'json': {'refresh_token': secret}, 'headers': {'Accept': 'application/json', 'Content-Type': 'application/json', 'Cache-Control': 'no-store'}, 'max_retries': 0}
    last_error: RemoteRequestError | None = None
    with create_configured_session() as session:
        for endpoint in _REFRESH_ENDPOINTS:
            try:
                response = api_request('POST', endpoint, session=session, timeout=get_http_timeout_seconds(), verify=get_request_verify_ssl(), **request_kwargs)
                try:
                    auth_payload = _unwrap_auth_response(_response_json(response))
                finally:
                    response.close()
                logger.info('Session refreshed endpoint=%s', endpoint)
                return _hydrate_authenticated_profile(auth_payload, session=session)
            except SessionExpiredError as exc:
                raise AuthError(canonical_error_message('invalid_credentials'), status_code=getattr(exc, 'status_code', 401), clear_remembered_session=True, reason='session_rejected') from exc
            except RemoteRequestError as exc:
                status_code = getattr(exc, 'status_code', None)
                if status_code in {401, 403}:
                    raise AuthError(canonical_error_message('invalid_credentials'), status_code=status_code, clear_remembered_session=True, reason='session_rejected') from exc
                if status_code in {404, 405, 422}:
                    last_error = exc
                    continue
                raise AuthError(user_error_message(exc, context='auth'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_auth_failure') from exc
            except SERVICE_OPERATION_EXCEPTIONS as exc:
                raise AuthError(user_error_message(exc, context='auth'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_auth_failure') from exc
    if last_error is not None:
        raise AuthError(user_error_message(last_error, context='auth')) from last_error
    raise AuthError(canonical_error_message('connection_failed'))

def _post(path: str, payload: dict) -> dict:
    logger.info('Auth request to: %s', path)
    try:
        data = api_post_json(path, payload, timeout=get_http_timeout_seconds(), verify=get_request_verify_ssl())
    except SessionExpiredError as exc:
        if str(path).rstrip('/').endswith('/auth/login'):
            logger.error('Login rejected status=401')
            raise AuthError(canonical_error_message('invalid_credentials'), status_code=getattr(exc, 'status_code', 401), clear_remembered_session=True, reason='session_rejected') from exc
        logger.error('Session expired during authentication request')
        raise AuthError(user_error_message(exc, context='auth'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_auth_failure') from exc
    except RemoteRequestError as exc:
        if getattr(exc, 'status_code', None) == 401 and str(path).rstrip('/').endswith('/auth/login'):
            logger.error('Login rejected status=401')
            raise AuthError(canonical_error_message('invalid_credentials'), status_code=getattr(exc, 'status_code', 401), clear_remembered_session=True, reason='session_rejected') from exc
        logger.error('Authentication request failed: %s', type(exc).__name__)
        raise AuthError(user_error_message(exc, context='auth'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_auth_failure') from exc
    except SERVICE_OPERATION_EXCEPTIONS as exc:
        logger.error('Authentication operation failed: %s', type(exc).__name__)
        raise AuthError(user_error_message(exc, context='auth'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_auth_failure') from exc
    if not isinstance(data, dict):
        logger.error('Invalid auth response type: %s', type(data))
        raise AuthError(canonical_error_message('invalid_response'), retryable=True, reason='invalid_response')
    return data

def sign_in_with_identifier_password(identifier: str, password: str) -> AuthSession:
    logger.info('Attempting server login')
    normalized_identifier = _normalize_login_identifier(identifier)
    data = _post_login(normalized_identifier, password)
    return _parse_auth_session(data, identifier=normalized_identifier)

def refresh_session(refresh_token: str, identifier: str='') -> AuthSession:
    if not str(refresh_token or '').strip():
        raise AuthError(canonical_error_message('invalid_response'), retryable=True, reason='invalid_response')
    secret = str(refresh_token).strip()
    data = _post_refresh(secret)
    data.setdefault('refresh_token', secret)
    return _parse_auth_session(
        data,
        identifier=_normalize_login_identifier(identifier),
    )

def change_own_password(api_client: Any, old_password: str, new_password: str) -> dict[str, Any]:
    if api_client is None:
        raise AuthError('Cloud service is not available.')
    try:
        result = api_client.change_own_password(old_password, new_password)
    except SessionExpiredError as exc:
        raise AuthError(user_error_message(exc, context='auth'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_auth_failure') from exc
    except RemoteRequestError as exc:
        raise AuthError(user_error_message(exc, context='auth'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_auth_failure') from exc
    except SERVICE_OPERATION_EXCEPTIONS as exc:
        raise AuthError(user_error_message(exc, context='auth'), status_code=getattr(exc, 'status_code', None), retryable=(getattr(exc, 'status_code', None) is None or getattr(exc, 'status_code', None) in {408, 429} or int(getattr(exc, 'status_code', 0) or 0) >= 500), reason='remote_auth_failure') from exc
    return dict(result or {})
