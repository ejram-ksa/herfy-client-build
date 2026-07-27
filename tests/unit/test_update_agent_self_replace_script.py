from __future__ import annotations

from pathlib import Path

import pytest

from runtime.bootstrap.runtime import update_agent


def test_self_replace_script_restarts_app_on_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "installed"
    pending = root / ".pending_update"
    pending.mkdir(parents=True)
    (pending / update_agent.AGENT_EXE_NAME).write_bytes(b"new-agent")
    restart = root / update_agent.APP_EXE_NAME
    restart.write_bytes(b"client")
    launched: list[tuple[list[object], Path]] = []
    monkeypatch.setattr(update_agent.os, "name", "nt")
    monkeypatch.setattr(
        update_agent,
        "launch_detached",
        lambda command, cwd: launched.append((list(command), Path(cwd))),
    )

    update_agent._schedule_agent_self_replace(root, restart)

    script = (pending / "complete_update.cmd").read_text(encoding="utf-8")
    restart_line = 'if exist "%RESTART%" start "" /D "%~dp0.." "%RESTART%"'
    assert script.count(restart_line) == 2
    assert script.index(restart_line) < script.index("exit /b 1")
    assert script.rindex(restart_line) > script.index(":copied")
    assert len(launched) == 1
    command, cwd = launched[0]
    assert command == ["cmd.exe", "/c", pending / "complete_update.cmd"]
    assert cwd.as_posix() == root.as_posix()


def test_self_replace_validation_mode_does_not_restart_on_failure_or_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "installed"
    pending = root / ".pending_update"
    pending.mkdir(parents=True)
    (pending / update_agent.AGENT_EXE_NAME).write_bytes(b"new-agent")
    restart = root / update_agent.APP_EXE_NAME
    restart.write_bytes(b"client")
    monkeypatch.setattr(update_agent.os, "name", "nt")
    monkeypatch.setattr(update_agent, "launch_detached", lambda *_args, **_kwargs: None)

    update_agent._schedule_agent_self_replace(
        root, restart, restart_after_update=False
    )

    script = (pending / "complete_update.cmd").read_text(encoding="utf-8")
    assert 'start ""' not in script
