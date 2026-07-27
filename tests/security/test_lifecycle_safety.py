from __future__ import annotations

import unittest
from pathlib import Path


class LifecycleSafetyTests(unittest.TestCase):
    def test_scheduler_uses_single_thread_implementation(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "runtime/services/lifecycle/background_scheduler.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("threading.Thread("), 1)
        self.assertNotIn("threading.Timer(", text)

    def test_single_instance_binds_only_localhost(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "runtime/bootstrap/runtime/single_instance.py").read_text(encoding="utf-8")
        self.assertIn('host: str = "127.0.0.1"', text)
