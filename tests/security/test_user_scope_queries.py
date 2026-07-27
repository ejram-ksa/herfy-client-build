from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class UserScopeQueryTests(unittest.TestCase):
    def test_parallel_data_and_sync_implementations_are_absent(self):
        self.assertFalse((ROOT / "runtime/data").exists())
        for relative in (
            "runtime/services/sync",
            "runtime/services/offline",
            "runtime/services/notifications",
            "runtime/services/ui",
        ):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_remembered_session_does_not_persist_authority(self):
        path = ROOT / "runtime/services/session/session_store.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        string_values = {
            node.value.casefold()
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        for forbidden in (
            "permissions",
            "permission_context",
            "allowed_branches",
            "branch_permissions",
            "role_permissions",
        ):
            self.assertNotIn(forbidden, string_values)

    def test_no_production_secrets(self):
        patterns = (
            re.compile(r"Bearer\s+eyJ", re.IGNORECASE),
            re.compile(
                r"(?im)^\s*(?:password|passwd|api_key|secret)\s*=\s*"
                r"[\"\'][^\"\']{4,}[\"\']"
            ),
            re.compile(r"BEGIN (?:OPENSSH|RSA|EC)? ?PRIVATE KEY", re.IGNORECASE),
        )
        for path in (ROOT / "runtime").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in patterns:
                self.assertIsNone(
                    pattern.search(text),
                    f"possible credential found in {path}: {pattern.pattern}",
                )
