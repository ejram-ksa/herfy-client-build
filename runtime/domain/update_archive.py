from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable

REQUIRED_PATCH_FILES = frozenset(
    {
        "HerfyClient.exe",
        "HerfyClientUpdateAgent.exe",
        "version.json",
        "runtime_files.txt",
        "resources/theme.qss",
        "resources/i18n/ar.json",
        "resources/i18n/en.json",
    }
)
FORBIDDEN_PATCH_SUFFIXES = frozenset({".py", ".pyc", ".pyo"})
FORBIDDEN_PATCH_PARTS = frozenset(
    {"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}
)
WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)
WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"|?*')
MAX_WINDOWS_COMPONENT_LENGTH = 255
MAX_RUNTIME_RELATIVE_PATH_LENGTH = 220
MAX_PATCH_MEMBERS = 10_000
MAX_PATCH_FILE_SIZE = 1024 * 1024 * 1024
MAX_PATCH_TOTAL_SIZE = 2 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 500
MAX_RUNTIME_MANIFEST_SIZE = 2 * 1024 * 1024
RUNTIME_MANIFEST_NAME = "runtime_files.txt"
REQUIRED_RUNTIME_MANIFEST_FILES = REQUIRED_PATCH_FILES - {RUNTIME_MANIFEST_NAME}


def validate_archive_name(archive_name: str) -> tuple[str, ...]:
    name = str(archive_name or "").replace("\\", "/")
    if name != name.strip():
        raise RuntimeError(
            f"Patch member has leading or trailing whitespace: {archive_name}"
        )
    if not name or name.endswith("/"):
        return ()
    raw_parts = tuple(name.split("/"))
    if any(part in {"", "."} for part in raw_parts):
        raise RuntimeError(f"Non-canonical patch member path rejected: {archive_name}")
    pure = PurePosixPath(name)
    if name.startswith("/") or ".." in pure.parts:
        raise RuntimeError(f"Unsafe patch member path rejected: {archive_name}")
    if len(name) > MAX_RUNTIME_RELATIVE_PATH_LENGTH:
        raise RuntimeError(f"Patch member path is too long: {archive_name}")
    for part in raw_parts:
        if (
            len(part) > MAX_WINDOWS_COMPONENT_LENGTH
            or part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or any(character in WINDOWS_INVALID_FILENAME_CHARS for character in part)
            or part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
        ):
            raise RuntimeError(
                f"Windows-incompatible patch member rejected: {archive_name}"
            )
    return raw_parts


def is_forbidden_patch_artifact(name: str, parts: Iterable[str] | None = None) -> bool:
    normalized_parts = tuple(parts or validate_archive_name(name))
    suffix = PurePosixPath(name).suffix.casefold()
    return suffix in FORBIDDEN_PATCH_SUFFIXES or bool(
        set(normalized_parts) & FORBIDDEN_PATCH_PARTS
    )


def validate_patch_members(members: Iterable[zipfile.ZipInfo]) -> set[str]:
    member_list = list(members)
    if len(member_list) > MAX_PATCH_MEMBERS:
        raise RuntimeError(
            f"Patch package contains too many members: {len(member_list)}"
        )
    names: set[str] = set()
    folded_names: set[str] = set()
    total_size = 0
    for member in member_list:
        name = member.filename.replace("\\", "/")
        parts = validate_archive_name(name)
        if not parts:
            continue
        if stat.S_ISLNK((member.external_attr >> 16) & 0xFFFF):
            raise RuntimeError(
                f"Symbolic-link patch member rejected: {member.filename}"
            )
        if member.file_size > MAX_PATCH_FILE_SIZE:
            raise RuntimeError(f"Oversized patch member rejected: {member.filename}")
        total_size += member.file_size
        if total_size > MAX_PATCH_TOTAL_SIZE:
            raise RuntimeError(
                f"Patch package expands beyond the allowed size: {total_size}"
            )
        if (
            member.file_size > 1024 * 1024
            and member.file_size / max(1, member.compress_size) > MAX_COMPRESSION_RATIO
        ):
            raise RuntimeError(
                f"Suspicious compression ratio rejected: {member.filename}"
            )
        if is_forbidden_patch_artifact(name, parts):
            raise RuntimeError(f"Source/cache artifact rejected from patch: {name}")
        folded = name.casefold()
        if folded in folded_names:
            raise RuntimeError(
                f"Case-insensitive duplicate patch member rejected: {member.filename}"
            )
        names.add(name)
        folded_names.add(folded)
    missing = sorted(REQUIRED_PATCH_FILES - names)
    if missing:
        raise RuntimeError(
            f"Patch package is incomplete. Missing: {', '.join(missing)}"
        )
    return names



def validate_runtime_manifest_names(lines: Iterable[str]) -> set[str]:
    """Validate and canonicalize the frozen runtime manifest.

    The manifest is a security boundary used to delete stale files during an
    update.  It therefore follows the same Windows path policy as the archive
    itself and rejects ambiguous case-insensitive names.
    """
    names: set[str] = set()
    folded_names: set[str] = set()
    for raw_line in lines:
        raw = str(raw_line)
        if not raw.strip():
            continue
        if raw != raw.strip():
            raise RuntimeError(
                f"Runtime manifest entry has leading or trailing whitespace: {raw!r}"
            )
        name = raw.replace("\\", "/")
        parts = validate_archive_name(name)
        if not parts:
            raise RuntimeError(f"Runtime manifest directory entry rejected: {raw}")
        if name.casefold() == RUNTIME_MANIFEST_NAME.casefold():
            raise RuntimeError(
                f"Runtime manifest cannot declare itself: {RUNTIME_MANIFEST_NAME}"
            )
        if is_forbidden_patch_artifact(name, parts):
            raise RuntimeError(
                f"Source/cache artifact rejected from runtime manifest: {name}"
            )
        folded = name.casefold()
        if folded in folded_names:
            raise RuntimeError(
                f"Case-insensitive duplicate runtime manifest entry rejected: {name}"
            )
        names.add(name)
        folded_names.add(folded)
    missing = sorted(REQUIRED_RUNTIME_MANIFEST_FILES - names)
    if missing:
        raise RuntimeError(
            f"Runtime manifest is incomplete. Missing: {', '.join(missing)}"
        )
    return names

def validate_patch_zip(patch_zip: str | Path) -> None:
    path = Path(patch_zip)
    if not path.is_file() or path.suffix.casefold() != ".zip":
        raise RuntimeError(f"Patch package is not a zip file: {path}")
    with zipfile.ZipFile(path, "r") as package:
        bad = package.testzip()
        if bad:
            raise RuntimeError(f"Patch package contains a corrupt file: {bad}")
        archive_names = validate_patch_members(package.infolist())
        manifest_info = package.getinfo(RUNTIME_MANIFEST_NAME)
        if manifest_info.file_size > MAX_RUNTIME_MANIFEST_SIZE:
            raise RuntimeError(
                f"Runtime manifest is too large: {manifest_info.file_size}"
            )
        try:
            manifest_text = package.read(manifest_info).decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise RuntimeError("Runtime manifest is not valid UTF-8") from exc
        manifest_names = validate_runtime_manifest_names(manifest_text.splitlines())
        packaged_runtime_names = archive_names - {RUNTIME_MANIFEST_NAME}
        missing_from_manifest = sorted(packaged_runtime_names - manifest_names)
        absent_from_package = sorted(manifest_names - packaged_runtime_names)
        if missing_from_manifest or absent_from_package:
            raise RuntimeError(
                "Runtime manifest does not match patch contents. "
                f"undeclared={missing_from_manifest[:10]} "
                f"absent={absent_from_package[:10]}"
            )


__all__ = [
    "FORBIDDEN_PATCH_PARTS",
    "FORBIDDEN_PATCH_SUFFIXES",
    "MAX_PATCH_FILE_SIZE",
    "MAX_PATCH_MEMBERS",
    "MAX_PATCH_TOTAL_SIZE",
    "MAX_RUNTIME_MANIFEST_SIZE",
    "REQUIRED_PATCH_FILES",
    "REQUIRED_RUNTIME_MANIFEST_FILES",
    "RUNTIME_MANIFEST_NAME",
    "is_forbidden_patch_artifact",
    "validate_archive_name",
    "validate_patch_members",
    "validate_runtime_manifest_names",
    "validate_patch_zip",
]
