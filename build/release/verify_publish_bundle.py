from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .verify_source_archive import verify_source_archive
except ImportError:  # Script execution from build/release.
    from verify_source_archive import verify_source_archive

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_SIGNED_LABELS = {
    "client-executable",
    "update-agent-executable",
    "installer",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Required JSON file is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def _safe_relative(value: str, *, label: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if (
        not text
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or ":" in pure.parts[0]
    ):
        raise RuntimeError(f"{label} is not a safe relative path: {value!r}")
    return pure.as_posix()


def _verify_artifact(path: Path, *, expected_hash: str, expected_size: int, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"{label} is missing: {path}")
    actual_size = path.stat().st_size
    actual_hash = _sha256(path)
    if actual_size != int(expected_size):
        raise RuntimeError(
            f"{label} size mismatch: expected={expected_size} actual={actual_size}"
        )
    if actual_hash != str(expected_hash).lower():
        raise RuntimeError(
            f"{label} SHA-256 mismatch: expected={expected_hash} actual={actual_hash}"
        )


def _verify_sidecar(artifact: Path, expected_hash: str) -> None:
    sidecar = Path(f"{artifact}.sha256")
    if not sidecar.is_file():
        raise RuntimeError(f"Checksum sidecar is missing: {sidecar}")
    line = sidecar.read_text(encoding="utf-8").strip()
    expected = f"{expected_hash.lower()}  {artifact.name}"
    if line != expected:
        raise RuntimeError(
            f"Checksum sidecar mismatch: {sidecar}; expected={expected!r} actual={line!r}"
        )


def verify_publish_bundle(
    publish_root: Path,
    *,
    expected_version: str | None = None,
    verify_source_metadata: bool = True,
) -> dict[str, object]:
    root = Path(publish_root).resolve()
    if not root.is_dir():
        raise RuntimeError(f"Publish root does not exist: {root}")

    release = _load_json(root / "release.json")
    version = str(release.get("version") or "").strip()
    if not version:
        raise RuntimeError("release.json does not contain a version")
    if expected_version is not None and version != str(expected_version).strip():
        raise RuntimeError(
            f"Release version mismatch: expected={expected_version} actual={version}"
        )
    if int(release.get("schema_version") or 0) != 3:
        raise RuntimeError("Unsupported release.json schema version")

    metadata_paths = [
        root / "updates" / "latest.json",
        root / "updates" / "manifest.json",
        root / "updates" / "upgrade-plan.json",
    ]
    metadata_documents = [_load_json(path) for path in metadata_paths]
    if not all(document == metadata_documents[0] for document in metadata_documents[1:]):
        raise RuntimeError("Update metadata files do not contain identical documents")
    metadata = metadata_documents[0]
    for key in ("latest", "version", "latest_version", "target_version"):
        if str(metadata.get(key) or "") != version:
            raise RuntimeError(f"Update metadata version mismatch in field: {key}")

    production = bool(release.get("production"))
    expected_gate = (
        "windows-build-smoke-and-authenticode-validated"
        if production
        else "windows-build-validated-code-signing-not-verified"
    )
    if str(release.get("release_gate") or "") != expected_gate:
        raise RuntimeError("release.json has an inconsistent release gate")

    installer = release.get("installer") or {}
    patch = release.get("validation_patch") or {}
    source = release.get("editable_source") or {}
    if not all(isinstance(value, dict) for value in (installer, patch, source)):
        raise RuntimeError("release.json artifact descriptors must be objects")

    setup_name = _safe_relative(str(installer.get("file") or ""), label="installer file")
    patch_name = _safe_relative(str(patch.get("file") or ""), label="patch file")
    source_name = _safe_relative(str(source.get("file") or ""), label="source file")
    setup_hash = str(installer.get("sha256") or "").lower()
    patch_hash = str(patch.get("sha256") or "").lower()
    source_hash = str(source.get("sha256") or "").lower()
    for label, value in (
        ("installer", setup_hash),
        ("patch", patch_hash),
        ("source", source_hash),
    ):
        if not _SHA256.fullmatch(value):
            raise RuntimeError(f"{label} descriptor has an invalid SHA-256")

    packages = root / "updates" / "packages"
    version_root = root / "updates" / version
    setup_path = packages / setup_name
    patch_path = packages / patch_name
    source_path = root / "source" / source_name
    _verify_artifact(
        setup_path,
        expected_hash=setup_hash,
        expected_size=int(installer.get("size") or 0),
        label="installer",
    )
    _verify_artifact(
        patch_path,
        expected_hash=patch_hash,
        expected_size=int(patch.get("size") or 0),
        label="validation patch",
    )
    _verify_artifact(
        source_path,
        expected_hash=source_hash,
        expected_size=int(source.get("size") or 0),
        label="editable source",
    )
    for artifact in (setup_path, patch_path, source_path):
        expected_hash = _sha256(artifact)
        _verify_sidecar(artifact, expected_hash)

    for artifact, expected_hash, expected_size, label in (
        (version_root / setup_name, setup_hash, int(installer.get("size") or 0), "versioned installer"),
        (version_root / patch_name, patch_hash, int(patch.get("size") or 0), "versioned validation patch"),
    ):
        _verify_artifact(
            artifact,
            expected_hash=expected_hash,
            expected_size=expected_size,
            label=label,
        )
        _verify_sidecar(artifact, expected_hash)

    if bool(patch.get("advertised")):
        raise RuntimeError("Validation patch must not be advertised")
    if any(metadata.get(key) not in {"", None} for key in ("patch_package", "patch_download_url", "patch_sha256")):
        raise RuntimeError("Validation patch leaked into public update metadata")
    if int(metadata.get("patch_size") or 0) != 0 or list(metadata.get("patches") or []):
        raise RuntimeError("Validation patch metadata must remain empty")

    if production:
        for key in ("available", "update_available"):
            if metadata.get(key) is not True:
                raise RuntimeError(f"Production update metadata must set {key}=true")
        mandatory = metadata.get("mandatory")
        force_update = metadata.get("force_update")
        current_supported = metadata.get("current_supported")
        if not isinstance(mandatory, bool) or not isinstance(force_update, bool):
            raise RuntimeError(
                "Production mandatory and force_update values must be booleans"
            )
        if mandatory != force_update:
            raise RuntimeError(
                "Production force_update must match the mandatory update policy"
            )
        if current_supported is not (not mandatory):
            raise RuntimeError(
                "Production current_supported must be the inverse of mandatory"
            )
        expected_url = f"/updates/packages/{setup_name}"
        for key in ("package_name", "setup_package"):
            if str(metadata.get(key) or "") != setup_name:
                raise RuntimeError(f"Production metadata has an invalid {key}")
        for key in ("url", "installer_url", "download_url"):
            if str(metadata.get(key) or "") != expected_url:
                raise RuntimeError(f"Production metadata has an invalid {key}")
        for key in ("sha256", "setup_sha256"):
            if str(metadata.get(key) or "").lower() != setup_hash:
                raise RuntimeError(f"Production metadata has an invalid {key}")
        for key in ("size", "setup_size"):
            if int(metadata.get(key) or 0) != int(installer.get("size") or 0):
                raise RuntimeError(f"Production metadata has an invalid {key}")
    else:
        for key in ("available", "update_available", "mandatory", "force_update"):
            if metadata.get(key) is not False:
                raise RuntimeError(f"Non-production metadata must set {key}=false")
        if metadata.get("current_supported") is not True:
            raise RuntimeError("Non-production metadata must set current_supported=true")
        for key in (
            "package_name",
            "setup_package",
            "url",
            "installer_url",
            "download_url",
            "sha256",
            "setup_sha256",
        ):
            if metadata.get(key) not in {"", None}:
                raise RuntimeError(f"Non-production metadata must not advertise {key}")
        for key in ("size", "setup_size"):
            if int(metadata.get(key) or 0) != 0:
                raise RuntimeError(f"Non-production metadata must set {key}=0")

    signing = _load_json(root / "validation" / "signing-status.json")
    if int(signing.get("schema_version") or 0) != 1:
        raise RuntimeError("Unsupported signing-status.json schema version")
    release_signing = release.get("code_signing") or {}
    if not isinstance(release_signing, dict):
        raise RuntimeError("release.json code_signing must be an object")
    if str(release_signing.get("status_file") or "") != "validation/signing-status.json":
        raise RuntimeError("release.json references an invalid signing-status path")
    if str(release_signing.get("status") or "") != str(signing.get("status") or ""):
        raise RuntimeError("release.json code-signing status does not match signing-status.json")
    if bool(release_signing.get("required")) != bool(signing.get("required")):
        raise RuntimeError("release.json code-signing requirement does not match signing-status.json")
    if str(release_signing.get("certificate_thumbprint") or "").strip().lower() != str(
        signing.get("certificate_thumbprint") or ""
    ).strip().lower():
        raise RuntimeError("release.json certificate thumbprint does not match signing-status.json")
    if production:
        if str(signing.get("status") or "") != "passed":
            raise RuntimeError("Production release requires passed code signing")
        labels = {
            str(item.get("label") or "")
            for item in list(signing.get("artifacts") or [])
            if isinstance(item, dict)
            and str(item.get("status") or "") == "passed"
            and bool(item.get("timestamped"))
        }
        if not _REQUIRED_SIGNED_LABELS.issubset(labels):
            raise RuntimeError("Production release has incomplete signed artifacts")
        release_labels = {
            str(value or "") for value in list(release_signing.get("signed_artifacts") or [])
        }
        if not _REQUIRED_SIGNED_LABELS.issubset(release_labels):
            raise RuntimeError("release.json does not list all required signed artifacts")
        if str((release.get("validation") or {}).get("code_signing") or "") != "passed":
            raise RuntimeError("Production release validation does not record code signing")
    else:
        if str(signing.get("status") or "") not in {"skipped", "passed"}:
            raise RuntimeError("Non-production signing status is invalid")
        if str((release.get("validation") or {}).get("code_signing") or "") != "not_verified":
            raise RuntimeError("Non-production release must record code_signing=not_verified")

    source_report = verify_source_archive(
        source_path,
        verify_metadata=verify_source_metadata,
    )
    return {
        "publish_root": str(root),
        "version": version,
        "production": production,
        "installer_sha256": setup_hash,
        "patch_sha256": patch_hash,
        "source_sha256": source_hash,
        "source_files": source_report["files"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a complete Windows publish bundle.")
    parser.add_argument("publish_root", type=Path)
    parser.add_argument("--expected-version")
    parser.add_argument("--skip-source-metadata", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify_publish_bundle(
        args.publish_root,
        expected_version=args.expected_version,
        verify_source_metadata=not args.skip_source_metadata,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        "HERFY_PUBLISH_BUNDLE_OK "
        f"version={report['version']} "
        f"production={str(report['production']).lower()} "
        f"source_files={report['source_files']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
