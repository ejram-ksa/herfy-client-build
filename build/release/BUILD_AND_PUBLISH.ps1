param(
    [string]$PublishTarget = $env:HERFY_PUBLISH_TARGET,
    [switch]$NoAutoInstallBuildTools,
    [switch]$AllowNonProductionPublishTarget,
    [switch]$MandatoryUpdate
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$CodeSigningScript = Join-Path $ProjectRoot 'build\release\WINDOWS_CODE_SIGNING.ps1'
if (-not (Test-Path -LiteralPath $CodeSigningScript -PathType Leaf)) {
    throw "Missing code-signing helper: $CodeSigningScript"
}
. $CodeSigningScript
$VersionData = Get-Content -Raw -Encoding UTF8 (Join-Path $ProjectRoot 'version.json') | ConvertFrom-Json
$Version = [string]$VersionData.app_version
if ([string]::IsNullOrWhiteSpace($Version)) { throw 'version.json does not contain app_version.' }
$PythonExe = if ([string]::IsNullOrWhiteSpace($env:HERFY_BUILD_PYTHON)) {
    'python'
}
else {
    $env:HERFY_BUILD_PYTHON
}

$BuildScript = Join-Path $ProjectRoot 'build\installer\BUILD_CUSTOM_INSTALLER.ps1'
if ($NoAutoInstallBuildTools) {
    & $BuildScript -Clean -NoAutoInstallBuildTools
}
else {
    & $BuildScript -Clean
}
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }

$OutputDir = Join-Path $ProjectRoot 'build\installer\output'
$Setup = Join-Path $OutputDir "HerfyClientSetup-$Version.exe"
$Patch = Join-Path $OutputDir "HerfyClientRuntime-$Version.zip"
foreach ($Artifact in @($Setup, $Patch)) {
    if (-not (Test-Path -LiteralPath $Artifact -PathType Leaf)) {
        throw "Missing release artifact: $Artifact"
    }
}

$SigningStatusPath = Join-Path $OutputDir 'signing-status.json'
if (-not (Test-Path -LiteralPath $SigningStatusPath -PathType Leaf)) {
    throw "Missing code-signing status: $SigningStatusPath"
}
$SigningStatus = Get-Content -Raw -Encoding UTF8 $SigningStatusPath | ConvertFrom-Json
if ([int]$SigningStatus.schema_version -ne 1) {
    throw "Unsupported code-signing status schema: $($SigningStatus.schema_version)"
}
if ([string]$SigningStatus.status -notin @('passed', 'skipped')) {
    throw "Code-signing pipeline did not complete successfully: $($SigningStatus.status) $($SigningStatus.reason)"
}
$RequiredSignedLabels = @('client-executable', 'update-agent-executable', 'installer')
$PassedSignedLabels = @(
    $SigningStatus.artifacts |
        Where-Object { [string]$_.status -eq 'passed' -and [bool]$_.timestamped } |
        ForEach-Object { [string]$_.label }
)
$MissingSignedLabels = @($RequiredSignedLabels | Where-Object { $_ -notin $PassedSignedLabels })
$SigningStatusCandidate = (
    [string]$SigningStatus.status -eq 'passed' -and
    $MissingSignedLabels.Count -eq 0
)
if ([string]$SigningStatus.status -eq 'passed' -and -not $SigningStatusCandidate) {
    throw "Code-signing status is passed, but signed artifacts are incomplete: $($MissingSignedLabels -join ', ')"
}
if ([bool]$SigningStatus.required -and -not $SigningStatusCandidate) {
    throw "Code signing was required, but signed artifacts are incomplete: $($MissingSignedLabels -join ', ')"
}

$PublishRoot = Join-Path $ProjectRoot 'publish'
Remove-Item -Recurse -Force $PublishRoot -ErrorAction SilentlyContinue
$Packages = Join-Path $PublishRoot 'updates\packages'
$VersionRoot = Join-Path $PublishRoot "updates\$Version"
$ValidationRoot = Join-Path $PublishRoot 'validation'
New-Item -ItemType Directory -Force -Path $Packages, $VersionRoot, $ValidationRoot | Out-Null
$PublishedSigningStatus = Join-Path $ValidationRoot 'signing-status.json'
Copy-Item -Force -LiteralPath $SigningStatusPath -Destination $PublishedSigningStatus

function Write-Sha256Sidecar {
    param(
        [Parameter(Mandatory = $true)][string]$ArtifactPath,
        [Parameter(Mandatory = $true)][string]$Hash
    )
    if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
        throw "Cannot write checksum for missing artifact: $ArtifactPath"
    }
    $SidecarPath = "$ArtifactPath.sha256"
    $Line = $Hash.ToLowerInvariant() + '  ' + (Split-Path -Leaf $ArtifactPath) + "`n"
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($SidecarPath, $Line, $Utf8NoBom)
    return $SidecarPath
}


function Copy-CleanEditableSource {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $ExcludedDirectories = @(
        '.git', '.venv', 'venv', '__pycache__', '.pytest_cache',
        '.ruff_cache', '.mypy_cache', 'htmlcov', 'dist', 'output',
        'publish', 'backup', 'backups', 'old', 'server'
    )
    $ExcludedFileNames = @('.coverage', 'coverage.xml')
    $ExcludedSuffixes = @(
        '.pyc', '.pyo', '.log', '.tmp', '.temp', '.bak', '.old',
        '.orig', '.rej', '.exe', '.msi', '.zip'
    )

    function Copy-DirectoryContents {
        param(
            [Parameter(Mandatory = $true)][string]$CurrentSource,
            [Parameter(Mandatory = $true)][string]$CurrentDestination
        )

        New-Item -ItemType Directory -Force -Path $CurrentDestination | Out-Null
        foreach ($Item in @(Get-ChildItem -Force -LiteralPath $CurrentSource)) {
            if ($Item.PSIsContainer) {
                if ($ExcludedDirectories -contains $Item.Name) { continue }
                Copy-DirectoryContents `
                    -CurrentSource $Item.FullName `
                    -CurrentDestination (Join-Path $CurrentDestination $Item.Name)
                continue
            }
            if (
                $ExcludedFileNames -contains $Item.Name -or
                $Item.Name.StartsWith('.coverage.') -or
                $ExcludedSuffixes -contains $Item.Extension.ToLowerInvariant()
            ) {
                continue
            }
            Copy-Item -Force -LiteralPath $Item.FullName -Destination (
                Join-Path $CurrentDestination $Item.Name
            )
        }
    }

    Remove-Item -Recurse -Force -LiteralPath $Destination -ErrorAction SilentlyContinue
    Copy-DirectoryContents -CurrentSource $Source -CurrentDestination $Destination
}

function Get-HerfySigningArtifactRecord {
    param(
        [Parameter(Mandatory = $true)][object]$Status,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $Matches = @($Status.artifacts | Where-Object { [string]$_.label -eq $Label })
    if ($Matches.Count -ne 1) {
        throw "Expected exactly one signing record for ${Label}; found $($Matches.Count)."
    }
    $Record = $Matches[0]
    if ([string]$Record.status -ne 'passed' -or -not [bool]$Record.timestamped) {
        throw "Signing record is not complete for $Label."
    }
    if ([string]$Record.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or [int64]$Record.size -le 0) {
        throw "Signing record has invalid integrity metadata for $Label."
    }
    return $Record
}

function Assert-HerfyPublishedCodeSignatures {
    param(
        [Parameter(Mandatory = $true)][string]$SetupPath,
        [Parameter(Mandatory = $true)][string]$PatchPath,
        [Parameter(Mandatory = $true)][object]$Status
    )

    $Thumbprint = Normalize-HerfyCertificateThumbprint -Thumbprint ([string]$Status.certificate_thumbprint)
    $SignTool = Resolve-HerfySignTool
    if ([string]::IsNullOrWhiteSpace([string]$SignTool)) {
        throw 'signtool.exe is required to independently verify signed release artifacts.'
    }
    $VerificationSession = @{
        Enabled = $true
        SignTool = $SignTool
        Thumbprint = $Thumbprint
    }

    $SetupRecord = Get-HerfySigningArtifactRecord -Status $Status -Label 'installer'
    Assert-HerfyAuthenticodeSignature -Session $VerificationSession -Path $SetupPath -Label 'publish-installer'
    $ActualSetupHash = (Get-FileHash -LiteralPath $SetupPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $ActualSetupSize = (Get-Item -LiteralPath $SetupPath).Length
    if ($ActualSetupHash -ne ([string]$SetupRecord.sha256).ToLowerInvariant() -or $ActualSetupSize -ne [int64]$SetupRecord.size) {
        throw 'Installer changed after Authenticode signing.'
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $ExtractionRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
        'herfy-signature-verify-' + [Guid]::NewGuid().ToString('N')
    )
    New-Item -ItemType Directory -Force -Path $ExtractionRoot | Out-Null
    $Archive = $null
    try {
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($PatchPath)
        foreach ($Specification in @(
            [pscustomobject]@{ Label = 'client-executable'; Name = 'HerfyClient.exe' },
            [pscustomobject]@{ Label = 'update-agent-executable'; Name = 'HerfyClientUpdateAgent.exe' }
        )) {
            $MatchingEntries = @(
                $Archive.Entries |
                    Where-Object { $_.FullName.Replace('\', '/') -eq $Specification.Name }
            )
            if ($MatchingEntries.Count -ne 1) {
                throw "Runtime patch must contain exactly one $($Specification.Name) entry."
            }
            $Entry = $MatchingEntries[0]
            if ([int64]$Entry.Length -le 0 -or [int64]$Entry.Length -gt 512MB) {
                throw "Runtime patch executable has an invalid size: $($Specification.Name)"
            }
            $ExtractedPath = Join-Path $ExtractionRoot $Specification.Name
            $InputStream = $Entry.Open()
            $OutputStream = [System.IO.File]::Create($ExtractedPath)
            try {
                $InputStream.CopyTo($OutputStream)
            }
            finally {
                $OutputStream.Dispose()
                $InputStream.Dispose()
            }

            Assert-HerfyAuthenticodeSignature `
                -Session $VerificationSession `
                -Path $ExtractedPath `
                -Label ("publish-" + $Specification.Label)
            $Record = Get-HerfySigningArtifactRecord -Status $Status -Label $Specification.Label
            $ActualHash = (Get-FileHash -LiteralPath $ExtractedPath -Algorithm SHA256).Hash.ToLowerInvariant()
            $ActualSize = (Get-Item -LiteralPath $ExtractedPath).Length
            if ($ActualHash -ne ([string]$Record.sha256).ToLowerInvariant() -or $ActualSize -ne [int64]$Record.size) {
                throw "Runtime patch executable changed after Authenticode signing: $($Specification.Name)"
            }
        }
    }
    finally {
        if ($null -ne $Archive) { $Archive.Dispose() }
        Remove-Item -Recurse -Force -LiteralPath $ExtractionRoot -ErrorAction SilentlyContinue
    }
    Write-Host 'HERFY_PUBLISH_AUTHENTICODE_REVERIFY_OK artifacts=3'
}

$SigningPassed = $false
if ($SigningStatusCandidate) {
    Assert-HerfyPublishedCodeSignatures -SetupPath $Setup -PatchPath $Patch -Status $SigningStatus
    $SigningPassed = $true
}
$ReleaseIsProduction = $SigningPassed
$MandatoryUpdateRequested = (
    [bool]$MandatoryUpdate -or
    [string]$env:HERFY_MANDATORY_UPDATE -eq '1'
)
if ($MandatoryUpdateRequested -and -not $ReleaseIsProduction) {
    throw 'Mandatory update metadata cannot be generated for a non-production release.'
}
$ReleaseGate = if ($ReleaseIsProduction) {
    'windows-build-smoke-and-authenticode-validated'
}
else {
    'windows-build-validated-code-signing-not-verified'
}
$CodeSigningValidation = if ($SigningPassed) { 'passed' } else { 'not_verified' }

$SetupName = "HerfyClient_Setup_$Version.exe"
$PatchName = "HerfyClient_${Version}_remote_update.zip"
$PublishedSetup = Join-Path $Packages $SetupName
$PublishedPatch = Join-Path $Packages $PatchName
Copy-Item -Force $Setup $PublishedSetup
Copy-Item -Force $Patch $PublishedPatch
Copy-Item -Force $PublishedSetup (Join-Path $VersionRoot $SetupName)
Copy-Item -Force $PublishedPatch (Join-Path $VersionRoot $PatchName)

$SetupHash = (Get-FileHash -Algorithm SHA256 $PublishedSetup).Hash.ToLowerInvariant()
$PatchHash = (Get-FileHash -Algorithm SHA256 $PublishedPatch).Hash.ToLowerInvariant()
$SetupSize = (Get-Item $PublishedSetup).Length
$PatchSize = (Get-Item $PublishedPatch).Length
$SourcePublishRoot = Join-Path $PublishRoot 'source'
New-Item -ItemType Directory -Force -Path $SourcePublishRoot | Out-Null
$SourceStage = Join-Path $env:TEMP (
    'HerfyClient_Source_' + $Version.Replace('.', '') + '_' +
    [Guid]::NewGuid().ToString('N')
)
$SourceName = "HerfyTrackingSystem_${Version}_WINDOWS_DESKTOP_SOURCE.zip"
$PublishedSource = Join-Path $SourcePublishRoot $SourceName
$SourceArchiveBuilder = Join-Path $ProjectRoot 'build\release\build_source_archive.py'
$SourceArchiveVerifier = Join-Path $ProjectRoot 'build\release\verify_source_archive.py'
foreach ($Tool in @($SourceArchiveBuilder, $SourceArchiveVerifier)) {
    if (-not (Test-Path -LiteralPath $Tool -PathType Leaf)) {
        throw "Missing source archive tool: $Tool"
    }
}
try {
    Copy-CleanEditableSource -Source $ProjectRoot -Destination $SourceStage
    if (Test-Path -LiteralPath $PublishedSource) {
        Remove-Item -Force -LiteralPath $PublishedSource
    }
    & $PythonExe $SourceArchiveBuilder $SourceStage $PublishedSource
    if ($LASTEXITCODE -ne 0) { throw 'Deterministic editable-source archive creation failed.' }
    & $PythonExe $SourceArchiveVerifier `
        $PublishedSource `
        --source-root $SourceStage `
        --verify-metadata
    if ($LASTEXITCODE -ne 0) { throw 'Editable-source archive verification failed.' }
}
finally {
    Remove-Item -Recurse -Force -LiteralPath $SourceStage -ErrorAction SilentlyContinue
}
if (-not (Test-Path -LiteralPath $PublishedSource -PathType Leaf)) {
    throw "Editable source package was not created: $PublishedSource"
}
$SourceHash = (Get-FileHash -Algorithm SHA256 $PublishedSource).Hash.ToLowerInvariant()
$SourceSize = (Get-Item $PublishedSource).Length
$OutputSetupChecksum = Write-Sha256Sidecar -ArtifactPath $Setup -Hash $SetupHash
$OutputPatchChecksum = Write-Sha256Sidecar -ArtifactPath $Patch -Hash $PatchHash
$PublishedSetupChecksum = Write-Sha256Sidecar -ArtifactPath $PublishedSetup -Hash $SetupHash
$PublishedPatchChecksum = Write-Sha256Sidecar -ArtifactPath $PublishedPatch -Hash $PatchHash
$PublishedSourceChecksum = Write-Sha256Sidecar -ArtifactPath $PublishedSource -Hash $SourceHash
Copy-Item -Force -LiteralPath $PublishedSetupChecksum -Destination (
    Join-Path $VersionRoot (Split-Path -Leaf $PublishedSetupChecksum)
)
Copy-Item -Force -LiteralPath $PublishedPatchChecksum -Destination (
    Join-Path $VersionRoot (Split-Path -Leaf $PublishedPatchChecksum)
)
Write-Host "HERFY_RELEASE_CHECKSUMS_OK setup=$OutputSetupChecksum patch=$OutputPatchChecksum source=$PublishedSourceChecksum"
Write-Host "HERFY_EDITABLE_SOURCE_PACKAGE_OK path=$PublishedSource"

$GeneratedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$Notes = 'The full installer replaces obsolete runtime modules before installing the isolated frozen application.'

# Older or mixed installations must use the full
# installer. The patch is produced only for agent validation and is not
# advertised to older clients.
$Latest = [ordered]@{
    latest = $Version
    version = $Version
    latest_version = $Version
    target_version = $Version
    available = $ReleaseIsProduction
    update_available = $ReleaseIsProduction
    mandatory = ($ReleaseIsProduction -and $MandatoryUpdateRequested)
    force_update = ($ReleaseIsProduction -and $MandatoryUpdateRequested)
    current_supported = (-not $MandatoryUpdateRequested)
    package_name = $(if ($ReleaseIsProduction) { $SetupName } else { '' })
    setup_package = $(if ($ReleaseIsProduction) { $SetupName } else { '' })
    url = $(if ($ReleaseIsProduction) { "/updates/packages/$SetupName" } else { '' })
    installer_url = $(if ($ReleaseIsProduction) { "/updates/packages/$SetupName" } else { '' })
    download_url = $(if ($ReleaseIsProduction) { "/updates/packages/$SetupName" } else { '' })
    sha256 = $(if ($ReleaseIsProduction) { $SetupHash } else { '' })
    setup_sha256 = $(if ($ReleaseIsProduction) { $SetupHash } else { '' })
    size = $(if ($ReleaseIsProduction) { $SetupSize } else { 0 })
    setup_size = $(if ($ReleaseIsProduction) { $SetupSize } else { 0 })
    patch_package = ''
    patch_download_url = ''
    patch_sha256 = ''
    patch_size = 0
    patches = @()
    notes = $Notes
    generated_at = $GeneratedAt
}

$Json = $Latest | ConvertTo-Json -Depth 10
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
foreach ($Name in @('latest.json', 'manifest.json', 'upgrade-plan.json')) {
    [IO.File]::WriteAllText((Join-Path (Join-Path $PublishRoot 'updates') $Name), $Json, $Utf8NoBom)
}

$ReleaseInfo = [ordered]@{
    schema_version = 3
    version = $Version
    generated_at = $GeneratedAt
    target = 'Windows 10/11 x64'
    production = $ReleaseIsProduction
    release_gate = $ReleaseGate
    installer = [ordered]@{
        file = $SetupName
        sha256 = $SetupHash
        size = $SetupSize
        checksum_file = (Split-Path -Leaf $PublishedSetupChecksum)
    }
    validation_patch = [ordered]@{
        file = $PatchName
        sha256 = $PatchHash
        size = $PatchSize
        checksum_file = (Split-Path -Leaf $PublishedPatchChecksum)
        advertised = $false
    }
    editable_source = [ordered]@{
        file = $SourceName
        sha256 = $SourceHash
        size = $SourceSize
        checksum_file = (Split-Path -Leaf $PublishedSourceChecksum)
    }
    validation = [ordered]@{
        source_contracts = 'passed'
        frozen_runtime_self_check = 'passed'
        frozen_notification_self_check = 'passed'
        frozen_update_agent_patch_apply = 'passed'
        installer_install_self_check_uninstall = 'passed'
        code_signing = $CodeSigningValidation
    }
    code_signing = [ordered]@{
        status = [string]$SigningStatus.status
        required = [bool]$SigningStatus.required
        timestamp_url = [string]$SigningStatus.timestamp_url
        certificate_thumbprint = [string]$SigningStatus.certificate_thumbprint
        status_file = 'validation/signing-status.json'
        signed_artifacts = @($PassedSignedLabels)
    }
    update_policy = 'full-installer-replacement'
    update_enforcement = $(if ($MandatoryUpdateRequested) { 'mandatory' } else { 'optional' })
}
[IO.File]::WriteAllText(
    (Join-Path $PublishRoot 'release.json'),
    ($ReleaseInfo | ConvertTo-Json -Depth 10),
    $Utf8NoBom
)

$PublishBundleVerifier = Join-Path $ProjectRoot 'build\release\verify_publish_bundle.py'
if (-not (Test-Path -LiteralPath $PublishBundleVerifier -PathType Leaf)) {
    throw "Missing publish-bundle verifier: $PublishBundleVerifier"
}
$PublishBundleReport = Join-Path $ValidationRoot 'publish-bundle-validation.json'
& $PythonExe $PublishBundleVerifier `
    $PublishRoot `
    --expected-version $Version `
    --output $PublishBundleReport
if ($LASTEXITCODE -ne 0) { throw 'Publish-bundle verification failed.' }

if (-not [string]::IsNullOrWhiteSpace($PublishTarget)) {
    if (-not $ReleaseIsProduction -and -not $AllowNonProductionPublishTarget) {
        throw 'Refusing to copy a non-production bundle to PublishTarget. Sign the release or pass -AllowNonProductionPublishTarget explicitly.'
    }
    $ResolvedProjectRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $ResolvedPublishTarget = [IO.Path]::GetFullPath($PublishTarget).TrimEnd('\')
    if ($ResolvedPublishTarget -eq $ResolvedProjectRoot) {
        throw 'PublishTarget must not be the project root.'
    }
    $ProjectPrefix = $ResolvedProjectRoot + [IO.Path]::DirectorySeparatorChar
    if ($ResolvedPublishTarget.StartsWith(
        $ProjectPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw 'PublishTarget must be outside the editable source tree.'
    }
    $PublishTargetRoot = [IO.Path]::GetPathRoot($ResolvedPublishTarget).TrimEnd('\')
    if ($ResolvedPublishTarget -eq $PublishTargetRoot) {
        throw 'PublishTarget must not be a filesystem root.'
    }
    New-Item -ItemType Directory -Force -Path $PublishTarget | Out-Null
    Copy-Item -Recurse -Force (Join-Path $PublishRoot '*') $PublishTarget
    & $PythonExe $PublishBundleVerifier `
        $PublishTarget `
        --expected-version $Version `
        --output (Join-Path $ValidationRoot 'publish-target-validation.json')
    if ($LASTEXITCODE -ne 0) { throw 'PublishTarget verification failed.' }
}

Write-Host "HERFY_BUILD_AND_PUBLISH_OK version=$Version production=$ReleaseIsProduction signing=$CodeSigningValidation policy=full-installer-replacement enforcement=$(if ($MandatoryUpdateRequested) { 'mandatory' } else { 'optional' }) source=$SourceName"
