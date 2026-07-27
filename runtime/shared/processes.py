from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from runtime.shared.objects import call_if_callable


def _resolve_cwd(cwd: str | Path | None) -> str | None:
    if cwd is None:
        return None
    resolved = Path(cwd).expanduser().resolve()
    if not resolved.is_dir():
        raise RuntimeError(f"Process working directory does not exist: {resolved}")
    return str(resolved)


def _normalize_command(command: Sequence[str | Path]) -> list[str]:
    args = [str(item) for item in command]
    if not args or not args[0].strip():
        raise RuntimeError("Cannot launch an empty process command")
    return args


def launch_detached(
    command: Sequence[str | Path], *, cwd: str | Path | None = None
) -> None:
    args = _normalize_command(command)
    options: dict[str, object] = {
        "cwd": _resolve_cwd(cwd),
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        options["creationflags"] = int(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        options["start_new_session"] = True
    subprocess.Popen(args, **options)  # noqa: S603


def launch_file(path: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise RuntimeError(f"Launch target does not exist: {target}")
    if os.name == "nt":
        start_file = getattr(os, "startfile", None)
        if not callable(start_file):
            raise RuntimeError("Windows file launcher is not available")
        call_if_callable(start_file, str(target))
        return
    launch_detached([target], cwd=target.parent)
