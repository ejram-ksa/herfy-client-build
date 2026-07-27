from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.bootstrap.runtime.update_agent import (  # noqa: E402
    _copy_tree_contents,
    _restore_runtime_snapshot,
    _runtime_manifest_entries,
    _snapshot_runtime,
    _verify_runtime_file_set,
)


def require(path: str, *needles: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise RuntimeError(f"{path} missing contracts: {missing}")


def verify_replacement_behavior() -> None:
    with tempfile.TemporaryDirectory(prefix="herfy-update-contract-") as temp:
        base = Path(temp)
        source = base / "source"
        installed = base / "installed"
        backup = base / "backup"
        for directory in (source, installed):
            directory.mkdir(parents=True)

        source_files = {
            "HerfyClient.exe": b"new-client",
            "HerfyClientUpdateAgent.exe": b"new-agent",
            "version.json": b'{"app_version":"2.18.1"}',
            "resources/theme.qss": b"theme",
            "resources/i18n/ar.json": b"{}",
            "resources/i18n/en.json": b"{}",
        }
        for relative, content in source_files.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (source / "runtime_files.txt").write_text(
            "\n".join(sorted(source_files)) + "\n",
            encoding="utf-8",
        )

        installed_files = {
            "HerfyClient.exe": b"old-client",
            "HerfyClientUpdateAgent.exe": b"old-agent",
            "presentation/logic.py": b"stale-source",
            "ui/shell_cloud.py": b"stale-source",
            "stale-runtime.dll": b"stale-binary",
            "installer_defaults.ini": b"language=ar",
            "installer/terms_and_conditions.txt": b"keep",
            "unins000.exe": b"keep",
        }
        for relative, content in installed_files.items():
            path = installed / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        _snapshot_runtime(installed, backup)
        staged_agent = _copy_tree_contents(source, installed)
        if not staged_agent:
            raise RuntimeError("update agent replacement was not staged")
        _verify_runtime_file_set(source, installed)
        for stale in (
            "presentation/logic.py",
            "ui/shell_cloud.py",
            "stale-runtime.dll",
        ):
            if (installed / stale).exists():
                raise RuntimeError(
                    f"stale installed artifact survived replacement: {stale}"
                )
        for kept in (
            "HerfyClientUpdateAgent.exe",
            "installer_defaults.ini",
            "installer/terms_and_conditions.txt",
            "unins000.exe",
        ):
            if not (installed / kept).is_file():
                raise RuntimeError(f"installer-owned file was removed: {kept}")

        _restore_runtime_snapshot(backup, installed)
        if (installed / "HerfyClient.exe").read_bytes() != b"old-client":
            raise RuntimeError("rollback did not restore the previous executable")
        if not (installed / "presentation/logic.py").is_file():
            raise RuntimeError(
                "rollback did not restore the complete previous snapshot"
            )

        unsafe = base / "unsafe"
        unsafe.mkdir()
        (unsafe / "runtime_files.txt").write_text(
            "HerfyClient.exe\nversion.json\nresources/theme.qss\n../escape.dll\n",
            encoding="utf-8",
        )
        try:
            _runtime_manifest_entries(unsafe)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("unsafe runtime manifest path was accepted")


def main() -> int:
    require(
        "build/installer/pyinstaller/HerfyClient.spec",
        'contents_directory="."',
        "runtime_path_guard.py",
    )
    require(
        "build/installer/HerfyClient_Custom_Installer.iss",
        "CleanupPreviousRuntime",
        "runtime_files.txt",
        "DelTree(AppRoot + '\\presentation'",
        "DeleteFile(AppRoot + '\\shell_cloud.py'",
        "if Value = '' then",
        "StringChangeEx(RelativePath, '/', '\\', True)",
    )
    require(
        "runtime/bootstrap/runtime/update_agent.py",
        "_verify_updated_runtime",
        "HERFY_UPDATE_RUNTIME_SELF_CHECK_OK",
        "runtime_files.txt",
        "--self-check",
    )
    require(
        "build/release/build_runtime_patch.py",
        "REQUIRED_PATCH_FILES",
        "validate_patch_zip",
    )
    require(
        "runtime/domain/update_archive.py",
        '"runtime_files.txt"',
        "Case-insensitive duplicate patch member rejected",
    )
    require(
        "build/installer/BUILD_CUSTOM_INSTALLER.ps1",
        "build_runtime_manifest.py",
        "HERFY_RUNTIME_MANIFEST_OK",
        "Invoke-FrozenAgentPatchSmoke",
        "HERFY_UPDATE_AGENT_VALIDATION",
        "--validation-no-restart",
        "Invoke-InstallerSmoke",
        "HERFY_INSTALLER_RUNTIME_SMOKE_OK",
        "Silent uninstaller smoke test",
    )
    require(
        "build/release/WINDOWS_CODE_SIGNING.ps1",
        "HERFY_REQUIRE_CODE_SIGNING",
        "Get-AuthenticodeSignature",
        "TimeStamperCertificate",
        "'/fd', 'SHA256'",
        "'/td', 'SHA256'",
    )
    require(
        "build/release/BUILD_AND_PUBLISH.ps1",
        "HERFY_EDITABLE_SOURCE_PACKAGE_OK",
        "editable_source = [ordered]",
        "HerfyTrackingSystem_${Version}_WINDOWS_DESKTOP_SOURCE.zip",
        "$ReleaseIsProduction = $SigningPassed",
        "available = $ReleaseIsProduction",
    )
    require(
        "build/release/verify_deployed_release.py",
        "HERFY_DEPLOYED_RELEASE_OK",
        "Cross-origin redirect was rejected",
        "Installer SHA-256 mismatch",
        '"latest.json", "manifest.json", "upgrade-plan.json"',
    )
    require(
        "00_VERIFY_DEPLOYED_RELEASE.cmd",
        "verify_deployed_release.py",
    )
    verify_replacement_behavior()
    print(
        "HERFY_UPDATE_INSTALL_CONTRACT_OK "
        "stale_source=removed rollback=complete self_check=required root_runtime=flat"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
