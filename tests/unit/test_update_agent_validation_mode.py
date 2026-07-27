from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

from runtime.bootstrap.runtime import update_agent


def _argv(tmp_path: Path) -> list[str]:
    return [
        "update_agent",
        "--apply",
        str(tmp_path / "update.zip"),
        "--root",
        str(tmp_path / "install"),
        "--restart",
        str(tmp_path / "install" / update_agent.APP_EXE_NAME),
        "--validation-no-restart",
    ]


def test_validation_no_restart_is_rejected_without_explicit_environment(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(sys, "argv", _argv(tmp_path))
    monkeypatch.delenv("HERFY_UPDATE_AGENT_VALIDATION", raising=False)
    apply_mock = Mock(return_value=0)
    monkeypatch.setattr(update_agent, "apply_patch", apply_mock)

    assert update_agent.main() == 1
    apply_mock.assert_not_called()


def test_validation_no_restart_disables_activation_only_in_validation_environment(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(sys, "argv", _argv(tmp_path))
    monkeypatch.setenv("HERFY_UPDATE_AGENT_VALIDATION", "1")
    apply_mock = Mock(return_value=0)
    monkeypatch.setattr(update_agent, "apply_patch", apply_mock)

    assert update_agent.main() == 0
    assert apply_mock.call_args.kwargs["restart_after_update"] is False
