from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from runtime.application.services.updates import service as updates_service
from runtime.application.services.updates.service import PatchUpdateInfo, PatchUpdateService


def _write_valid_patch(path: Path) -> tuple[str, int]:
    files = {
        "HerfyClient.exe": b"client",
        "HerfyClientUpdateAgent.exe": b"agent",
        "version.json": b'{"version":"2.18.2"}',
        "resources/theme.qss": b"QWidget {}",
        "resources/i18n/ar.json": b"{}",
        "resources/i18n/en.json": b"{}",
    }
    manifest = "\n".join(sorted(files)) + "\n"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, payload in files.items():
            package.writestr(name, payload)
        package.writestr("runtime_files.txt", manifest)
    payload = path.read_bytes()
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PatchUpdateService:
    service = PatchUpdateService.__new__(PatchUpdateService)
    service.pending_root = tmp_path / "pending"
    service.pending_root.mkdir()
    root = tmp_path / "installed"
    root.mkdir()
    agent = root / "HerfyClientUpdateAgent.exe"
    client = root / "HerfyClient.exe"
    agent.write_bytes(b"agent")
    client.write_bytes(b"client")
    monkeypatch.setattr(service, "validate_install_runtime", lambda: (root, agent, client))
    return service


def _info(sha256: str, size: int) -> PatchUpdateInfo:
    return PatchUpdateInfo(
        available=True,
        current_version="2.18.1",
        target_version="2.18.2",
        sha256=sha256,
        size=size,
    )


def test_launch_update_agent_revalidates_integrity_and_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path, monkeypatch)
    patch = service.pending_root / "patch.zip"
    checksum, size = _write_valid_patch(patch)
    launched: list[tuple[list[object], Path]] = []
    monkeypatch.setattr(
        updates_service,
        "launch_detached",
        lambda command, cwd: launched.append((list(command), Path(cwd))),
    )

    service.launch_update_agent(patch, _info(checksum, size))

    assert len(launched) == 1
    command, cwd = launched[0]
    assert command[0].name == "HerfyClientUpdateAgent.exe"
    assert command[command.index("--sha256") + 1] == checksum
    assert command[command.index("--expected-size") + 1] == str(size)
    assert cwd.name == "installed"


def test_launch_update_agent_rejects_missing_integrity_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path, monkeypatch)
    patch = service.pending_root / "patch.zip"
    checksum, size = _write_valid_patch(patch)
    monkeypatch.setattr(
        updates_service,
        "launch_detached",
        lambda *_args, **_kwargs: pytest.fail("agent must not launch"),
    )

    with pytest.raises(RuntimeError, match="exact SHA256"):
        service.launch_update_agent(patch, _info("", size))
    with pytest.raises(RuntimeError, match="positive size"):
        service.launch_update_agent(patch, _info(checksum, 0))


def test_launch_update_agent_detects_tampering_before_process_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path, monkeypatch)
    patch = service.pending_root / "patch.zip"
    checksum, size = _write_valid_patch(patch)
    patch.write_bytes(patch.read_bytes() + b"tampered")
    monkeypatch.setattr(
        updates_service,
        "launch_detached",
        lambda *_args, **_kwargs: pytest.fail("agent must not launch"),
    )

    with pytest.raises(RuntimeError, match="size changed"):
        service.launch_update_agent(patch, _info(checksum, size))


def test_launch_update_agent_rejects_manifest_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path, monkeypatch)
    patch = service.pending_root / "patch.zip"
    files = {
        "HerfyClient.exe": b"client",
        "HerfyClientUpdateAgent.exe": b"agent",
        "version.json": b"{}",
        "resources/theme.qss": b"QWidget {}",
        "resources/i18n/ar.json": b"{}",
        "resources/i18n/en.json": b"{}",
    }
    with zipfile.ZipFile(patch, "w") as package:
        for name, content in files.items():
            package.writestr(name, content)
        package.writestr(
            "runtime_files.txt",
            "\n".join(sorted([*files, "missing.dll"])) + "\n",
        )
    payload = patch.read_bytes()
    monkeypatch.setattr(
        updates_service,
        "launch_detached",
        lambda *_args, **_kwargs: pytest.fail("agent must not launch"),
    )

    with pytest.raises(RuntimeError, match="does not match patch contents"):
        service.launch_update_agent(
            patch, _info(hashlib.sha256(payload).hexdigest(), len(payload))
        )


def test_download_patch_rejects_incomplete_integrity_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = PatchUpdateService.__new__(PatchUpdateService)
    service.pending_root = tmp_path / "pending"
    service.pending_root.mkdir()
    service.api_base_url = "https://example.invalid"
    service.http_timeout = 10.0
    service.verify_ssl = True
    monkeypatch.setattr(
        updates_service,
        "api_request",
        lambda *_args, **_kwargs: pytest.fail("network must not be called"),
    )

    missing_sha = _info("", 100)
    missing_sha = PatchUpdateInfo(
        **{**missing_sha.__dict__, "download_url": "https://example.invalid/patch.zip"}
    )
    with pytest.raises(RuntimeError, match="required SHA256"):
        service.download_patch(missing_sha)

    missing_size = _info("a" * 64, 0)
    missing_size = PatchUpdateInfo(
        **{**missing_size.__dict__, "download_url": "https://example.invalid/patch.zip"}
    )
    with pytest.raises(RuntimeError, match="positive size"):
        service.download_patch(missing_size)
