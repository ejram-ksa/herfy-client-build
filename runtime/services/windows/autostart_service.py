from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


class RegistryBackend(Protocol):
    def set_value(self, name: str, value: str) -> None: ...

    def get_value(self, name: str) -> str | None: ...

    def delete_value(self, name: str) -> None: ...


class WindowsRunRegistryBackend:
    KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows registry is only available on Windows")
        import winreg

        self._winreg = winreg

    def set_value(self, name: str, value: str) -> None:
        with self._winreg.OpenKey(
            self._winreg.HKEY_CURRENT_USER,
            self.KEY_PATH,
            0,
            self._winreg.KEY_SET_VALUE,
        ) as key:
            self._winreg.SetValueEx(key, name, 0, self._winreg.REG_SZ, value)

    def get_value(self, name: str) -> str | None:
        try:
            with self._winreg.OpenKey(
                self._winreg.HKEY_CURRENT_USER,
                self.KEY_PATH,
                0,
                self._winreg.KEY_QUERY_VALUE,
            ) as key:
                value, _ = self._winreg.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None

    def delete_value(self, name: str) -> None:
        try:
            with self._winreg.OpenKey(
                self._winreg.HKEY_CURRENT_USER,
                self.KEY_PATH,
                0,
                self._winreg.KEY_SET_VALUE,
            ) as key:
                self._winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return


@dataclass(slots=True)
class AutostartService:
    app_name: str
    executable: Path
    backend: RegistryBackend
    arguments: Sequence[str] = ("--background",)

    def enable(self) -> None:
        self.backend.set_value(self._registry_name(), self.command())

    def disable(self) -> None:
        self.backend.delete_value(self._registry_name())

    def is_enabled(self) -> bool:
        return self.backend.get_value(self._registry_name()) == self.command()

    def command(self) -> str:
        executable = str(Path(self.executable).resolve())
        arguments = [str(argument) for argument in self.arguments if str(argument)]
        return subprocess.list2cmdline([executable, *arguments])

    def _registry_name(self) -> str:
        value = str(self.app_name or "").strip()
        if not value or "\x00" in value:
            raise ValueError("A valid autostart registry value name is required")
        return value
