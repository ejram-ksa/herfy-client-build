from __future__ import annotations

import unittest
from pathlib import Path


class CanonicalUpdateAgentTests(unittest.TestCase):
    def test_only_one_update_agent_source_exists(self):
        root = Path(__file__).resolve().parents[2]
        canonical = root / "runtime/bootstrap/runtime/update_agent.py"
        previous = root / "runtime/bootstrap/updater_agent.py"
        duplicate_stack = root / "runtime/services/update"
        self.assertTrue(canonical.is_file())
        self.assertFalse(previous.exists())
        self.assertFalse(duplicate_stack.exists())

    def test_pyinstaller_uses_canonical_agent(self):
        root = Path(__file__).resolve().parents[2]
        spec = (
            root / "build/installer/pyinstaller/HerfyClientUpdateAgent.spec"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'ROOT / "runtime" / "bootstrap" / "runtime" / "update_agent.py"',
            spec,
        )
        self.assertNotIn(
            'ROOT / "runtime" / "bootstrap" / "updater_agent.py"',
            spec,
        )
