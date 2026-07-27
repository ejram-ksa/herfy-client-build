from __future__ import annotations

import argparse
import os
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

_DEFAULT_TIMESTAMP = (2000, 1, 1, 0, 0, 0)
_EXECUTABLE_SUFFIXES = {".cmd", ".ps1", ".sh"}
_EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "output",
    "publish",
    "venv",
    "htmlcov",
}
_EXCLUDED_FILE_NAMES = {".coverage", "coverage.xml"}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".temp", ".bak"}


def _zip_timestamp() -> tuple[int, int, int, int, int, int]:
    raw = str(os.environ.get("SOURCE_DATE_EPOCH") or "").strip()
    if not raw:
        return _DEFAULT_TIMESTAMP
    try:
        value = max(315532800, int(raw))
        converted = datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError):
        return _DEFAULT_TIMESTAMP
    if converted.year > 2107:
        return (2107, 12, 31, 23, 59, 58)
    return (
        converted.year,
        converted.month,
        converted.day,
        converted.hour,
        converted.minute,
        converted.second - converted.second % 2,
    )


def iter_archive_files(source_root: Path, *, output_path: Path | None = None):
    root = Path(source_root).resolve()
    output = Path(output_path).resolve() if output_path is not None else None
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in _EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        if path.is_symlink():
            raise RuntimeError(f"Symbolic links are not allowed: {relative.as_posix()}")
        if not path.is_file():
            continue
        if output is not None and path.resolve() == output:
            continue
        if path.name in _EXCLUDED_FILE_NAMES or path.name.startswith(".coverage."):
            continue
        if path.suffix.lower() in _EXCLUDED_SUFFIXES:
            continue
        archive_name = PurePosixPath(*relative.parts).as_posix()
        if not archive_name or archive_name.startswith("/") or ".." in relative.parts:
            raise RuntimeError(f"Unsafe source path: {archive_name!r}")
        yield path, archive_name


def build_source_archive(source_root: Path, destination: Path) -> dict[str, object]:
    root = Path(source_root).resolve()
    output = Path(destination).resolve()
    if not root.is_dir():
        raise RuntimeError(f"Source root does not exist: {root}")
    output.parent.mkdir(parents=True, exist_ok=True)

    files = list(iter_archive_files(root, output_path=output))
    names = [name for _, name in files]
    if not files:
        raise RuntimeError("Source archive would contain no files")
    if len(names) != len(set(names)):
        raise RuntimeError("Source archive contains duplicate member names")

    timestamp = _zip_timestamp()
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent)
    )
    os.close(fd)
    temporary = Path(temporary_name)
    total_size = 0
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            for path, archive_name in files:
                payload = path.read_bytes()
                total_size += len(payload)
                mode = 0o755 if path.suffix.lower() in _EXECUTABLE_SUFFIXES else 0o644
                info = zipfile.ZipInfo(filename=archive_name, date_time=timestamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.flag_bits |= 0x800
                archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "archive": str(output),
        "files": len(files),
        "uncompressed_bytes": total_size,
        "archive_bytes": output.stat().st_size,
        "timestamp": "%04d-%02d-%02dT%02d:%02d:%02dZ" % timestamp,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic editable-source ZIP.")
    parser.add_argument("source_root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    report = build_source_archive(args.source_root, args.destination)
    print(
        "HERFY_SOURCE_ARCHIVE_BUILT "
        f"files={report['files']} "
        f"uncompressed_bytes={report['uncompressed_bytes']} "
        f"archive_bytes={report['archive_bytes']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
