from __future__ import annotations
import re
from typing import Any
from runtime.shared.settings.config import _

_LOGIN_FALLBACK = "Sign in failed. Check the username and password, then try again."
_GENERAL_FALLBACK = "The operation could not be completed. Please try again."
_CANONICAL_ERROR_MESSAGES = {
    "invalid_credentials": "The username or password is incorrect. Check the credentials and try again.",
    "missing_credentials": "Username and password are required.",
    "session_expired": "Your session expired. Sign in again to continue.",
    "server_unavailable": "The server is temporarily unavailable. Wait a moment and try again.",
    "server_timeout": "The server did not respond in time. Check the connection and try again.",
    "connection_failed": "Cannot reach the server. Check the internet connection and try again.",
    "malformed_response": "The server returned an unreadable response. Try again or contact support.",
    "invalid_response": "The server response was incomplete. Try again or contact support.",
    "profile_missing": "Sign in succeeded, but the account profile is incomplete. Contact the administrator.",
    "permission_denied": "You do not have permission to perform this action.",
    "account_inactive": "This account is inactive. Ask a system administrator to reactivate it.",
    "login_access_denied": "Sign-in was rejected by the server before a session was created. Verify that the account is active and assigned a valid role.",
    "operation_failed": _GENERAL_FALLBACK,
    "login_failed": _LOGIN_FALLBACK,
    "settings_open_failed": "Settings could not be opened. Close other dialogs and try again.",
    "settings_save_failed": "Settings could not be saved. Review the values and try again.",
    "admin_open_failed": "The administration workspace could not be opened. Check the connection and your permissions, then try again.",
    "password_change_failed": "The password could not be changed. Check the current password and try again.",
    "update_install_failed": "The update could not be installed. Try again from the main application or contact support.",
    "update_package_missing": "The update package is not available on the update server. Contact support or retry after the server package is published.",
}


def canonical_error_message(key: str) -> str:
    return _(_CANONICAL_ERROR_MESSAGES.get(str(key or ""), _GENERAL_FALLBACK))


def _clean_error_text(error: Any) -> str:
    text = str(error or "").strip()
    text = re.sub("\\s+", " ", text)
    if "<html" in text.lower() or "traceback" in text.lower():
        return ""
    return text


def classify_user_error(error: Any, *, context: str = "general") -> str:
    raw = str(error or "")
    raw_lower = raw.lower()
    text = _clean_error_text(error)
    lower = text.lower()
    normalized_context = str(context or "general").strip().lower()
    if (
        normalized_context == "password"
        and text
        and any(
            (
                marker in lower
                for marker in (
                    "current password",
                    "old password",
                    "incorrect password",
                    "invalid password",
                )
            )
        )
    ):
        return "password_change_failed"
    if not text:
        if any(
            (
                marker in raw_lower
                for marker in (
                    "502",
                    "503",
                    "504",
                    "bad gateway",
                    "temporarily unavailable",
                )
            )
        ):
            return "server_unavailable"
        if "timeout" in raw_lower or "timed out" in raw_lower:
            return "server_timeout"
        if any(
            (
                marker in raw_lower
                for marker in (
                    "cannot connect",
                    "connection error",
                    "failed to establish",
                )
            )
        ):
            return "connection_failed"
        return "login_failed" if normalized_context == "login" else "operation_failed"
    if any(
        (
            marker in lower
            for marker in (
                "invalid username or password",
                "incorrect username or password",
                "bad credentials",
                "401",
                "unauthorized",
                "not authenticated",
            )
        )
    ):
        return (
            "invalid_credentials"
            if normalized_context == "login"
            else "session_expired"
        )
    if "missing token" in lower or "server did not return a session" in lower:
        return "invalid_response"
    if "profile missing" in lower or "profile is incomplete" in lower:
        return "profile_missing"
    if "account is inactive" in lower:
        return "account_inactive"
    if "sign-in was rejected by the server" in lower:
        return "login_access_denied"
    if "timed out" in lower or "timeout" in lower:
        return "server_timeout"
    if any(
        (
            marker in lower
            for marker in (
                "cannot connect",
                "connection error",
                "name resolution",
                "failed to establish",
            )
        )
    ):
        return "connection_failed"
    if any(
        (
            marker in lower
            for marker in (
                "502",
                "503",
                "504",
                "bad gateway",
                "temporarily unavailable",
            )
        )
    ):
        return "server_unavailable"
    if any((marker in lower for marker in ("malformed json", "unreadable response"))):
        return "malformed_response"
    if any((marker in lower for marker in ("invalid response", "incomplete"))):
        return "invalid_response"
    if any((marker in lower for marker in ("permission", "forbidden", "403"))):
        return "permission_denied"
    if normalized_context == "password":
        return "password_change_failed"
    if normalized_context == "settings":
        return "settings_save_failed"
    if normalized_context == "update" and any(
        (marker in lower or marker in raw_lower for marker in ("404", "not found"))
    ):
        return "update_package_missing"
    if normalized_context == "update":
        return "update_install_failed"
    return "login_failed" if normalized_context == "login" else "operation_failed"


def user_error_message(error: Any, *, context: str = "general") -> str:
    text = _clean_error_text(error)
    normalized_context = str(context or "general").strip().lower()
    key = classify_user_error(error, context=normalized_context)
    if normalized_context == "general" and key == "operation_failed" and text:
        return _(text)
    return canonical_error_message(key)
