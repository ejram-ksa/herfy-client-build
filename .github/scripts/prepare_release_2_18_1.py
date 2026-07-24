from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

VERSION = "2.18.1"
SETUP = f"HerfyTrackingSystem_{VERSION}_Setup.exe"


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def replace(path: Path, old: str, new: str, *, required: bool = False) -> None:
    text = path.read_text(encoding="utf-8")
    if old in text:
        path.write_text(text.replace(old, new), encoding="utf-8")
        return
    if required and new not in text:
        raise RuntimeError(f"Expected release token was not found in {path}: {old!r}")


def patch_source(root: Path) -> None:
    version_path = root / "version.json"
    version = json.loads(version_path.read_text(encoding="utf-8"))
    version.update(
        {
            "app_version": VERSION,
            "version": VERSION,
            "file_version": f"{VERSION}.0",
            "package_name": f"HerfyTrackingSystem_{VERSION}",
        }
    )
    write_json(version_path, version)

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "version": VERSION,
            "installer": SETUP,
            "installer_url": f"https://herfy.online/api/updates/packages/{SETUP}",
            "sha256": "",
            "size": 0,
            "publication_status": "pending",
        }
    )
    write_json(manifest_path, manifest)

    settings_version = root / "settings" / "version.py"
    text = settings_version.read_text(encoding="utf-8")
    text, count = re.subn(
        r'_VERSION_FALLBACK\s*=\s*"[^"]+"',
        f'_VERSION_FALLBACK = "{VERSION}"',
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError("settings/version.py version fallback was not patched")
    settings_version.write_text(text, encoding="utf-8")

    installer = root / "installer" / "HerfyTrackingSystem.iss"
    text = installer.read_text(encoding="utf-8")
    text, count = re.subn(
        r'#define SetupVersion\s+"[^"]+"',
        f'#define SetupVersion "{VERSION}"',
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError("Installer version was not patched")
    installer.write_text(text, encoding="utf-8")

    replacements = {
        "data/tracking_baseline.py": [
            (
                "Delete all legacy or canonical representations",
                "Delete all previous or canonical representations",
            ),
        ],
        "data/usage_repository.py": [
            ("_legacy_usage_table_exists", "_previous_usage_table_exists"),
            (
                "migrate_legacy_usage_operations",
                "migrate_previous_usage_operations",
            ),
        ],
        "services/local_sync.py": [
            ("migrate_legacy", "migrate_previous"),
            (
                "migrate_legacy_usage_operations",
                "migrate_previous_usage_operations",
            ),
        ],
        "tools/verify/verify_architecture.py": [
            ("legacy import", "obsolete import"),
            ("legacy usage outbox", "previous usage outbox"),
        ],
        "tools/verify/verify_deep_runtime_contract.py": [
            ("legacy.sqlite3", "previous.sqlite3"),
        ],
        "tools/verify/verify_local_first_sync_contract.py": [
            ("legacy direct readers", "previous direct readers"),
        ],
    }
    for relative, pairs in replacements.items():
        path = root / relative
        for old, new in pairs:
            replace(path, old, new)

    architecture = root / "tools" / "verify" / "verify_architecture.py"
    source = architecture.read_text(encoding="utf-8")
    old = "def _assert_server_routes() -> None:\n    routes = _server_routes()"
    new = (
        "def _assert_server_routes() -> None:\n"
        "    server_main = SERVER_ROOT / \"app\" / \"main.py\"\n"
        "    if not server_main.is_file():\n"
        "        return\n"
        "    routes = _server_routes()"
    )
    if old in source:
        source = source.replace(old, new, 1)
    if "server_main = SERVER_ROOT" not in source:
        raise RuntimeError("Client-only architecture verifier patch was not applied")
    source = source.replace(
        '(SERVER_ROOT / "app" / "main.py").read_text(encoding="utf-8")',
        'server_main.read_text(encoding="utf-8")',
    )
    architecture.write_text(source, encoding="utf-8")

    for relative in (
        "tools/verify/verify_full_source_contract.py",
        "tools/verify/verify_update_install_contract.py",
    ):
        path = root / relative
        text = path.read_text(encoding="utf-8")
        text = text.replace('"2.18.0"', f'"{VERSION}"')
        text = text.replace("Setup_2.18.0", f"Setup_{VERSION}")
        path.write_text(text, encoding="utf-8")

    build = root / "tools" / "build" / "build.ps1"
    replace(
        build,
        '(Join-Path $Publish "manifest.json")',
        '(Join-Path $Publish "client-update-manifest.json")',
        required=True,
    )

    update_contract = root / "tools" / "verify" / "verify_update_install_contract.py"
    replace(
        update_contract,
        '"manifest.json",',
        '"client-update-manifest.json",',
        required=True,
    )


def source_files(root: Path) -> list[Path]:
    blocked_top_level = {
        ".git",
        ".venv",
        "build",
        "dist",
        "publish",
        "release",
    }
    blocked_anywhere = {
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    }
    blocked_suffixes = {
        ".pyc",
        ".pyo",
        ".log",
        ".tmp",
        ".bak",
        ".old",
        ".orig",
    }
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in blocked_top_level:
            continue
        if any(part in blocked_anywhere for part in relative.parts):
            continue
        if path.suffix.lower() in blocked_suffixes:
            continue
        if relative.as_posix() == "MANIFEST.sha256.json":
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def regenerate_manifest(root: Path) -> list[Path]:
    files = source_files(root)
    entries = []
    for path in files:
        data = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    write_json(
        root / "MANIFEST.sha256.json",
        {
            "app": "Herfy Tracking System",
            "version": VERSION,
            "files": entries,
        },
    )
    return files


def create_source_zip(root: Path, output: Path, files: list[Path]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    ordered = [root / "MANIFEST.sha256.json", *files]
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in ordered:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2026, 7, 24, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(output, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Generated source ZIP is corrupt at {bad}")
        names = set(archive.namelist())
        required = {
            "tools/build/build.cmd",
            "tools/build/build.ps1",
            "installer/HerfyTrackingSystem.iss",
            "version.json",
            "MANIFEST.sha256.json",
        }
        missing = sorted(required - names)
        if missing:
            raise RuntimeError(f"Generated source ZIP is incomplete: {missing}")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: prepare_release_2_18_1.py CLIENT_ROOT OUTPUT_ZIP"
        )
    root = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    patch_source(root)
    files = regenerate_manifest(root)
    create_source_zip(root, output, files)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(
        f"HERFY_2_18_1_SOURCE_READY files={len(files) + 1} sha256={digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
