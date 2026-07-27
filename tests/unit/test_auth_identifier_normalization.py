from __future__ import annotations

from unittest.mock import patch

from runtime.application.services.auth.service import (
    _canonical_login_request,
    _normalize_login_identifier,
    sign_in_with_identifier_password,
)


def test_branch_style_login_identifier_is_case_canonicalized():
    assert _normalize_login_identifier("h1074") == "H1074"
    assert _normalize_login_identifier(" H0019 ") == "H0019"
    assert _canonical_login_request("h1074", "secret")["json"]["username"] == "H1074"


def test_general_login_identifiers_are_not_rewritten():
    assert _normalize_login_identifier("john@example.com") == "john@example.com"
    assert _normalize_login_identifier("herfy-admin") == "herfy-admin"
    assert _normalize_login_identifier("1074") == "1074"


def test_normalized_identifier_is_used_for_request_and_session_identity():
    payload = {"access_token": "token", "username": "H1074"}
    with (
        patch(
            "runtime.application.services.auth.service._post_login",
            return_value=payload,
        ) as post_login,
        patch(
            "runtime.application.services.auth.service._parse_auth_session",
            return_value=object(),
        ) as parse_session,
    ):
        sign_in_with_identifier_password("h1074", "secret")
    post_login.assert_called_once_with("H1074", "secret")
    parse_session.assert_called_once_with(payload, identifier="H1074")
