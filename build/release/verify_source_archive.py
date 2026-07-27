from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

_MAX_MEMBER_BYTES = 256 * 1024 * 1024
_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 500.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member_name(name: str) -> str:
    if not name or "\x00" in name or "\\" in name:
        raise RuntimeError(f"Unsafe ZIP member name: {name!r}")
    pure = PurePosixPath(name)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeError(f"Unsafe ZIP member path: {name!r}")
    if ":" in pure.parts[0]:
        raise RuntimeError(f"Drive-qualified ZIP member is not allowed: {name!r}")
    canonical = pure.as_posix()
    if canonical != name.rstrip("/"):
        raise RuntimeError(f"Non-canonical ZIP member name: {name!r}")
    return canonical


def _tree_entries(root: Path) -> dict[str, tuple[int, str]]:
    entries: dict[str, tuple[int, str]] = {}
    for path in sorted(Path(root).rglob("*")):
        relative = path.relative_to(root)
        if any(part in {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"} for part in relative.parts):
            continue
        if path.is_symlink():
            raise RuntimeError(f"Symbolic link is not allowed: {relative.as_posix()}")
        if path.is_file():
            entries[relative.as_posix()] = (path.stat().st_size, _sha256(path))
    return entries


def _run_extracted_validator(root: Path, relative_script: str) -> str:
    script = root / relative_script
    if not script.is_file():
        raise RuntimeError(f"Archive is missing validator: {relative_script}")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("PYTHONUTF8", "1")
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = str(completed.stdout or "")
    if completed.returncode != 0:
        raise RuntimeError(
            f"Extracted source validator failed: {relative_script}\n{output.strip()}"
        )
    return output.strip()


def verify_source_archive(
    archive_path: Path,
    *,
    source_root: Path | None = None,
    verify_metadata: bool = False,
) -> dict[str, object]:
    archive_file = Path(archive_path).resolve()
    if not archive_file.is_file():
        raise RuntimeError(f"Source archive does not exist: {archive_file}")

    members: dict[str, tuple[int, str]] = {}
    total_uncompressed = 0
    with zipfile.ZipFile(archive_file, "r") as archive:
        seen: set[str] = set()
        for info in archive.infolist():
            name = _safe_member_name(info.filename)
            if name in seen:
                raise RuntimeError(f"Duplicate ZIP member: {name}")
            seen.add(name)
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise RuntimeError(f"Symbolic-link ZIP member is not allowed: {name}")
            if info.is_dir():
                continue
            if info.file_size < 0 or info.file_size > _MAX_MEMBER_BYTES:
                raise RuntimeError(f"ZIP member has an invalid size: {name}")
            total_uncompressed += info.file_size
            if total_uncompressed > _MAX_TOTAL_BYTES:
                raise RuntimeError("ZIP archive exceeds the total uncompressed-size limit")
            if info.file_size > 1024 * 1024:
                if info.compress_size <= 0:
                    raise RuntimeError(f"ZIP member has an invalid compressed size: {name}")
                ratio = info.file_size / info.compress_size
                if ratio > _MAX_COMPRESSION_RATIO:
                    raise RuntimeError(f"ZIP member compression ratio is excessive: {name}")
            with archive.open(info, "r") as stream:
                digest = hashlib.sha256()
                read_size = 0
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    read_size += len(chunk)
                    if read_size > _MAX_MEMBER_BYTES:
                        raise RuntimeError(f"ZIP member exceeded the read limit: {name}")
                    digest.update(chunk)
            if read_size != info.file_size:
                raise RuntimeError(f"ZIP member size changed while reading: {name}")
            members[name] = (info.file_size, digest.hexdigest())
        corrupt = archive.testzip()
        if corrupt is not None:
            raise RuntimeError(f"ZIP CRC validation failed for member: {corrupt}")

    if not members:
        raise RuntimeError("Source archive contains no files")

    if source_root is not None:
        expected = _tree_entries(Path(source_root).resolve())
        if members != expected:
            missing = sorted(set(expected) - set(members))
            extra = sorted(set(members) - set(expected))
            changed = sorted(
                name
                for name in set(expected) & set(members)
                if expected[name] != members[name]
            )
            raise RuntimeError(
                "Source archive does not match the source tree: "
                f"missing={missing} extra={extra} changed={changed}"
            )

    validation_outputs: list[str] = []
    if verify_metadata:
        with tempfile.TemporaryDirectory(prefix="herfy-source-archive-") as temp_dir:
            extracted = Path(temp_dir)
            with zipfile.ZipFile(archive_file, "r") as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    name = _safe_member_name(info.filename)
                    destination = extracted.joinpath(*PurePosixPath(name).parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
            validation_outputs.append(
                _run_extracted_validator(
                    extracted, "build/release/verify_source_manifest.py"
                )
            )
            validation_outputs.append(
                _run_extracted_validator(
                    extracted, "build/release/verify_source_hygiene.py"
                )
            )

    return {
        "archive": str(archive_file),
        "archive_sha256": _sha256(archive_file),
        "archive_bytes": archive_file.stat().st_size,
        "files": len(members),
        "uncompressed_bytes": total_uncompressed,
        "metadata_verified": bool(verify_metadata),
        "validation_outputs": validation_outputs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an editable-source ZIP.")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--verify-metadata", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify_source_archive(
        args.archive,
        source_root=args.source_root,
        verify_metadata=args.verify_metadata,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        "HERFY_SOURCE_ARCHIVE_OK "
        f"files={report['files']} "
        f"archive_bytes={report['archive_bytes']} "
        f"metadata_verified={str(report['metadata_verified']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
