from __future__ import annotations
import unittest
from pathlib import Path

class WindowsIntegrationSecurityTests(unittest.TestCase):
    def test_autostart_uses_current_user_run_key(self):
        root=Path(__file__).resolve().parents[2]
        text=(root/"runtime/services/windows/autostart_service.py").read_text(encoding="utf-8")
        self.assertIn("HKEY_CURRENT_USER",text)
        self.assertNotIn("HKEY_LOCAL_MACHINE",text)

    def test_update_agent_does_not_use_shell(self):
        root=Path(__file__).resolve().parents[2]
        for rel in [
            "runtime/bootstrap/runtime/update_agent.py",
            "runtime/shared/processes.py",
        ]:
            text = (root / rel).read_text(encoding="utf-8")
            self.assertNotIn("shell=True", text)
    def test_windows_run_registry_has_one_canonical_implementation(self):
        root = Path(__file__).resolve().parents[2]
        registry_modules = []
        for path in (root / "runtime").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "import winreg" in text or "SetValueEx(" in text:
                registry_modules.append(path.relative_to(root).as_posix())
        self.assertEqual(
            registry_modules,
            ["runtime/services/windows/autostart_service.py"],
        )
        sync_source = (
            root / "runtime/application/services/sync/service.py"
        ).read_text(encoding="utf-8")
        self.assertIn("AutostartService", sync_source)
        self.assertIn("WindowsRunRegistryBackend", sync_source)
        self.assertNotIn("SetValueEx(", sync_source)

