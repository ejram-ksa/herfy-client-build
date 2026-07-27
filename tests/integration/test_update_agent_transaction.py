from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.bootstrap.runtime import update_agent


def _runtime_files() -> dict[str, bytes]:
    manifest_entries = [
        update_agent.APP_EXE_NAME,
        update_agent.AGENT_EXE_NAME,
        "version.json",
        "resources/theme.qss",
        "resources/i18n/ar.json",
        "resources/i18n/en.json",
        "new_runtime.dat",
    ]
    return {
        update_agent.APP_EXE_NAME: b"new-client",
        update_agent.AGENT_EXE_NAME: b"new-agent",
        "version.json": json.dumps({"app_version": "2.18.2"}).encode("utf-8"),
        "resources/theme.qss": b"QWidget { min-width: 1px; }",
        "resources/i18n/ar.json": b"{}",
        "resources/i18n/en.json": b"{}",
        "new_runtime.dat": b"new-runtime",
        update_agent.RUNTIME_MANIFEST_NAME: (
            "\n".join(manifest_entries) + "\n"
        ).encode("utf-8"),
    }


def _build_patch(path: Path) -> tuple[str, int]:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in _runtime_files().items():
            archive.writestr(name, data)
    payload = path.read_bytes()
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _build_install(root: Path) -> Path:
    root.mkdir()
    (root / update_agent.APP_EXE_NAME).write_bytes(b"old-client")
    (root / update_agent.AGENT_EXE_NAME).write_bytes(b"old-agent")
    (root / "version.json").write_text(
        json.dumps({"app_version": "2.18.1"}), encoding="utf-8"
    )
    (root / "resources").mkdir()
    (root / "resources/theme.qss").write_text("old-theme", encoding="utf-8")
    (root / "stale_runtime.dat").write_bytes(b"stale")
    return root / update_agent.APP_EXE_NAME


def _apply(package: Path, root: Path, restart: Path, sha256: str, size: int) -> int:
    with (
        patch.object(update_agent, "_wait_for_target_release", return_value=None),
        patch.object(update_agent, "_verify_updated_runtime", return_value=None),
        patch.object(update_agent, "_schedule_agent_self_replace", return_value=None),
        patch.object(update_agent, "_restart_application", return_value=None),
    ):
        return update_agent.apply_patch(
            package,
            root,
            restart,
            1,
            expected_sha256=sha256,
            expected_size=size,
        )


def test_canonical_update_agent_replaces_runtime_and_removes_stale_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "install"
    restart = _build_install(root)
    package = tmp_path / "update.zip"
    sha256, size = _build_patch(package)

    result = _apply(package, root, restart, sha256, size)

    assert result == 0
    assert (root / update_agent.APP_EXE_NAME).read_bytes() == b"new-client"
    assert (root / update_agent.AGENT_EXE_NAME).read_bytes() == b"old-agent"
    assert (root / ".pending_update" / update_agent.AGENT_EXE_NAME).read_bytes() == b"new-agent"
    assert (root / "new_runtime.dat").read_bytes() == b"new-runtime"
    assert not (root / "stale_runtime.dat").exists()
    assert not package.exists()


def test_canonical_update_agent_restores_complete_snapshot_on_verification_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "install"
    restart = _build_install(root)
    package = tmp_path / "update.zip"
    sha256, size = _build_patch(package)

    with (
        patch.object(update_agent, "_wait_for_target_release", return_value=None),
        patch.object(
            update_agent,
            "_verify_updated_runtime",
            side_effect=RuntimeError("forced verification failure"),
        ),
        patch.object(update_agent, "_schedule_agent_self_replace", return_value=None),
        patch.object(update_agent, "_restart_application", return_value=None),
    ):
        with pytest.raises(RuntimeError, match="forced verification failure"):
            update_agent.apply_patch(
                package,
                root,
                restart,
                1,
                expected_sha256=sha256,
                expected_size=size,
            )

    assert (root / update_agent.APP_EXE_NAME).read_bytes() == b"old-client"
    assert (root / update_agent.AGENT_EXE_NAME).read_bytes() == b"old-agent"
    assert (root / "version.json").read_text(encoding="utf-8") == json.dumps(
        {"app_version": "2.18.1"}
    )
    assert (root / "resources/theme.qss").read_text(encoding="utf-8") == "old-theme"
    assert (root / "stale_runtime.dat").read_bytes() == b"stale"
    assert not (root / "new_runtime.dat").exists()
    assert package.exists()


def test_canonical_update_agent_rejects_tampered_package_before_runtime_changes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "install"
    restart = _build_install(root)
    package = tmp_path / "update.zip"
    sha256, size = _build_patch(package)
    package.write_bytes(package.read_bytes() + b"tampered")

    with pytest.raises(RuntimeError, match="Patch size mismatch"):
        _apply(package, root, restart, sha256, size)

    assert (root / update_agent.APP_EXE_NAME).read_bytes() == b"old-client"
    assert (root / "stale_runtime.dat").read_bytes() == b"stale"


def test_canonical_update_agent_requires_exact_integrity_metadata(
    tmp_path: Path,
) -> None:
    root = tmp_path / "install"
    restart = _build_install(root)
    package = tmp_path / "update.zip"
    _build_patch(package)

    with pytest.raises(RuntimeError, match="SHA256 checksum is required"):
        update_agent.apply_patch(package, root, restart, 1)

    assert (root / update_agent.APP_EXE_NAME).read_bytes() == b"old-client"
    assert (root / "stale_runtime.dat").read_bytes() == b"stale"


def test_canonical_update_agent_requires_positive_expected_size(
    tmp_path: Path,
) -> None:
    root = tmp_path / "install"
    restart = _build_install(root)
    package = tmp_path / "update.zip"
    sha256, _ = _build_patch(package)

    with pytest.raises(RuntimeError, match="positive expected patch size"):
        update_agent.apply_patch(
            package,
            root,
            restart,
            1,
            expected_sha256=sha256,
            expected_size=0,
        )

    assert (root / update_agent.APP_EXE_NAME).read_bytes() == b"old-client"
