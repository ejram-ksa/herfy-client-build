from __future__ import annotations

import argparse
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.domain.update_archive import (  # noqa: E402
    RUNTIME_MANIFEST_NAME,
    is_forbidden_patch_artifact,
    validate_archive_name,
    validate_runtime_manifest_names,
)


FORBIDDEN_PARTS = {"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}
MANIFEST_NAME = RUNTIME_MANIFEST_NAME


def build_manifest(runtime_root: Path) -> Path:
    root = runtime_root.resolve()
    if not root.is_dir():
        raise RuntimeError(f"Runtime directory does not exist: {root}")
    entries: list[str] = []
    folded_entries: set[str] = set()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Symbolic links are forbidden in runtime: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.name == MANIFEST_NAME:
            continue
        archive_name = PurePosixPath(*relative.parts).as_posix()
        parts = validate_archive_name(archive_name)
        if is_forbidden_patch_artifact(archive_name, parts):
            raise RuntimeError(
                f"Source/cache artifact found in frozen runtime: {relative}"
            )
        folded = archive_name.casefold()
        if folded in folded_entries:
            raise RuntimeError(
                f"Case-insensitive duplicate path found in frozen runtime: {relative}"
            )
        folded_entries.add(folded)
        entries.append(archive_name)

    # Apply the same manifest policy used by the frozen update agent before the
    # file is written or packed into a remote update archive.
    validate_runtime_manifest_names(entries)
    output = root / MANIFEST_NAME
    output.write_text("\n".join(entries) + "\n", encoding="utf-8", newline="\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    args = parser.parse_args()
    output = build_manifest(args.runtime)
    print(f"HERFY_RUNTIME_MANIFEST_OK path={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
