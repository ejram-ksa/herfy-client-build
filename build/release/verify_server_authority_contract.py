from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    from runtime.domain.access import PermissionContext
    from runtime.application.services.admin import _current_user_has_full_admin
    from runtime.domain.user import AuthSession
    from runtime.application.services.auth import (
        AuthError,
        _flatten_auth_payload,
        load_user_profile_from_session,
    )
    from runtime.infrastructure.network.tracking_api import RemoteTrackingMetadataMixin

    role_only = PermissionContext.from_payload(
        {
            "username": "root-like-name",
            "role": "system",
            "permissions": ["*"],
            "scope": {
                "all_regions": True,
                "all_areas": True,
                "all_branches": True,
            },
        }
    )
    require(not role_only.permissions, "untrusted role payload granted permissions")
    require(
        not role_only.scope.all_branches,
        "untrusted role payload granted all-branch scope",
    )
    require(
        not role_only.can_access_branch("1019"),
        "role name alone granted branch access",
    )
    try:
        load_user_profile_from_session(
            AuthSession(
                id_token="token",
                uid="root-like-name",
                role="system",
                permission_context=role_only,
            )
        )
    except AuthError:
        pass
    else:
        raise RuntimeError("login accepted a profile without server authority")

    username_only = _flatten_auth_payload(
        {"user": {"username": "H1119", "role": "store_user"}}
    )
    require(
        "scope" not in username_only
        and "branches" not in username_only
        and "branch_scope" not in username_only,
        "username was converted into local branch authority",
    )

    trusted = PermissionContext.from_payload(
        {
            "username": "server-admin",
            "role": "system",
            "permissions": ["*", "sync.pull", "sync.push"],
            "scope": {
                "regions": [],
                "areas": [],
                "branches": [],
                "all_regions": True,
                "all_areas": True,
                "all_branches": True,
            },
            "permission_source": "postgresql.role_permissions",
            "authority_revision": 7,
            "is_active": True,
        }
    )
    require(trusted.has_permission("tracking.create"), "trusted wildcard was ignored")
    require(trusted.can_access_branch("1019"), "trusted all-branch scope was ignored")
    require(
        trusted.authority_revision == 7
        and trusted.authority_source == "postgresql.role_permissions",
        "authority metadata was not preserved",
    )

    restricted = PermissionContext.from_payload(
        {
            "username": "branch-user",
            "role": "system",
            "permissions": ["tracking.view", "sync.pull"],
            "scope": {
                "branches": ["1019"],
                "all_regions": False,
                "all_areas": False,
                "all_branches": False,
            },
            "permission_source": "postgresql.role_permissions",
            "authority_revision": 3,
        }
    )
    require(restricted.can_access_branch("1019"), "explicit server scope was lost")
    require(
        not restricted.can_access_branch("9999"),
        "system role bypassed explicit restricted scope",
    )
    require(
        not restricted.has_permission("tracking.create"),
        "system role bypassed explicit permission list",
    )

    require(
        not _current_user_has_full_admin({"role": "system", "permissions": []}),
        "admin service granted full access from role name",
    )
    require(
        _current_user_has_full_admin({"role": "store_user", "permissions": ["*"]}),
        "admin service ignored server wildcard permission",
    )

    class Probe(RemoteTrackingMetadataMixin):
        def __init__(self, user):
            self.user = user

    untrusted_probe = Probe(
        {
            "role": "system",
            "permissions": ["*"],
            "scope": {"all_branches": True, "branches": []},
        }
    )
    require(
        not untrusted_probe._server_authority_valid(),
        "remote API accepted unsigned authority payload",
    )
    require(
        not untrusted_probe._server_scope_all_branches(),
        "remote API granted global scope from role payload",
    )
    require(
        not untrusted_probe._server_has_permission("sync.pull"),
        "remote API granted permission from unsigned payload",
    )

    trusted_probe = Probe(trusted.to_payload())
    require(trusted_probe._server_authority_valid(), "trusted authority was rejected")
    require(
        trusted_probe._server_has_permission("sync.pull"),
        "trusted server permission was not enforced",
    )

    authority_sources = "\n".join(
        [
            inspect.getsource(PermissionContext.from_payload),
            inspect.getsource(RemoteTrackingMetadataMixin),
        ]
    )
    for forbidden in (
        'role_norm == "system"',
        'role == "system" or',
        'safe_get(self.user, "role")',
    ):
        require(
            forbidden not in authority_sources, f"role fallback remains: {forbidden}"
        )

    print(
        "HERFY_SERVER_AUTHORITY_CLIENT_OK "
        "role=no-grant username=no-scope permissions=postgresql-only scope=postgresql-only"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
