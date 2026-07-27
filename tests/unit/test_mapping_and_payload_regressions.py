from __future__ import annotations

import ast
from pathlib import Path

from runtime.application.services.auth import LoginRemoteNoticeService
from runtime.domain.access import PermissionContext, scope_candidates
from runtime.domain.updates import parse_update_payload
from runtime.infrastructure.network.http import _detail_from_response
from runtime.shared.objects import first_value


class _Response:
    text = "fallback"

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_mapping_helpers_use_their_supplied_mapping():
    assert first_value({"a": "", "b": "value"}, "a", "b") == "value"
    assert scope_candidates({"branches": ["H-19"], "area_id": "A1", "region_id": "R1"}) == (
        ["H-19"],
        ["A1"],
        ["R1"],
    )


def test_http_detail_uses_response_json_payload():
    response = _Response({"detail": [{"loc": ["body", "username"], "msg": "required"}]})
    assert _detail_from_response(response) == "body.username: required"


def test_login_notice_uses_supplied_settings():
    notice = LoginRemoteNoticeService.evaluate(
        {
            "remote_maintenance_enabled": True,
            "remote_maintenance_message": "Maintenance window",
        }
    )
    assert notice.message == "Maintenance window"
    assert notice.severity == "warning"


def test_permission_and_update_payloads_are_parsed_from_arguments():
    context = PermissionContext.from_payload(
        {
            "user_id": "42",
            "username": "H1074",
            "role": "branch_user",
            "permission_source": "postgresql.role_permissions",
            "permissions": ["tracking.view"],
            "scope": {"branches": ["H1074"]},
            "active_branch": "H1074",
        }
    )
    assert context.username == "H1074"
    assert context.active_branch == "H1074"
    assert context.has_permission("tracking.view")

    update = parse_update_payload(
        {
            "current_version": "2.18.1",
            "latest_version": "2.18.2",
            "update_available": True,
            "mandatory": False,
            "packages": [],
        },
        current_version="2.18.1",
        base_url="https://example.invalid",
    )
    assert update.target_version == "2.18.2"


def test_no_corrupted_persistence_mapping_calls_remain():
    root = Path(__file__).resolve().parents[2] / "runtime"
    forbidden = "runtime.infrastructure.persistence"
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            parts = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            dotted = ".".join(reversed(parts))
            if dotted.startswith(forbidden + "."):
                tail = dotted[len(forbidden) + 1 :].split(".", 1)[0]
                if tail in {"get", "setdefault", "items", "keys", "values"}:
                    violations.append(f"{path.relative_to(root.parent)}:{node.lineno}:{dotted}")
    assert not violations, "\n".join(violations)
