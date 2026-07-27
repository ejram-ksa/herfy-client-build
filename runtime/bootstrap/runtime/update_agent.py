from __future__ import annotations
import argparse
import contextlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from runtime.shared.files import sha256_file as _sha256_file
from runtime.shared.processes import launch_detached
from runtime.domain.update_archive import (
    validate_patch_zip as _validate_patch_zip,
    validate_runtime_manifest_names,
)

logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
APP_EXE_NAME = "HerfyClient.exe"
AGENT_EXE_NAME = "HerfyClientUpdateAgent.exe"
RUNTIME_MANIFEST_NAME = "runtime_files.txt"
_RUNTIME_KEEP_DIRS = {".pending_update", ".update_backup", "installer"}
_RUNTIME_KEEP_FILES = {AGENT_EXE_NAME.lower(), "installer_defaults.ini"}
_INNO_UNINSTALLER_SUFFIXES = {".exe", ".dat", ".msg"}



def _is_inno_uninstaller_file(name: str) -> bool:
    candidate = Path(name).name.casefold()
    stem = Path(candidate).stem
    suffix = Path(candidate).suffix
    return (
        suffix in _INNO_UNINSTALLER_SUFFIXES
        and stem.startswith("unins")
        and stem[5:].isdigit()
    )


def _is_runtime_keep_path(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return True
    if parts[0].casefold() in _RUNTIME_KEEP_DIRS:
        return True
    name = relative.name.casefold()
    return name in _RUNTIME_KEEP_FILES or _is_inno_uninstaller_file(name)


def _remove_tree_with_retry(
    path: Path, *, attempts: int = 20, delay_seconds: float = 0.25
) -> None:
    if not path.exists():
        return
    last_error: OSError | None = None
    for _ in range(max(1, attempts)):
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(max(0.01, delay_seconds))
    raise RuntimeError(f"Unable to remove directory: {path}: {last_error}")


def _prune_update_backups(root: Path, *, keep: int = 3) -> None:
    backup_parent = root / ".update_backup"
    if not backup_parent.is_dir():
        return
    backups = sorted(
        (item for item in backup_parent.iterdir() if item.is_dir()),
        key=lambda item: item.name,
        reverse=True,
    )
    for stale in backups[max(1, keep) :]:
        _remove_tree_with_retry(stale)


def _remove_previous_update_artifacts(root: Path) -> None:
    previous_restore = root / ".update_restore_backup"
    if previous_restore.exists():
        _remove_tree_with_retry(previous_restore)


def _snapshot_runtime(destination: Path, backup_root: Path) -> None:
    """Capture the complete replaceable runtime before changing any file."""
    if backup_root.exists():
        raise RuntimeError(f"Update backup already exists: {backup_root}")
    backup_root.mkdir(parents=True, exist_ok=False)
    for item in sorted(destination.rglob("*")):
        if item.is_dir():
            continue
        relative = item.relative_to(destination)
        if _is_runtime_keep_path(relative):
            continue
        target = backup_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def _remove_replaceable_runtime(destination: Path) -> None:
    for item in sorted(
        destination.rglob("*"), key=lambda value: len(value.parts), reverse=True
    ):
        if item == destination or not item.exists():
            continue
        relative = item.relative_to(destination)
        if _is_runtime_keep_path(relative):
            continue
        if item.is_dir():
            with contextlib.suppress(OSError):
                item.rmdir()
            continue
        item.unlink()


def _restore_runtime_snapshot(backup_root: Path, destination: Path) -> None:
    pending = destination / ".pending_update"
    if pending.exists():
        _remove_tree_with_retry(pending)
    _remove_replaceable_runtime(destination)
    for item in sorted(backup_root.rglob("*")):
        if item.is_dir():
            continue
        relative = item.relative_to(backup_root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def _runtime_manifest_entries(root: Path) -> set[Path]:
    manifest = root / RUNTIME_MANIFEST_NAME
    if not manifest.is_file():
        raise RuntimeError(f"Runtime manifest is missing: {manifest}")
    names = validate_runtime_manifest_names(
        manifest.read_text(encoding="utf-8-sig").splitlines()
    )
    return {Path(*name.split("/")) for name in names}


def _delete_stale_runtime_files(source: Path, destination: Path) -> None:
    """Remove every replaceable file absent from the declared runtime manifest."""
    expected_files = _runtime_manifest_entries(source) | {Path(RUNTIME_MANIFEST_NAME)}
    for item in sorted(
        destination.rglob("*"), key=lambda value: len(value.parts), reverse=True
    ):
        if item == destination or not item.exists():
            continue
        relative = item.relative_to(destination)
        if _is_runtime_keep_path(relative):
            continue
        if item.is_dir():
            with contextlib.suppress(OSError):
                item.rmdir()
            continue
        if relative in expected_files:
            continue
        item.unlink()


def _verify_runtime_file_set(source: Path, destination: Path) -> None:
    expected = {
        item
        for item in _runtime_manifest_entries(source)
        if not _is_runtime_keep_path(item)
    } | {Path(RUNTIME_MANIFEST_NAME)}
    actual = {
        item.relative_to(destination)
        for item in destination.rglob("*")
        if item.is_file() and not _is_runtime_keep_path(item.relative_to(destination))
    }
    missing = sorted(str(item) for item in expected - actual)
    extra = sorted(str(item) for item in actual - expected)
    if missing or extra:
        raise RuntimeError(
            "Installed runtime file set does not match manifest. "
            f"missing={missing[:10]} extra={extra[:10]}"
        )
    source_artifacts = sorted(
        str(item.relative_to(destination))
        for item in destination.rglob("*")
        if item.is_file()
        and item.suffix.lower() in {".py", ".pyc", ".pyo"}
        and not _is_runtime_keep_path(item.relative_to(destination))
    )
    if source_artifacts:
        raise RuntimeError(
            f"Source files leaked into installed runtime: {source_artifacts[:10]}"
        )


def _verify_updated_runtime(destination: Path) -> None:
    executable = destination / APP_EXE_NAME
    version_file = destination / "version.json"
    if not executable.is_file() or not version_file.is_file():
        raise RuntimeError("Updated runtime is missing the executable or version.json")
    version_data = json.loads(version_file.read_text(encoding="utf-8"))
    expected_version = str(
        version_data.get("app_version") or version_data.get("version") or ""
    ).strip()
    if not expected_version:
        raise RuntimeError("Updated runtime version.json has no version")
    with tempfile.TemporaryDirectory(prefix="herfy_update_self_check_") as temp_dir:
        result_path = Path(temp_dir) / "self_check.json"
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["HERFY_SELF_CHECK_FILE"] = str(result_path)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        )
        completed = subprocess.run(
            [str(executable), "--self-check"],
            cwd=str(destination),
            env=environment,
            timeout=120,
            check=False,
            creationflags=creation_flags,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Updated executable self-check exited with {completed.returncode}"
            )
        if not result_path.is_file():
            raise RuntimeError("Updated executable self-check produced no result file")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if str(payload.get("status") or "") != "ok":
            raise RuntimeError(f"Updated executable self-check failed: {payload}")
        if str(payload.get("version") or "") != expected_version:
            raise RuntimeError(
                "Updated executable self-check version mismatch. "
                f"expected={expected_version} actual={payload.get('version')}"
            )
        if not bool(payload.get("frozen")):
            raise RuntimeError("Updated executable self-check reported frozen=false")
    _write_line(f"HERFY_UPDATE_RUNTIME_SELF_CHECK_OK version={expected_version}")


def _write_line(message: str) -> None:
    logger.info(message)


def _safe_resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _validate_package_integrity(
    patch_zip: Path, *, expected_sha256: str = "", expected_size: int = 0
) -> None:
    normalized_sha = str(expected_sha256 or "").strip().lower()
    if len(normalized_sha) != 64 or any(
        character not in "0123456789abcdef" for character in normalized_sha
    ):
        raise RuntimeError("A valid expected patch SHA256 checksum is required")
    if int(expected_size or 0) <= 0:
        raise RuntimeError("A positive expected patch size is required")
    actual_size = patch_zip.stat().st_size
    if actual_size != int(expected_size):
        raise RuntimeError(
            f"Patch size mismatch. expected={expected_size} actual={actual_size}"
        )
    actual = _sha256_file(patch_zip).lower()
    if actual != normalized_sha:
        raise RuntimeError(
            f"Patch SHA256 mismatch. expected={normalized_sha} actual={actual}"
        )


def _wait_for_target_release(root: Path, wait_seconds: int) -> None:
    target = root / APP_EXE_NAME
    temp_name = root / f".{APP_EXE_NAME}.rename_test"
    probe = root / f".{APP_EXE_NAME}.write_test"
    deadline = time.monotonic() + max(1, int(wait_seconds))
    while time.monotonic() < deadline:
        try:
            if temp_name.exists() and not target.exists():
                temp_name.rename(target)
            elif temp_name.exists():
                temp_name.unlink()
            if not target.exists():
                return
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            target.rename(temp_name)
            try:
                temp_name.rename(target)
            except OSError:
                with contextlib.suppress(OSError):
                    if temp_name.exists() and not target.exists():
                        temp_name.rename(target)
                raise
            return
        except OSError:
            with contextlib.suppress(OSError):
                probe.unlink(missing_ok=True)
            time.sleep(1)
    with contextlib.suppress(OSError):
        if temp_name.exists() and not target.exists():
            temp_name.rename(target)
    raise RuntimeError(f"Timed out waiting for {APP_EXE_NAME} to close")


def _copy_tree_contents(source: Path, destination: Path) -> bool:
    destination = destination.resolve()
    _delete_stale_runtime_files(source, destination)
    staged_agent_update = False
    for item in sorted(source.rglob("*")):
        if item.is_dir():
            continue
        relative = item.relative_to(source)
        if relative.name.lower() == AGENT_EXE_NAME.lower():
            pending = destination / ".pending_update" / AGENT_EXE_NAME
            pending.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, pending)
            staged_agent_update = True
            continue
        target = (destination / relative).resolve()
        if destination not in target.parents and target != destination:
            raise RuntimeError(f"Unsafe target path rejected: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
    return staged_agent_update


def _extract_patch(patch_zip: Path) -> tuple[Path, Path]:
    """Extract validated members without delegating path creation to extractall()."""
    temp_root = Path(tempfile.mkdtemp(prefix="herfy_update_extract_")).resolve()
    try:
        with zipfile.ZipFile(patch_zip, "r") as package:
            for member in package.infolist():
                name = member.filename.replace("\\", "/")
                if not name or name.endswith("/"):
                    continue
                target = (temp_root / Path(*name.split("/"))).resolve()
                if temp_root not in target.parents:
                    raise RuntimeError(
                        f"Unsafe extraction target rejected: {member.filename}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                with (
                    package.open(member, "r") as source,
                    target.open("xb") as destination,
                ):
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
        return temp_root, temp_root
    except BaseException:
        with contextlib.suppress(RuntimeError):
            _remove_tree_with_retry(temp_root)
        raise


def _restart_application(restart: Path) -> None:
    if not restart.exists():
        return
    launch_detached([restart], cwd=restart.parent)


def _escape_cmd_value(value: str | Path) -> str:
    text = str(value)
    if any(character in text for character in ("\r", "\n", '"')):
        raise RuntimeError("Unsafe character in update command path")
    return text.replace("^", "^^").replace("%", "%%")


def _schedule_agent_self_replace(
    root: Path, restart: Path, *, restart_after_update: bool = True
) -> None:
    pending = root / ".pending_update" / AGENT_EXE_NAME
    target = root / AGENT_EXE_NAME
    if os.name != "nt" or not pending.exists():
        if restart_after_update:
            _restart_application(restart)
        return
    script = root / ".pending_update" / "complete_update.cmd"
    lines = [
        "@echo off",
        "setlocal",
        f'set "SOURCE={_escape_cmd_value(pending)}"',
        f'set "TARGET={_escape_cmd_value(target)}"',
        f'set "RESTART={_escape_cmd_value(restart)}"',
        "for /L %%i in (1,1,45) do (",
        '  copy /Y "%SOURCE%" "%TARGET%" >nul 2>nul && goto copied',
        "  timeout /t 1 /nobreak >nul",
        ")",
        '> "%~dp0complete_update_failed.log" echo Failed to replace HerfyClientUpdateAgent.exe after 45 attempts.',
        *(
            ['if exist "%RESTART%" start "" /D "%~dp0.." "%RESTART%"']
            if restart_after_update
            else []
        ),
        "exit /b 1",
        ":copied",
        'del /Q "%SOURCE%" >nul 2>nul',
        *(
            ['if exist "%RESTART%" start "" /D "%~dp0.." "%RESTART%"']
            if restart_after_update
            else []
        ),
        'del /Q "%~f0" >nul 2>nul',
        "exit /b 0",
    ]
    script.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    launch_detached(["cmd.exe", "/c", script], cwd=root)


def apply_patch(
    patch_zip: Path,
    root: Path,
    restart: Path,
    wait_seconds: int,
    *,
    expected_sha256: str = "",
    expected_size: int = 0,
    restart_after_update: bool = True,
) -> int:
    patch_zip = _safe_resolve(patch_zip)
    root = _safe_resolve(root)
    restart = _safe_resolve(restart)
    if not root.is_dir():
        raise RuntimeError(f"Install root does not exist: {root}")
    expected_restart = (root / APP_EXE_NAME).resolve()
    if restart != expected_restart:
        raise RuntimeError(
            "Restart target must be the existing HerfyClient.exe in the current install root"
        )
    _validate_package_integrity(
        patch_zip, expected_sha256=expected_sha256, expected_size=expected_size
    )
    _validate_patch_zip(patch_zip)
    _wait_for_target_release(root, wait_seconds)
    _remove_previous_update_artifacts(root)
    pending_root = root / ".pending_update"
    if pending_root.exists():
        _remove_tree_with_retry(pending_root)
    backup_root = root / ".update_backup" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    _snapshot_runtime(root, backup_root)
    extracted: Path | None = None
    extraction_root: Path | None = None
    try:
        extracted, extraction_root = _extract_patch(patch_zip)
        staged_agent_update = _copy_tree_contents(extracted, root)
        _verify_runtime_file_set(extracted, root)
        _verify_updated_runtime(root)
    except (OSError, RuntimeError, ValueError, TimeoutError, zipfile.BadZipFile):
        _write_line("Patch failed; restoring complete runtime snapshot...")
        _restore_runtime_snapshot(backup_root, root)
        raise
    finally:
        if extraction_root is not None and extraction_root.exists():
            _remove_tree_with_retry(extraction_root)
    try:
        if staged_agent_update:
            _schedule_agent_self_replace(
                root, restart, restart_after_update=restart_after_update
            )
        elif restart_after_update:
            _restart_application(restart)
    except (OSError, RuntimeError, ValueError, TimeoutError):
        _write_line(
            "Post-copy activation failed; restoring complete runtime snapshot..."
        )
        _restore_runtime_snapshot(backup_root, root)
        with contextlib.suppress(OSError, RuntimeError, ValueError):
            _restart_application(root / APP_EXE_NAME)
        raise
    # Backup pruning is housekeeping and must never turn a successful update into
    # a reported failure after the new runtime has already been activated.
    with contextlib.suppress(OSError, RuntimeError):
        _prune_update_backups(root)
    with contextlib.suppress(OSError):
        patch_zip.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        pending_root = root / ".pending_update"
        if pending_root.is_dir() and not any(pending_root.iterdir()):
            pending_root.rmdir()
    _write_line(f"HERFY_UPDATE_AGENT_OK root={root} restart={restart}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Herfy Client safe update agent")
    parser.add_argument(
        "--apply", dest="patch_zip", required=True, help="Verified patch zip path"
    )
    parser.add_argument(
        "--root", dest="root", required=True, help="Installed application directory"
    )
    parser.add_argument(
        "--restart", dest="restart", required=True, help="Application exe to restart"
    )
    parser.add_argument(
        "--wait",
        dest="wait",
        type=int,
        default=60,
        help="Seconds to wait for app shutdown",
    )
    parser.add_argument("--sha256", default="", help="Expected patch SHA256")
    parser.add_argument(
        "--expected-size", type=int, default=0, help="Expected patch size in bytes"
    )
    parser.add_argument(
        "--validation-no-restart",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validation_no_restart = bool(args.validation_no_restart)
        if validation_no_restart and os.environ.get(
            "HERFY_UPDATE_AGENT_VALIDATION"
        ) != "1":
            raise RuntimeError(
                "--validation-no-restart is restricted to the build validation environment"
            )
        return apply_patch(
            Path(args.patch_zip),
            Path(args.root),
            Path(args.restart),
            args.wait,
            expected_sha256=args.sha256,
            expected_size=args.expected_size,
            restart_after_update=not validation_no_restart,
        )
    except (OSError, RuntimeError, ValueError, TimeoutError, zipfile.BadZipFile) as exc:
        _write_line(f"HERFY_UPDATE_AGENT_FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
