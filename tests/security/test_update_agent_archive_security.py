from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from runtime.bootstrap.runtime import update_agent


_REQUIRED_FILES = {
    update_agent.APP_EXE_NAME: b"client",
    update_agent.AGENT_EXE_NAME: b"agent",
    "version.json": b'{"app_version":"2.18.2"}',
    "resources/theme.qss": b"QWidget {}",
    "resources/i18n/ar.json": b"{}",
    "resources/i18n/en.json": b"{}",
}
_REQUIRED_FILES[update_agent.RUNTIME_MANIFEST_NAME] = (
    "\n".join(_REQUIRED_FILES) + "\n"
).encode("utf-8")


def _write_archive(path: Path, extra_members: list[tuple[zipfile.ZipInfo | str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in _REQUIRED_FILES.items():
            archive.writestr(name, data)
        for member, data in extra_members:
            archive.writestr(member, data)


def test_archive_traversal_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "traversal.zip"
    _write_archive(package, [("../evil.txt", b"evil")])
    with pytest.raises(RuntimeError, match="Unsafe patch member path"):
        update_agent._validate_patch_zip(package)


def test_case_insensitive_duplicate_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "duplicate.zip"
    _write_archive(package, [("Data/Item.txt", b"one"), ("data/item.TXT", b"two")])
    with pytest.raises(RuntimeError, match="Case-insensitive duplicate"):
        update_agent._validate_patch_zip(package)


def test_windows_alternate_data_stream_path_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "ads.zip"
    _write_archive(package, [("resources/file.txt:stream", b"bad")])
    with pytest.raises(RuntimeError, match="Windows-incompatible"):
        update_agent._validate_patch_zip(package)


def test_windows_reserved_filename_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "reserved.zip"
    _write_archive(package, [("resources/CON.txt", b"bad")])
    with pytest.raises(RuntimeError, match="Windows-incompatible"):
        update_agent._validate_patch_zip(package)


def test_symbolic_link_member_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("resources/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    _write_archive(package, [(link, b"target")])
    with pytest.raises(RuntimeError, match="Symbolic-link"):
        update_agent._validate_patch_zip(package)


def test_suspicious_compression_ratio_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "bomb.zip"
    _write_archive(package, [("resources/large.bin", b"0" * (2 * 1024 * 1024))])
    with pytest.raises(RuntimeError, match="Suspicious compression ratio"):
        update_agent._validate_patch_zip(package)


def test_python_source_artifact_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "source.zip"
    _write_archive(package, [("runtime/hidden.py", b"print('bad')")])
    with pytest.raises(RuntimeError, match="Source/cache artifact"):
        update_agent._validate_patch_zip(package)


def test_runtime_manifest_must_declare_every_packaged_file(tmp_path: Path) -> None:
    package = tmp_path / "undeclared.zip"
    _write_archive(package, [("resources/undeclared.dat", b"data")])
    with pytest.raises(RuntimeError, match="does not match patch contents"):
        update_agent._validate_patch_zip(package)


def test_runtime_manifest_rejects_case_insensitive_duplicate_entries(
    tmp_path: Path,
) -> None:
    package = tmp_path / "manifest-duplicate.zip"
    files = dict(_REQUIRED_FILES)
    files[update_agent.RUNTIME_MANIFEST_NAME] = (
        files[update_agent.RUNTIME_MANIFEST_NAME]
        + b"resources/theme.qss\nRESOURCES/THEME.QSS\n"
    )
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with pytest.raises(RuntimeError, match="duplicate runtime manifest"):
        update_agent._validate_patch_zip(package)


def test_runtime_manifest_rejects_windows_reserved_entry(tmp_path: Path) -> None:
    package = tmp_path / "manifest-reserved.zip"
    files = dict(_REQUIRED_FILES)
    files[update_agent.RUNTIME_MANIFEST_NAME] += b"resources/CON.txt\n"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with pytest.raises(RuntimeError, match="Windows-incompatible"):
        update_agent._validate_patch_zip(package)
