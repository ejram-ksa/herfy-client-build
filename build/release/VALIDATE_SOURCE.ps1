param(
    [string]$Python = $env:HERFY_BUILD_PYTHON,
    [switch]$EnforceFormat
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ([string]::IsNullOrWhiteSpace($Python)) { $Python = 'python' }
$MasterVerifier = Join-Path $ProjectRoot 'build\release\verify_all.py'
if (-not (Test-Path -LiteralPath $MasterVerifier -PathType Leaf)) {
    throw "Missing master source verifier: $MasterVerifier"
}

Push-Location $ProjectRoot
try {
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:QT_QPA_PLATFORM = 'offscreen'
    $Arguments = @($MasterVerifier, '--require-quality-tools')
    if ($EnforceFormat) { $Arguments += '--enforce-format' }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Herfy source validation failed.' }

    $VersionData = Get-Content -Raw -Encoding UTF8 (Join-Path $ProjectRoot 'version.json') | ConvertFrom-Json
    Write-Host "HERFY_SOURCE_VALIDATION_OK version=$($VersionData.app_version)"
}
finally {
    Pop-Location
}
