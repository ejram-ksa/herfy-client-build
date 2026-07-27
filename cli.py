from __future__ import annotations
import os
from collections.abc import Sequence
from runtime_health import run_runtime_diagnostics, run_runtime_self_check
from runtime_notification_health import (
    run_notification_demo,
    run_notification_self_check,
)
from runtime.shared.settings.version import __version__ as APP_VERSION

HELP_TEXT = f"""Herfy Client {APP_VERSION}

Usage:
  python main.py [option]

Options:
  --version
      Print the application version.
  --self-check
      Validate runtime dependencies, resources, and critical imports.
  --self-check-file PATH
      Write the runtime self-check result to PATH.
  --diagnose
      Print runtime diagnostics.
  --diagnose-file PATH
      Write diagnostics to PATH.
  --notification-self-check
      Validate expiry thresholds, sounds, Qt, tray, printing, and paths.
  --notification-self-check-file PATH
      Write the notification runtime check to PATH.
  --notification-demo
      Show a real Windows notification and play the selected sound.
  -h, --help
      Show this help.
"""


def _argument_value(arguments: Sequence[str], name: str) -> str | None:
    try:
        index = list(arguments).index(name)
    except ValueError:
        return None
    next_index = index + 1
    if next_index >= len(arguments):
        return None
    value = str(arguments[next_index]).strip()
    return value or None


def handle_cli_shortcut(arguments: Sequence[str]) -> int | None:
    args = set(arguments)
    env_self_check_file = os.environ.get("HERFY_SELF_CHECK_FILE")
    env_notification_check_file = os.environ.get("HERFY_NOTIFICATION_SELF_CHECK_FILE")
    if env_self_check_file:
        return run_runtime_self_check(env_self_check_file)
    if env_notification_check_file:
        return run_notification_self_check(env_notification_check_file)
    if "-h" in args or "--help" in args:
        print(HELP_TEXT)
        return 0
    if "--version" in args:
        print(APP_VERSION)
        return 0
    if "--self-check" in args or "--self-check-file" in args:
        return run_runtime_self_check(_argument_value(arguments, "--self-check-file"))
    if "--diagnose" in args or "--diagnose-file" in args:
        return run_runtime_diagnostics(_argument_value(arguments, "--diagnose-file"))
    if "--notification-self-check" in args or "--notification-self-check-file" in args:
        return run_notification_self_check(
            _argument_value(arguments, "--notification-self-check-file")
        )
    if "--notification-demo" in args:
        return run_notification_demo()
    return None
