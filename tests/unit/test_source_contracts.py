from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from runtime.application.services import translations
from runtime.application.services.notifications import NotificationDecisionService
from runtime.bootstrap.runtime import single_instance
from runtime.shared.settings.runtime_migration import (
    CANONICAL_SETTINGS_FILENAME,
    PREVIOUS_SETTINGS_FILENAMES,
    migrate_previous_settings_filename,
)

ROOT = Path(__file__).resolve().parents[2]


class _NotificationStore:
    def __init__(self) -> None:
        self.state: dict[str, dict] = {}
        self.ledger: dict[str, dict] = {}

    def get_alert_state(self, key: str):
        return dict(self.state.get(key) or {})

    def get_notification_ledger(self, key: str):
        return dict(self.ledger.get(key) or {})

    def set_alert_state(self, key: str, **payload) -> None:
        self.state[key] = dict(payload)

    def record_notification_ledger(
        self, key: str, *, state: str, severity: int, payload_hash: str
    ) -> None:
        self.ledger[key] = {
            "state": state,
            "severity": severity,
            "last_payload_hash": payload_hash,
            "last_shown_at": "2026-07-26T10:00:00Z",
        }


def _event(*, rank: int = 2, quantity: int = 1) -> dict:
    return {
        "branch": "H1074",
        "material_number": "1001",
        "product_name": "Milk",
        "production_date": "2026-07-20",
        "expiry_date": "2026-07-27",
        "quantity": quantity,
        "status_kind": "expiring_soon",
        "severity_rank": rank,
    }


def test_translation_catalog_uses_runtime_resources_and_is_complete():
    resource_root = translations._resource_root()
    assert resource_root == ROOT / "runtime" / "resources"
    arabic = translations.language_entries("ar")
    english = translations.language_entries("en")
    assert len(arabic) == len(english) >= 1400
    assert translations.tr_for_language("ar", "settings.title") == "الإعدادات"
    assert translations.tr_for_language("en", "settings.title") == "Settings"
    assert translations.tr_for_language("ar", "Checking connection...") == (
        "جارٍ التحقق من الاتصال..."
    )


def test_notification_decision_is_once_per_day_but_allows_escalation():
    store = _NotificationStore()
    service = NotificationDecisionService(
        clock=lambda: 1_722_000_000.0,
        today_provider=lambda: "2026-07-26",
    )
    first = service.evaluate(store, _event(), once_per_day=True)
    second = service.evaluate(store, _event(), once_per_day=True)
    escalated = service.evaluate(store, _event(rank=4), once_per_day=True)
    assert first.should_notify is True
    assert second.should_notify is False
    assert escalated.should_notify is True
    assert escalated.escalated is True


def test_previous_settings_filename_is_migrated_atomically(tmp_path: Path):
    previous = tmp_path / PREVIOUS_SETTINGS_FILENAMES[0]
    previous.write_text("language=ar\n", encoding="utf-8")
    result = migrate_previous_settings_filename(tmp_path)
    canonical = tmp_path / CANONICAL_SETTINGS_FILENAME
    assert result["migrated"] is True
    assert canonical.read_text(encoding="utf-8") == "language=ar\n"
    assert not previous.exists()


def test_single_instance_bootstrap_exports_the_runtime_api():
    for name in (
        "SingleInstanceGuard",
        "RuntimeInstanceLease",
        "acquire_runtime",
        "reveal_window",
        "cleanup",
    ):
        assert hasattr(single_instance, name)


def test_no_implementation_heavy_package_initializers_remain():
    violations = [
        f"{path.relative_to(ROOT)}:{path.stat().st_size}"
        for path in ROOT.joinpath("runtime").rglob("__init__.py")
        if path.stat().st_size > 4096
    ]
    assert not violations, "\n".join(violations)


def test_no_module_qualified_local_qapplication_references_remain():
    violations: list[str] = []
    for path in ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            parts: list[str] = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            dotted = ".".join(reversed(parts))
            if dotted.startswith("runtime.bootstrap.app."):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{dotted}")
    assert not violations, "\n".join(violations)


def test_release_pipeline_retains_build_inputs_in_editable_source():
    script = (ROOT / "build" / "release" / "BUILD_AND_PUBLISH.ps1").read_text(
        encoding="utf-8"
    )
    excluded_block = script.split("$ExcludedDirectories = @(", 1)[1].split(")", 1)[0]
    assert "'build'" not in excluded_block
    assert "verify_all.py" in (
        ROOT / "build" / "release" / "VALIDATE_SOURCE.ps1"
    ).read_text(encoding="utf-8")

    installer_builder = (
        ROOT / "build" / "installer" / "BUILD_CUSTOM_INSTALLER.ps1"
    ).read_text(encoding="utf-8")
    assert "requirements-build.txt" in installer_builder

    workflow = (
        ROOT / ".github" / "workflows" / "windows-release-validation.yml"
    ).read_text(encoding="utf-8")
    assert "requirements-build.txt" in workflow
    install_step = workflow.split("Install validation dependencies", 1)[1].split(
        "Validate source and Windows Qt runtime", 1
    )[0]
    assert "-r requirements-build.txt" in install_step
    assert "steps.release_metadata.outputs.app_version" in workflow
    assert "HerfyClient-Windows-2.18.1" not in workflow

    deployed_verifier = (
        ROOT / "build" / "release" / "verify_deployed_release.py"
    ).read_text(encoding="utf-8")
    assert "HERFY_DEPLOYED_RELEASE_OK" in deployed_verifier
    assert "Cross-origin redirect was rejected" in deployed_verifier
    assert "Installer SHA-256 mismatch" in deployed_verifier
    assert (ROOT / "00_VERIFY_DEPLOYED_RELEASE.cmd").is_file()
    deployed_workflow = (
        ROOT / ".github" / "workflows" / "deployed-release-validation.yml"
    ).read_text(encoding="utf-8")
    assert "verify_deployed_release.py" in deployed_workflow
    assert "deployed-release-validation.json" in deployed_workflow
    assert "HERFY_SIGNING_PFX_PASSWORD" not in deployed_workflow

    assert "Invoke-FrozenAgentPatchSmoke" in installer_builder
    assert "--validation-no-restart" in installer_builder
    assert "$RestartPath = Join-Path $SmokeRoot 'HerfyClient.exe'" in installer_builder
    assert "Invoke-InstallerSmoke" in installer_builder
    assert "HERFY_INSTALLER_RUNTIME_SMOKE_OK" in installer_builder
    assert "Silent uninstaller smoke test" in installer_builder
    assert "Installed runtime manifest entry escapes the install root" in installer_builder
    assert "Uninstaller left installed runtime files" in installer_builder
    assert "Uninstaller left frozen runtime binaries or metadata" in installer_builder

    assert "Write-Sha256Sidecar" in script
    assert "HERFY_RELEASE_CHECKSUMS_OK" in script
    assert "installer_install_self_check_uninstall = 'passed'" in script
    assert "$ReleaseIsProduction = $SigningPassed" in script
    assert "available = $ReleaseIsProduction" in script
    assert "MandatoryUpdateRequested" in script
    assert "mandatory = ($ReleaseIsProduction -and $MandatoryUpdateRequested)" in script
    assert "current_supported = (-not $MandatoryUpdateRequested)" in script

    signing = (
        ROOT / "build" / "release" / "WINDOWS_CODE_SIGNING.ps1"
    ).read_text(encoding="utf-8")
    assert "Get-AuthenticodeSignature" in signing
    assert "TimeStamperCertificate" in signing
    assert "'/fd', 'SHA256'" in signing

    production_workflow = (
        ROOT / ".github" / "workflows" / "windows-production-release.yml"
    ).read_text(encoding="utf-8")
    assert "environment: production" in production_workflow
    assert 'HERFY_REQUIRE_CODE_SIGNING: "1"' in production_workflow
    assert "windows-build-smoke-and-authenticode-validated" in production_workflow
    assert "gh release create" not in production_workflow
    assert "'release', 'create', $tag" in production_workflow
    assert "publish-bundle-validation.json" in production_workflow
    assert "mandatory_update:" in production_workflow
    assert "HERFY_MANDATORY_UPDATE" in production_workflow

    workflow_sources = [
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    ]
    workflow_text = "\n".join(workflow_sources)
    assert "actions/checkout@v7" in workflow_text
    assert "actions/setup-python@v7" in workflow_text
    assert "actions/upload-artifact@v7" in workflow_text
    for obsolete in (
        "actions/checkout@v4",
        "actions/checkout@v5",
        "actions/checkout@v6",
        "actions/setup-python@v5",
        "actions/setup-python@v6",
        "actions/upload-artifact@v4",
        "actions/upload-artifact@v5",
        "actions/upload-artifact@v6",
    ):
        assert obsolete not in workflow_text


def test_release_metadata_has_one_canonical_application_version():
    metadata = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    assert metadata["app_version"] == metadata["version"] == "2.18.1"
    assert metadata["file_version"] == "2.18.1.0"
    assert metadata["deployment_validation_command"] == (
        "00_VERIFY_DEPLOYED_RELEASE.cmd"
    )
    assert "RFC 3161" in metadata["code_signing_contract"]


def test_package_facades_are_explicit_and_declarative():
    violations = []
    for path in ROOT.joinpath("runtime").rglob("__init__.py"):
        source = path.read_text(encoding="utf-8-sig")
        if "vars(_implementation)" in source or "globals()[_name]" in source:
            violations.append(str(path.relative_to(ROOT)))
    assert not violations, "\n".join(violations)


def test_no_exact_duplicate_nontrivial_function_bodies():
    import hashlib
    from collections import defaultdict

    bodies = defaultdict(list)
    for path in ROOT.joinpath("runtime").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if sum(1 for _ in ast.walk(node)) < 25:
                continue
            normalized = ast.dump(
                ast.Module(body=node.body, type_ignores=[]),
                include_attributes=False,
            )
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            bodies[digest].append((path, node.name, node.lineno))
    duplicates = [
        matches
        for matches in bodies.values()
        if len({path for path, _, _ in matches}) > 1
    ]
    assert not duplicates, duplicates


def test_source_manifest_is_part_of_the_master_validation_pipeline():
    master = (ROOT / "build" / "release" / "verify_all.py").read_text(
        encoding="utf-8"
    )
    assert "write_source_metadata" in master
    assert "verify_source_manifest.py" in master
    assert "feature_version=(3, 11)" in master
    assert (ROOT / "build" / "release" / "source_manifest.py").is_file()


def test_source_metadata_uses_neutral_release_identity():
    metadata = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    assert metadata["package_name"] == (
        "HerfyTrackingSystem_2.18.1_WINDOWS_DESKTOP_SOURCE"
    )
    assert metadata["artifact_kind"] == "editable-validated-windows-desktop-source"
    assert metadata["release_name"] == "WINDOWS_DESKTOP_SOURCE"
    assert metadata["production"] is False


def _qss_blocks(source: str) -> list[tuple[str, str]]:
    without_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    blocks: list[tuple[str, str]] = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", without_comments):
        normalized_selector = " ".join(selector.split())
        declarations = [
            " ".join(part.strip().split())
            for part in body.split(";")
            if part.strip()
        ]
        normalized_body = ";".join(declarations)
        blocks.append((normalized_selector, normalized_body))
    return blocks


def test_theme_resource_is_structurally_clean_and_deduplicated():
    source = (ROOT / "runtime" / "resources" / "theme.qss").read_text(
        encoding="utf-8"
    )
    assert source.count("{") == source.count("}")
    blocks = _qss_blocks(source)
    seen: set[tuple[str, str]] = set()
    duplicates: list[tuple[str, str]] = []
    for block in blocks:
        if block in seen:
            duplicates.append(block)
        seen.add(block)
    assert not duplicates, duplicates
    lowered = source.casefold()
    for forbidden in ("consolidated from", "next-pass"):
        assert forbidden not in lowered


def _duplicate_json_keys(path: Path) -> list[str]:
    duplicates: list[str] = []

    def object_hook(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                duplicates.append(str(key))
            value[key] = item
        return value

    json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=object_hook)
    return duplicates


def test_translation_catalogs_have_no_duplicate_json_keys():
    for language in ("ar", "en"):
        path = ROOT / "runtime" / "resources" / "i18n" / f"{language}.json"
        assert not _duplicate_json_keys(path), language

