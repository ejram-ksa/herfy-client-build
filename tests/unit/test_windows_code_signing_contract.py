from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_signing_helper_uses_sha256_rfc3161_and_verifies_authenticode():
    source = _text("build/release/WINDOWS_CODE_SIGNING.ps1")
    for contract in (
        "'/fd', 'SHA256'",
        "'/tr', [string]$Session.TimestampUrl",
        "'/td', 'SHA256'",
        "'verify', '/pa', '/all', '/v'",
        "Get-AuthenticodeSignature",
        "TimeStamperCertificate",
        "HERFY_REQUIRE_CODE_SIGNING",
        "HERFY_SIGNING_CERT_THUMBPRINT",
        "HERFY_SIGNING_PFX_BASE64",
        "HERFY_SIGNING_PFX_PASSWORD",
        "http://timestamp.digicert.com",
    ):
        assert contract in source
    assert "'/p'" not in source
    assert '"/p"' not in source


def test_temporary_pfx_is_removed_and_imported_certificate_is_cleaned_up():
    source = _text("build/release/WINDOWS_CODE_SIGNING.ps1")
    assert "Remove-Item -Force -LiteralPath $TemporaryPfx" in source
    assert "Cert:\\CurrentUser\\My\\" in source
    assert "ImportedThumbprint" in source
    assert "Import-PfxCertificate" in source
    assert "$env:HERFY_SIGNING_PFX_BASE64 = ''" in source
    assert "$env:HERFY_SIGNING_PFX_PASSWORD = ''" in source
    assert "-Exportable:$false" in source


def test_release_builder_signs_frozen_executables_before_manifest_and_installer_before_smoke():
    source = _text("build/installer/BUILD_CUSTOM_INSTALLER.ps1")
    client_sign = source.index(
        "Invoke-HerfyCodeSigning -Session $SigningSession -Path $ClientExe"
    )
    agent_sign = source.index(
        "Invoke-HerfyCodeSigning -Session $SigningSession -Path $AgentExe"
    )
    manifest = source.index("& $PythonExe $RuntimeManifestBuilder --runtime $DistDir")
    setup_sign = source.index(
        "Invoke-HerfyCodeSigning -Session $SigningSession -Path $SetupPath"
    )
    setup_smoke = source.index(
        "Invoke-InstallerSmoke -SetupPath $SetupPath -Version $Version"
    )
    assert client_sign < manifest
    assert agent_sign < manifest
    assert setup_sign < setup_smoke
    assert "Complete-HerfyCodeSigningSession" in source
    assert "signing-status.json" in source
    assert "Assert-HerfyAuthenticodeSignature -Session $SigningSession -Path $InstalledClient" in source
    assert "Assert-HerfyAuthenticodeSignature -Session $SigningSession -Path $InstalledAgent" in source


def test_unsigned_publish_bundle_is_not_advertised_as_production_update():
    source = _text("build/release/BUILD_AND_PUBLISH.ps1")
    assert "$ReleaseIsProduction = $SigningPassed" in source
    assert "production = $ReleaseIsProduction" in source
    assert "available = $ReleaseIsProduction" in source
    assert "mandatory = ($ReleaseIsProduction -and $MandatoryUpdateRequested)" in source
    assert "force_update = ($ReleaseIsProduction -and $MandatoryUpdateRequested)" in source
    assert "current_supported = (-not $MandatoryUpdateRequested)" in source
    assert "code_signing = $CodeSigningValidation" in source
    assert "signed artifacts are incomplete" in source
    assert "status_file = 'validation/signing-status.json'" in source
    assert "Assert-HerfyPublishedCodeSignatures" in source
    assert "Runtime patch must contain exactly one" in source
    assert "changed after Authenticode signing" in source


def test_windows_workflow_exposes_strict_signing_gate_without_using_secrets_on_validation_job():
    source = _text(".github/workflows/windows-release-validation.yml")
    assert "require_code_signing:" in source
    assert "HERFY_REQUIRE_CODE_SIGNING:" in source
    assert "secrets.HERFY_SIGNING_CERT_THUMBPRINT" in source
    assert "secrets.HERFY_SIGNING_PFX_BASE64" in source
    assert "secrets.HERFY_SIGNING_PFX_PASSWORD" in source
    assert "vars.HERFY_TIMESTAMP_URL" in source
    validate_job, build_job = source.split("  build-release:", 1)
    assert "HERFY_SIGNING_PFX_BASE64" not in validate_job
    assert "HERFY_SIGNING_PFX_BASE64" in build_job
