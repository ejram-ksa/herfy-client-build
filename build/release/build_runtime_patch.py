from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.domain.update_archive import (  # noqa: E402
    MAX_PATCH_FILE_SIZE,
    MAX_PATCH_MEMBERS,
    MAX_PATCH_TOTAL_SIZE,
    REQUIRED_PATCH_FILES,
    is_forbidden_patch_artifact,
    validate_archive_name,
    validate_patch_zip,
)


def _relative_files(source: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(
                f"Symbolic link cannot enter runtime patch: {path.relative_to(source)}"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        archive_name = PurePosixPath(*relative.parts).as_posix()
        parts = validate_archive_name(archive_name)
        if is_forbidden_patch_artifact(archive_name, parts):
            raise RuntimeError(
                f"Source/cache artifact cannot enter runtime patch: {relative}"
            )
        files.append((path, archive_name))
    return files


def build_runtime_patch(source: Path, output: Path, expected_version: str) -> None:
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise RuntimeError(f"Runtime directory does not exist: {source}")
    version_file = source / "version.json"
    if not version_file.is_file():
        raise RuntimeError("Runtime version.json is missing")
    version_data = json.loads(version_file.read_text(encoding="utf-8"))
    actual_version = str(
        version_data.get("app_version") or version_data.get("version") or ""
    )
    if actual_version != expected_version:
        raise RuntimeError(
            f"Runtime version mismatch. expected={expected_version} actual={actual_version}"
        )
    files = _relative_files(source)
    if len(files) > MAX_PATCH_MEMBERS:
        raise RuntimeError(f"Runtime patch contains too many files: {len(files)}")
    total_size = sum(path.stat().st_size for path, _ in files)
    if total_size > MAX_PATCH_TOTAL_SIZE:
        raise RuntimeError(f"Runtime patch is too large when extracted: {total_size}")
    oversized = [
        archive_name
        for path, archive_name in files
        if path.stat().st_size > MAX_PATCH_FILE_SIZE
    ]
    if oversized:
        raise RuntimeError(f"Runtime patch contains an oversized file: {oversized[0]}")
    names = {archive_name for _, archive_name in files}
    folded_names = {name.casefold() for name in names}
    if len(folded_names) != len(names):
        raise RuntimeError("Runtime patch contains case-insensitive duplicate paths")
    missing = sorted(REQUIRED_PATCH_FILES - names)
    if missing:
        raise RuntimeError(
            f"Runtime patch is incomplete. Missing: {', '.join(missing)}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.stem}.",
            suffix=".tmp.zip",
            dir=output.parent,
            delete=False,
        ) as handle:
            temp = Path(handle.name)
        with zipfile.ZipFile(
            temp,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as package:
            for path, archive_name in files:
                package.write(path, archive_name)
        validate_patch_zip(temp)
        temp.replace(output)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a clean Herfy Client runtime patch"
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_runtime_patch(args.source, args.output, str(args.version).strip())
    print(f"HERFY_RUNTIME_PATCH_OK path={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
