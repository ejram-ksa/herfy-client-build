from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from runtime.application.services.auth import AuthError, refresh_session
from runtime.domain.access import PermissionContext
from runtime.domain.user import AuthSession, UserProfile
from runtime.services.session import SessionStore, classify_restore_failure
from runtime.shared.errors import RemoteRequestError, SessionExpiredError


@dataclass
class _Profile:
    uid: str = "u-1"
    username: str = "H1074"


def _session(*, refresh_token: str = "token-for-validation") -> AuthSession:
    return AuthSession(
        id_token="access-secret",
        uid="u-1",
        role="store_user",
        refresh_token=refresh_token,
        permission_context=PermissionContext(),
    )


def _store(root: str) -> SessionStore:
    base = Path(root)
    return SessionStore(
        metadata_file=base / "metadata.json",
        secure_file=base / "secure.json",
        login_form_file=base / "login-form.json",
    )


def test_session_store_round_trip_contains_only_refresh_authority():
    with tempfile.TemporaryDirectory() as temp:
        store = _store(temp)
        store.save(
            session=_session(),
            profile=_Profile(),
            remember=True,
            permission_context=object(),
            saved_at=123,
        )
        snapshot = store.load_snapshot()
        assert snapshot is not None
        assert snapshot.user_id == "u-1"
        assert snapshot.username == "H1074"
        assert snapshot.refresh_token == "token-for-validation"
        assert snapshot.saved_at == 123

        metadata = (Path(temp) / "metadata.json").read_text(encoding="utf-8")
        secure = (Path(temp) / "secure.json").read_text(encoding="utf-8")
        assert "access-secret" not in metadata
        assert "token-for-validation" not in metadata
        assert "access-secret" not in secure
        assert "token-for-validation" not in secure
        assert "permissions" not in metadata
        assert "branches" not in metadata


def test_session_store_without_remember_clears_all_identity_state():
    with tempfile.TemporaryDirectory() as temp:
        store = _store(temp)
        store.save_login_form_state(username="H1074", remember=True)
        store.save(
            session=_session(),
            profile=_Profile(),
            remember=True,
            saved_at=1,
        )
        store.save(
            session=_session(),
            profile=_Profile(),
            remember=False,
            saved_at=2,
        )
        assert store.load_snapshot() is None
        assert not (Path(temp) / "metadata.json").exists()
        assert not (Path(temp) / "secure.json").exists()
        assert not (Path(temp) / "login-form.json").exists()


def test_session_store_rejects_cross_user_file_mismatch():
    with tempfile.TemporaryDirectory() as temp:
        store = _store(temp)
        store.save(
            session=_session(),
            profile=_Profile(),
            remember=True,
            saved_at=1,
        )
        from runtime.infrastructure.persistence.secure_store import (
            read_secure_json,
            write_secure_json,
        )

        secure_path = Path(temp) / "secure.json"
        secure = read_secure_json(secure_path)
        secure["user_id"] = "u-2"
        write_secure_json(secure_path, secure)
        assert store.load_snapshot() is None
        assert not (Path(temp) / "metadata.json").exists()
        assert not secure_path.exists()


def test_login_form_is_saved_only_when_remember_is_enabled():
    with tempfile.TemporaryDirectory() as temp:
        store = _store(temp)
        store.save_login_form_state(username="H1074", remember=False)
        assert store.load_login_form_state().username == ""
        store.save_login_form_state(username="H1074", remember=True)
        state = store.load_login_form_state()
        assert state.username == "H1074"
        assert state.remember is True
        store.clear()
        assert store.load_login_form_state().remember is False


def test_explicit_auth_rejection_is_terminal():
    decision = classify_restore_failure(
        SessionExpiredError("expired", status_code=401)
    )
    assert decision.clear_persistent_session is True
    assert decision.retryable is False
    assert decision.reason == "session_rejected"


def test_wrapped_server_outage_preserves_remembered_session():
    cause = RemoteRequestError("unavailable", status_code=503)
    error = AuthError("server unavailable", retryable=True)
    error.__cause__ = cause
    decision = classify_restore_failure(error)
    assert decision.clear_persistent_session is False
    assert decision.retryable is True


def test_unknown_runtime_failure_is_non_destructive():
    decision = classify_restore_failure(RuntimeError("unexpected"))
    assert decision.clear_persistent_session is False
    assert decision.retryable is False
    assert decision.reason == "restore_failed"


def test_refresh_preserves_existing_refresh_token_when_server_omits_rotation():
    payload = {
        "access_token": "new-access",
        "user_id": "u-1",
        "username": "H1074",
        "role": "store_user",
        "permissions": [],
        "scope": {"branches": []},
        "permission_source": "postgresql.role_permissions",
    }
    with patch("runtime.application.services.auth.service._post_refresh", return_value=payload):
        restored = refresh_session("existing-refresh", "H1074")
    assert restored.refresh_token == "existing-refresh"


def test_ui_persistence_boundary_honors_the_users_remember_choice():
    root = Path(__file__).resolve().parents[2]
    source = (
        root / "runtime/presentation/main_window/session_sections/session.py"
    ).read_text(encoding="utf-8")
    section = source[source.index("def _save_persistent_session"):]
    section = section[: section.index("def _clear_persistent_session")]
    assert 'remember_session = bool(getattr(self, "_remember_session", False))' in section
    assert "remember=remember_session" in section
    assert "remember=True" not in section
    assert 's.remove("session/remember")' in section
