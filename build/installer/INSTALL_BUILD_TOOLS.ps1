param([switch]$NoAutoInstallBuildTools)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Bootstrap = Join-Path $PSScriptRoot 'INNO_SETUP_BOOTSTRAP.ps1'
if (-not (Test-Path -LiteralPath $Bootstrap)) { throw "Missing Inno Setup bootstrap: $Bootstrap" }
. $Bootstrap
$Compiler = Resolve-InnoSetupCompiler -InstallIfMissing:(-not $NoAutoInstallBuildTools)
Write-Host "HERFY_BUILD_TOOLS_OK inno_compiler=$Compiler"
