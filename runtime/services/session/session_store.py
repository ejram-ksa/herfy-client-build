from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.infrastructure.persistence.secure_store import (
    read_secure_json,
    write_secure_json,
)
from runtime.shared.files import read_json_dict, write_json_dict
from runtime.shared.settings.config import runtime_cache_path

logger = logging.getLogger(__name__)

_SESSION_FORMAT = "remembered-session-v2"
_SECURE_FORMAT = "remembered-session-secret-v2"
_LOGIN_FORM_FORMAT = "login-form-state-v1"


@dataclass(frozen=True, slots=True)
class RememberedSessionSnapshot:
    """Minimal remembered-session material used only for server refresh.

    Cached roles, permissions, branches, and access tokens are deliberately not
    restored as authority. The application must refresh the token and obtain a
    new server-authoritative profile before opening the authenticated shell.
    """

    remember: bool
    user_id: str
    username: str
    refresh_token: str
    saved_at: int = 0


@dataclass(frozen=True, slots=True)
class LoginFormState:
    username: str = ""
    remember: bool = False


class SessionStore:
    """Canonical persistence boundary for the desktop login session.

    Public identity metadata and the encrypted refresh token are stored in
    separate files. The secure file is written first and the metadata file is
    the commit marker. On read, both sides must agree on the same user identity.
    """

    def __init__(
        self,
        metadata_file: str | Path | None = None,
        secure_file: str | Path | None = None,
        login_form_file: str | Path | None = None,
    ) -> None:
        self.metadata_file = Path(
            metadata_file or runtime_cache_path("session/session_metadata.json")
        )
        self.secure_file = Path(
            secure_file or runtime_cache_path("session/session_secure.json")
        )
        self.login_form_file = Path(
            login_form_file or runtime_cache_path("session/login_form.json")
        )

    def save(
        self,
        *,
        session: Any,
        profile: Any,
        remember: bool,
        permission_context: Any | None = None,
        saved_at: int = 0,
    ) -> None:
        """Persist only enough data to perform a server-side token refresh.

        ``permission_context`` is accepted for the application-facing contract
        but is intentionally ignored. Authorization is always fetched again
        from PostgreSQL-backed server authority after refresh.
        """

        del permission_context
        if not bool(remember):
            self.clear()
            return

        refresh_token = str(getattr(session, "refresh_token", "") or "").strip()
        username = str(
            getattr(profile, "username", "")
            or getattr(session, "uid", "")
            or ""
        ).strip()
        user_id = str(
            getattr(profile, "uid", "")
            or getattr(session, "uid", "")
            or username
        ).strip()
        if not refresh_token:
            self.clear_session()
            raise ValueError("refresh_token is required for remembered sessions")
        if not username or not user_id:
            self.clear_session()
            raise ValueError("user identity is required for remembered sessions")

        secure_payload = {
            "format": _SECURE_FORMAT,
            "user_id": user_id,
            "username": username,
            "refresh_token": refresh_token,
        }
        metadata_payload = {
            "format": _SESSION_FORMAT,
            "user_id": user_id,
            "username": username,
            "remember_session": True,
            "saved_at": self._safe_int(saved_at),
            "session_version": 1,
        }

        # The secure payload is staged first. Metadata is the commit marker; a
        # crash between writes yields either no metadata or an identity mismatch,
        # both of which fail closed in ``load_snapshot``.
        write_secure_json(self.secure_file, secure_payload, ensure_ascii=False)
        try:
            write_json_dict(self.metadata_file, metadata_payload, ensure_ascii=False)
        except Exception:
            self.clear_secure()
            raise

        self.save_login_form_state(username=username, remember=True)

    def load_snapshot(self) -> RememberedSessionSnapshot | None:
        metadata = read_json_dict(self.metadata_file)
        if not metadata:
            return None
        if metadata.get("format") not in {_SESSION_FORMAT, None, ""}:
            self._discard_invalid_session("unsupported metadata format")
            return None
        if not bool(metadata.get("remember_session")):
            self.clear_session()
            return None

        secure = read_secure_json(self.secure_file)
        if not secure:
            self._discard_invalid_session("secure payload missing")
            return None
        if secure.get("format") not in {_SECURE_FORMAT, None, ""}:
            self._discard_invalid_session("unsupported secure format")
            return None

        metadata_user = str(metadata.get("user_id") or "").strip()
        secure_user = str(secure.get("user_id") or metadata_user).strip()
        metadata_username = str(metadata.get("username") or "").strip()
        secure_username = str(secure.get("username") or metadata_username).strip()
        refresh_token = str(secure.get("refresh_token") or "").strip()

        if (
            not metadata_user
            or not metadata_username
            or not refresh_token
            or metadata_user.casefold() != secure_user.casefold()
            or metadata_username.casefold() != secure_username.casefold()
        ):
            self._discard_invalid_session("remembered session identity mismatch")
            return None

        return RememberedSessionSnapshot(
            remember=True,
            user_id=metadata_user,
            username=metadata_username,
            refresh_token=refresh_token,
            saved_at=self._safe_int(metadata.get("saved_at")),
        )

    def save_login_form_state(self, *, username: str, remember: bool) -> None:
        clean_username = str(username or "").strip()
        if not bool(remember) or not clean_username:
            self.clear_login_form_state()
            return
        write_json_dict(
            self.login_form_file,
            {
                "format": _LOGIN_FORM_FORMAT,
                "username": clean_username,
                "remember": True,
            },
            ensure_ascii=False,
        )

    def load_login_form_state(self) -> LoginFormState:
        payload = read_json_dict(self.login_form_file)
        if not payload:
            return LoginFormState()
        if payload.get("format") not in {_LOGIN_FORM_FORMAT, None, ""}:
            self.clear_login_form_state()
            return LoginFormState()
        remember = bool(payload.get("remember"))
        username = str(payload.get("username") or "").strip() if remember else ""
        return LoginFormState(username=username, remember=remember and bool(username))

    def clear(self) -> None:
        """Clear both remembered credentials and cached login-form identity."""

        self.clear_session()
        self.clear_login_form_state()

    def clear_session(self) -> None:
        self.clear_secure()
        self.clear_metadata()

    def clear_secure(self) -> None:
        self._unlink(self.secure_file)

    def clear_metadata(self) -> None:
        self._unlink(self.metadata_file)

    def clear_login_form_state(self) -> None:
        self._unlink(self.login_form_file)

    def _discard_invalid_session(self, reason: str) -> None:
        logger.warning("Discarding invalid remembered session: %s", reason)
        self.clear_session()

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except TypeError:
            if path.exists():
                path.unlink()
