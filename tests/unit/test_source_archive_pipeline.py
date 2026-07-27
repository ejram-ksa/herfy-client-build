from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from build.release.build_source_archive import build_source_archive
from build.release.verify_publish_bundle import verify_publish_bundle
from build.release.verify_source_archive import verify_source_archive

ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_sidecar(path: Path) -> None:
    Path(f"{path}.sha256").write_text(
        f"{_sha256(path)}  {path.name}\n",
        encoding="utf-8",
    )


def test_source_archive_is_deterministic_and_matches_the_source_tree(tmp_path: Path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first_report = build_source_archive(ROOT, first)
    second_report = build_source_archive(ROOT, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_report["files"] == second_report["files"]
    verified = verify_source_archive(first, source_root=ROOT)
    assert verified["files"] == first_report["files"]
    assert verified["archive_sha256"] == _sha256(first)


def test_source_archive_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", b"unsafe")
    with pytest.raises(RuntimeError, match="Unsafe ZIP member path"):
        verify_source_archive(archive)


def test_source_archive_rejects_symbolic_link_members(tmp_path: Path):
    archive = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(info, b"target")
    with pytest.raises(RuntimeError, match="Symbolic-link ZIP member"):
        verify_source_archive(archive)


def _create_nonproduction_publish_bundle(tmp_path: Path) -> tuple[Path, str]:
    version = "2.18.1"
    root = tmp_path / "publish"
    packages = root / "updates" / "packages"
    version_root = root / "updates" / version
    source_root = root / "source"
    validation_root = root / "validation"
    for directory in (packages, version_root, source_root, validation_root):
        directory.mkdir(parents=True, exist_ok=True)

    setup_name = f"HerfyClient_Setup_{version}.exe"
    patch_name = f"HerfyClient_{version}_remote_update.zip"
    source_name = f"HerfyTrackingSystem_{version}_WINDOWS_DESKTOP_SOURCE.zip"
    setup = packages / setup_name
    patch = packages / patch_name
    source = source_root / source_name
    setup.write_bytes(b"MZ" + b"client" * 200)
    patch.write_bytes(b"PK\x03\x04" + b"patch" * 200)

    source_tree = tmp_path / "source-tree"
    source_tree.mkdir()
    (source_tree / "main.py").write_text("print('ok')\n", encoding="utf-8")
    build_source_archive(source_tree, source)

    (version_root / setup_name).write_bytes(setup.read_bytes())
    (version_root / patch_name).write_bytes(patch.read_bytes())
    for artifact in (
        setup,
        patch,
        source,
        version_root / setup_name,
        version_root / patch_name,
    ):
        _write_sidecar(artifact)

    metadata = {
        "latest": version,
        "version": version,
        "latest_version": version,
        "target_version": version,
        "available": False,
        "update_available": False,
        "mandatory": False,
        "force_update": False,
        "current_supported": True,
        "package_name": "",
        "setup_package": "",
        "url": "",
        "installer_url": "",
        "download_url": "",
        "sha256": "",
        "setup_sha256": "",
        "size": 0,
        "setup_size": 0,
        "patch_package": "",
        "patch_download_url": "",
        "patch_sha256": "",
        "patch_size": 0,
        "patches": [],
    }
    for name in ("latest.json", "manifest.json", "upgrade-plan.json"):
        (root / "updates" / name).write_text(
            json.dumps(metadata), encoding="utf-8"
        )

    (validation_root / "signing-status.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "skipped",
                "required": False,
                "artifacts": [],
            }
        ),
        encoding="utf-8",
    )
    release = {
        "schema_version": 3,
        "version": version,
        "production": False,
        "release_gate": "windows-build-validated-code-signing-not-verified",
        "installer": {
            "file": setup_name,
            "sha256": _sha256(setup),
            "size": setup.stat().st_size,
        },
        "validation_patch": {
            "file": patch_name,
            "sha256": _sha256(patch),
            "size": patch.stat().st_size,
            "advertised": False,
        },
        "editable_source": {
            "file": source_name,
            "sha256": _sha256(source),
            "size": source.stat().st_size,
        },
        "validation": {"code_signing": "not_verified"},
        "code_signing": {
            "status": "skipped",
            "required": False,
            "certificate_thumbprint": "",
            "status_file": "validation/signing-status.json",
            "signed_artifacts": [],
        },
    }
    (root / "release.json").write_text(json.dumps(release), encoding="utf-8")
    return root, version


def test_publish_bundle_verifier_accepts_a_consistent_nonproduction_bundle(
    tmp_path: Path,
):
    root, version = _create_nonproduction_publish_bundle(tmp_path)
    result = verify_publish_bundle(
        root,
        expected_version=version,
        verify_source_metadata=False,
    )
    assert result["version"] == version
    assert result["production"] is False


def test_publish_bundle_requires_canonical_names_in_the_version_directory(
    tmp_path: Path,
):
    root, version = _create_nonproduction_publish_bundle(tmp_path)
    canonical = root / "updates" / version / f"HerfyClient_Setup_{version}.exe"
    canonical.rename(root / "updates" / version / f"HerfyClientSetup-{version}.exe")
    with pytest.raises(RuntimeError, match="versioned installer is missing"):
        verify_publish_bundle(
            root,
            expected_version=version,
            verify_source_metadata=False,
        )


def test_release_script_blocks_implicit_nonproduction_target_copy():
    script = (ROOT / "build" / "release" / "BUILD_AND_PUBLISH.ps1").read_text(
        encoding="utf-8"
    )
    assert "AllowNonProductionPublishTarget" in script
    assert "Refusing to copy a non-production bundle to PublishTarget" in script
    assert "verify_publish_bundle.py" in script
    assert "build_source_archive.py" in script
    assert "verify_source_archive.py" in script
    assert "Copy-Item -Force $PublishedSetup (Join-Path $VersionRoot $SetupName)" in script
    assert "Copy-Item -Force $PublishedPatch (Join-Path $VersionRoot $PatchName)" in script

def _promote_bundle_to_signed_production(
    root: Path,
    version: str,
    *,
    mandatory: bool,
) -> None:
    release_path = root / "release.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    setup_name = str(release["installer"]["file"])
    setup_hash = str(release["installer"]["sha256"])
    setup_size = int(release["installer"]["size"])

    metadata_path = root / "updates" / "latest.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update(
        {
            "available": True,
            "update_available": True,
            "mandatory": mandatory,
            "force_update": mandatory,
            "current_supported": not mandatory,
            "package_name": setup_name,
            "setup_package": setup_name,
            "url": f"/updates/packages/{setup_name}",
            "installer_url": f"/updates/packages/{setup_name}",
            "download_url": f"/updates/packages/{setup_name}",
            "sha256": setup_hash,
            "setup_sha256": setup_hash,
            "size": setup_size,
            "setup_size": setup_size,
        }
    )
    for name in ("latest.json", "manifest.json", "upgrade-plan.json"):
        (root / "updates" / name).write_text(
            json.dumps(metadata), encoding="utf-8"
        )

    artifacts = [
        {
            "label": label,
            "status": "passed",
            "timestamped": True,
        }
        for label in (
            "client-executable",
            "update-agent-executable",
            "installer",
        )
    ]
    signing = {
        "schema_version": 1,
        "status": "passed",
        "required": True,
        "certificate_thumbprint": "A" * 40,
        "artifacts": artifacts,
    }
    (root / "validation" / "signing-status.json").write_text(
        json.dumps(signing), encoding="utf-8"
    )

    release["production"] = True
    release["release_gate"] = "windows-build-smoke-and-authenticode-validated"
    release["validation"]["code_signing"] = "passed"
    release["code_signing"] = {
        "status": "passed",
        "required": True,
        "certificate_thumbprint": "A" * 40,
        "status_file": "validation/signing-status.json",
        "signed_artifacts": [item["label"] for item in artifacts],
    }
    release["update_enforcement"] = "mandatory" if mandatory else "optional"
    release_path.write_text(json.dumps(release), encoding="utf-8")


@pytest.mark.parametrize("mandatory", [False, True])
def test_publish_bundle_accepts_explicit_optional_or_mandatory_production_policy(
    tmp_path: Path,
    mandatory: bool,
):
    root, version = _create_nonproduction_publish_bundle(tmp_path)
    _promote_bundle_to_signed_production(root, version, mandatory=mandatory)
    result = verify_publish_bundle(
        root,
        expected_version=version,
        verify_source_metadata=False,
    )
    assert result["production"] is True


def test_publish_bundle_rejects_inconsistent_production_force_policy(tmp_path: Path):
    root, version = _create_nonproduction_publish_bundle(tmp_path)
    _promote_bundle_to_signed_production(root, version, mandatory=False)
    metadata_path = root / "updates" / "latest.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["force_update"] = True
    for name in ("latest.json", "manifest.json", "upgrade-plan.json"):
        (root / "updates" / name).write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(RuntimeError, match="force_update must match"):
        verify_publish_bundle(
            root,
            expected_version=version,
            verify_source_metadata=False,
        )



def test_source_manifest_is_reproducible_for_identical_inputs(tmp_path: Path, monkeypatch):
    from build.release.source_manifest import write_source_metadata

    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "version.json").write_text(
        json.dumps(
            {
                "app_version": "1.0.0",
                "package_name": "sample-source",
                "artifact_kind": "editable-source",
                "production": False,
            }
        ),
        encoding="utf-8",
    )
    (source_root / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)

    first = write_source_metadata(
        pytest_passed=1,
        validator_results={"validator": "passed"},
        quality_results={"ruff": "passed", "black": "passed"},
        platform="win32",
        root=source_root,
    )
    first_bytes = (source_root / "PACKAGE_MANIFEST.json").read_bytes()
    second = write_source_metadata(
        pytest_passed=1,
        validator_results={"validator": "passed"},
        quality_results={"ruff": "passed", "black": "passed"},
        platform="win32",
        root=source_root,
    )
    assert first == second
    assert first_bytes == (source_root / "PACKAGE_MANIFEST.json").read_bytes()
    assert first["generated_at_utc"] == "2000-01-01T00:00:00+00:00"
