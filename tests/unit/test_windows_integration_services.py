from __future__ import annotations

import unittest
from pathlib import Path

from runtime.services.windows import AutostartService


class FakeRegistry:
    def __init__(self):
        self.values = {}

    def set_value(self, name, value):
        self.values[name] = value

    def get_value(self, name):
        return self.values.get(name)

    def delete_value(self, name):
        self.values.pop(name, None)


class WindowsIntegrationServiceTests(unittest.TestCase):
    def test_autostart_enable_disable_and_quote(self):
        backend = FakeRegistry()
        service = AutostartService("Herfy", Path("/tmp/Herfy Client.exe"), backend)
        service.enable()
        self.assertTrue(service.is_enabled())
        self.assertEqual(
            backend.values["Herfy"],
            f'"{Path("/tmp/Herfy Client.exe").resolve()}" --background',
        )
        service.disable()
        self.assertFalse(service.is_enabled())
    def test_autostart_quotes_multiple_arguments_with_spaces(self):
        backend = FakeRegistry()
        service = AutostartService(
            "Herfy",
            Path("/tmp/Python Runtime/pythonw.exe"),
            backend,
            ("/tmp/Herfy Source/main.py", "--background"),
        )
        service.enable()
        command = backend.values["Herfy"]
        self.assertIn('"/tmp/Python Runtime/pythonw.exe"', command)
        self.assertIn('"/tmp/Herfy Source/main.py"', command)
        self.assertTrue(command.endswith("--background"))

    def test_autostart_rejects_an_empty_registry_value_name(self):
        backend = FakeRegistry()
        service = AutostartService("  ", Path("/tmp/app.exe"), backend)
        with self.assertRaises(ValueError):
            service.enable()

