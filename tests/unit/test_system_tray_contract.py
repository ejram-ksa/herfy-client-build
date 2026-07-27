from __future__ import annotations

import unittest
from pathlib import Path

from runtime.presentation.qt.tray_contract import EXIT_TEXT, LOGOUT_TEXT, OPEN_TEXT, TrayBadgeState


class SystemTrayContractTests(unittest.TestCase):
    def test_menu_contains_exactly_requested_labels(self):
        self.assertEqual(OPEN_TEXT, "فتح")
        self.assertEqual(LOGOUT_TEXT, "تسجيل الخروج")
        self.assertEqual(EXIT_TEXT, "إغلاق")

    def test_badge_state_for_notifications_and_update(self):
        self.assertEqual(TrayBadgeState(0, False).text, "")
        self.assertEqual(TrayBadgeState(4, False).text, "4")
        self.assertEqual(TrayBadgeState(120, False).text, "99+")
        self.assertEqual(TrayBadgeState(0, True).text, "!")
        self.assertTrue(TrayBadgeState(2, True).visible)

    def test_actions_have_no_menu_icons_or_styling_calls(self):
        root = Path(__file__).resolve().parents[2]
        text = (
            root / "runtime/presentation/qt/system_tray_adapter.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("setIcon(", text.split("def _apply_icon", 1)[0])
        self.assertNotIn("setStyleSheet(", text)
        self.assertEqual(text.count("self.menu.addAction("), 3)

    def test_update_menu_badge_also_updates_the_tray_badge(self):
        root = Path(__file__).resolve().parents[2]
        text = (
            root
            / "runtime/presentation/main_window/cloud_sections/cloud_runtime.py"
        ).read_text(encoding="utf-8")
        method = text.split("def _set_update_action_badge", 1)[1].split(
            "def check_for_updates_now", 1
        )[0]
        assert "set_tray_update_available" in method
        assert "set_tray_update(bool(available))" in method

