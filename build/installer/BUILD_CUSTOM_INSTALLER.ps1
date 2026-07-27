param(
    [switch]$Clean,
    [switch]$SkipPythonBuild,
    [switch]$SkipPatch,
    [switch]$SkipInno,
    [switch]$NoAutoInstallBuildTools,
    [ValidateRange(30, 600)][int]$SelfCheckTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$VersionData = Get-Content -Raw -Encoding UTF8 (Join-Path $ProjectRoot 'version.json') | ConvertFrom-Json
$ExpectedVersion = [string]$VersionData.app_version
if ([string]::IsNullOrWhiteSpace($ExpectedVersion)) { throw 'version.json does not contain app_version.' }

function Resolve-ShortBuildWorkspaceRoot {
    param([Parameter(Mandatory = $true)][string]$Version)

    $ConfiguredRoot = [string]$env:HERFY_BUILD_ROOT
    if ([string]::IsNullOrWhiteSpace($ConfiguredRoot)) {
        $SystemDrive = [string]$env:SystemDrive
        if ([string]::IsNullOrWhiteSpace($SystemDrive)) {
            $SystemDrive = [System.IO.Path]::GetPathRoot([string]$env:TEMP)
        }
        if ([string]::IsNullOrWhiteSpace($SystemDrive)) { $SystemDrive = 'C:\' }
        if ($SystemDrive -match '^[A-Za-z]:$') { $SystemDrive += '\' }
        $VersionToken = $Version.Replace('.', '')
        $ConfiguredRoot = [System.IO.Path]::Combine(
            $SystemDrive,
            'HerfyBuild',
            $VersionToken
        )
    }

    $ResolvedRoot = [System.IO.Path]::GetFullPath($ConfiguredRoot).TrimEnd('\')
    $DriveRoot = [System.IO.Path]::GetPathRoot($ResolvedRoot).TrimEnd('\')
    if ($ResolvedRoot.StartsWith('\\')) {
        throw "HERFY_BUILD_ROOT must be a local drive path, not a network path: $ResolvedRoot"
    }
    if ($ResolvedRoot -eq $DriveRoot -or $ResolvedRoot.Length -lt 10) {
        throw "Unsafe HERFY_BUILD_ROOT: $ResolvedRoot"
    }
    if (
        $ResolvedRoot.Equals(
            $ProjectRoot.TrimEnd('\'),
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw 'HERFY_BUILD_ROOT cannot be the project source directory because -Clean would delete source files.'
    }
    if ($ResolvedRoot.Length -gt 80) {
        throw "HERFY_BUILD_ROOT is too long ($($ResolvedRoot.Length) characters). Use C:\HerfyBuild\$($Version.Replace('.', ''))."
    }
    return $ResolvedRoot
}

$BuildWorkspaceRoot = Resolve-ShortBuildWorkspaceRoot -Version $ExpectedVersion
$DistRoot = Join-Path $BuildWorkspaceRoot 'dist'
$DistDir = Join-Path $DistRoot 'HerfyClient'
$BuildDir = Join-Path $BuildWorkspaceRoot 'build'
$OutputDir = Join-Path $PSScriptRoot 'output'
$SigningStatusPath = Join-Path $OutputDir 'signing-status.json'
$ClientSpecFile = Join-Path $PSScriptRoot 'pyinstaller\HerfyClient.spec'
$AgentSpecFile = Join-Path $PSScriptRoot 'pyinstaller\HerfyClientUpdateAgent.spec'
$InnoFile = Join-Path $PSScriptRoot 'HerfyClient_Custom_Installer.iss'
$PatchBuilder = Join-Path $ProjectRoot 'build\release\build_runtime_patch.py'
$RuntimeManifestBuilder = Join-Path $ProjectRoot 'build\release\build_runtime_manifest.py'
$MasterVerifier = Join-Path $ProjectRoot 'build\release\verify_all.py'
$StructureVerifier = Join-Path $ProjectRoot 'build\release\verify_structure_contract.py'
$ValidationScript = Join-Path $ProjectRoot 'build\release\VALIDATE_SOURCE.ps1'
$VenvDir = Join-Path $BuildWorkspaceRoot 'venv'
$PythonExe = Join-Path $VenvDir 'Scripts\python.exe'
$BuildLockPath = "$BuildWorkspaceRoot.lock"
$BuildLockStream = $null
$InnoBootstrap = Join-Path $PSScriptRoot 'INNO_SETUP_BOOTSTRAP.ps1'
$CodeSigningScript = Join-Path $ProjectRoot 'build\release\WINDOWS_CODE_SIGNING.ps1'
if (-not (Test-Path -LiteralPath $InnoBootstrap)) { throw "Missing Inno Setup bootstrap: $InnoBootstrap" }
if (-not (Test-Path -LiteralPath $CodeSigningScript)) { throw "Missing code-signing helper: $CodeSigningScript" }
. $InnoBootstrap
. $CodeSigningScript
$SigningSession = $null
$BuildSucceeded = $false

function Assert-SafeBuildWorkspace {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 100)][int]$MinimumFreeSpaceGb = 4
    )

    $FullPath = [System.IO.Path]::GetFullPath($Path)
    $ParentPath = Split-Path -Parent $FullPath
    if ([string]::IsNullOrWhiteSpace($ParentPath)) {
        throw "Unable to resolve the build workspace parent: $FullPath"
    }
    New-Item -ItemType Directory -Force -Path $ParentPath | Out-Null

    foreach ($Candidate in @($ParentPath, $FullPath)) {
        if (-not (Test-Path -LiteralPath $Candidate)) { continue }
        $Item = Get-Item -Force -LiteralPath $Candidate
        if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Build workspace cannot be a junction, symbolic link, or other reparse point: $Candidate"
        }
    }

    $DriveRoot = [System.IO.Path]::GetPathRoot($FullPath)
    $Drive = [System.IO.DriveInfo]::new($DriveRoot)
    $RequiredBytes = [int64]$MinimumFreeSpaceGb * 1GB
    if ($Drive.AvailableFreeSpace -lt $RequiredBytes) {
        $FreeGb = [Math]::Round($Drive.AvailableFreeSpace / 1GB, 2)
        throw "Insufficient free space on $DriveRoot. Required ${MinimumFreeSpaceGb} GB; available ${FreeGb} GB."
    }
    Write-Host "HERFY_BUILD_STORAGE_OK root=$FullPath free_bytes=$($Drive.AvailableFreeSpace)"
}

function Enter-BuildLock {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    try {
        $Stream = [System.IO.File]::Open(
            $Path,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $Stream.SetLength(0)
        $Payload = [System.Text.Encoding]::UTF8.GetBytes(
            "pid=$PID`r`nstarted_utc=$([DateTime]::UtcNow.ToString('o'))`r`n"
        )
        $Stream.Write($Payload, 0, $Payload.Length)
        $Stream.Flush()
        Write-Host "HERFY_BUILD_LOCK_OK path=$Path pid=$PID"
        return $Stream
    }
    catch {
        throw "Another Herfy Client build is already using this workspace, or the build lock is inaccessible: $Path. $($_.Exception.Message)"
    }
}

function Exit-BuildLock {
    param(
        [System.IO.FileStream]$Stream,
        [string]$Path
    )
    if ($null -ne $Stream) { $Stream.Dispose() }
    if (-not [string]::IsNullOrWhiteSpace($Path)) {
        Remove-Item -Force -LiteralPath $Path -ErrorAction SilentlyContinue
    }
}

function Assert-NoMissingLocalPyInstallerModules {
    param(
        [Parameter(Mandatory = $true)][string]$WorkPath,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $WarningFiles = @(
        Get-ChildItem -LiteralPath $WorkPath -Recurse -File -Filter 'warn-*.txt' -ErrorAction SilentlyContinue
    )
    if ($WarningFiles.Count -eq 0) {
        throw "$Label did not produce a PyInstaller warning report under $WorkPath"
    }

    $LocalMissingPattern = 'missing module named [''\"]?(?:app|application|bootstrap|core|data|domain|presentation|remote|services|settings|ui)(?:\\.|[''\"])'
    $Violations = @()
    foreach ($WarningFile in $WarningFiles) {
        $Matches = @(Select-String -LiteralPath $WarningFile.FullName -Pattern $LocalMissingPattern -AllMatches)
        foreach ($Match in $Matches) {
            $Violations += "$($WarningFile.FullName):$($Match.LineNumber): $($Match.Line.Trim())"
        }
    }
    if ($Violations.Count -gt 0) {
        throw "$Label contains missing local runtime modules:`n$($Violations -join "`n")"
    }
    Write-Host "HERFY_PYINSTALLER_LOCAL_IMPORTS_OK label=$Label warning_files=$($WarningFiles.Count)"
}

function Optimize-FrozenQtRuntime {
    param([Parameter(Mandatory = $true)][string]$RuntimeDir)

    $TranslationDir = Join-Path $RuntimeDir 'PyQt5\Qt5\translations'
    $RemovedTranslations = 0
    if (Test-Path -LiteralPath $TranslationDir) {
        $AllowedTranslationPattern = '^(?:qt|qtbase|qtmultimedia)_(?:ar|en)\.qm$'
        foreach ($Translation in @(Get-ChildItem -LiteralPath $TranslationDir -File -Filter '*.qm')) {
            if ($Translation.Name -notmatch $AllowedTranslationPattern) {
                Remove-Item -Force -LiteralPath $Translation.FullName
                $RemovedTranslations++
            }
        }
    }

    $UnexpectedTranslations = @()
    if (Test-Path -LiteralPath $TranslationDir) {
        $UnexpectedTranslations = @(
            Get-ChildItem -LiteralPath $TranslationDir -File -Filter '*.qm' |
                Where-Object { $_.Name -notmatch $AllowedTranslationPattern }
        )
    }
    if ($UnexpectedTranslations.Count -gt 0) {
        throw "Frozen Qt translation cleanup failed: $($UnexpectedTranslations.Name -join ', ')"
    }

    $RemovedPlugins = 0
    $PlatformDir = Join-Path $RuntimeDir 'PyQt5\Qt5\plugins\platforms'
    foreach ($PluginName in @('qminimal.dll', 'qwebgl.dll')) {
        $PluginPath = Join-Path $PlatformDir $PluginName
        if (Test-Path -LiteralPath $PluginPath) {
            Remove-Item -Force -LiteralPath $PluginPath
            $RemovedPlugins++
        }
    }
    foreach ($RequiredPlugin in @('qwindows.dll', 'qoffscreen.dll')) {
        $RequiredPluginPath = Join-Path $PlatformDir $RequiredPlugin
        if (-not (Test-Path -LiteralPath $RequiredPluginPath -PathType Leaf)) {
            throw "Required frozen Qt platform plugin is missing after cleanup: $RequiredPlugin"
        }
    }

    Write-Host "HERFY_FROZEN_RUNTIME_CLEAN_OK translations_removed=$RemovedTranslations plugins_removed=$RemovedPlugins"
}

function Read-AppVersion {
    $VersionFile = Join-Path $ProjectRoot 'version.json'
    if (-not (Test-Path -LiteralPath $VersionFile)) { throw "Missing $VersionFile" }
    $VersionData = Get-Content -Raw -Encoding UTF8 $VersionFile | ConvertFrom-Json
    if ($VersionData.app_version) { return [string]$VersionData.app_version }
    if ($VersionData.version) { return [string]$VersionData.version }
    throw 'version.json does not contain app_version or version.'
}

function Assert-NativeExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Test-Python311X64 {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$Prefix = @()
    )
    if (-not (Test-Path -LiteralPath $Executable)) { return $false }
    & $Executable @Prefix -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64 else 1)"
    return ($LASTEXITCODE -eq 0)
}

function Resolve-BasePython311X64 {
    $PyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        foreach ($Selector in @('-3.11-64', '-3.11')) {
            & $PyLauncher.Source $Selector -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') * 8 == 64 else 1)"
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]@{ File = [string]$PyLauncher.Source; Prefix = [string[]]@($Selector) }
            }
        }
    }

    foreach ($Name in @('python.exe', 'python')) {
        $Python = Get-Command $Name -ErrorAction SilentlyContinue
        if (-not $Python) { continue }
        if (Test-Python311X64 -Executable ([string]$Python.Source)) {
            return [pscustomobject]@{ File = [string]$Python.Source; Prefix = [string[]]@() }
        }
    }

    throw '64-bit Python 3.11 was not found. Install Python 3.11 x64 (the Python Launcher is recommended), then rerun this script.'
}

function Ensure-BuildPython {
    if (Test-Python311X64 -Executable $PythonExe) { return }

    if (Test-Path -LiteralPath $VenvDir) {
        Remove-Item -Recurse -Force $VenvDir
    }

    $BasePython = Resolve-BasePython311X64
    $VenvArguments = @($BasePython.Prefix) + @('-m', 'venv', $VenvDir)
    & $BasePython.File @VenvArguments
    Assert-NativeExitCode 'Create Python 3.11 x64 build environment'

    if (-not (Test-Python311X64 -Executable $PythonExe)) {
        throw "The build environment was created but is not Python 3.11 x64: $PythonExe"
    }
}


function Install-PinnedPyInstaller {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$WorkspaceRoot
    )

    $ExpectedVersion = '6.21.0'
    $PinnedPyInstallerRequirement = 'pyinstaller==6.21.0'
    $ExpectedSha256 = '7fae06c494ce0ebfe6bd3055c0e409def884f63af2e3705d06bd431ad9237fc7'
    $WheelName = 'pyinstaller-6.21.0-py3-none-win_amd64.whl'
    $OfficialWheelUrl = 'https://files.pythonhosted.org/packages/c1/fa/ca1d7e5257dd8566a9dfc0dfb02f8a8075eeb53d4b2d3c579f1276759042/pyinstaller-6.21.0-py3-none-win_amd64.whl'
    $DownloadRoot = Join-Path $WorkspaceRoot 'downloads'
    $WheelPath = Join-Path $DownloadRoot $WheelName

    New-Item -ItemType Directory -Force -Path $DownloadRoot | Out-Null

    function Test-PyInstallerWheelHash {
        param([Parameter(Mandatory = $true)][string]$Path)
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
        $ActualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        return ($ActualHash -eq $ExpectedSha256)
    }

    $ConfiguredWheel = [string]$env:HERFY_PYINSTALLER_WHEEL
    if (-not [string]::IsNullOrWhiteSpace($ConfiguredWheel)) {
        $ConfiguredWheel = [System.IO.Path]::GetFullPath($ConfiguredWheel)
        if (-not (Test-PyInstallerWheelHash -Path $ConfiguredWheel)) {
            throw "HERFY_PYINSTALLER_WHEEL is missing or has the wrong SHA256: $ConfiguredWheel"
        }
        if (-not $ConfiguredWheel.Equals($WheelPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            Copy-Item -Force -LiteralPath $ConfiguredWheel -Destination $WheelPath
        }
    }

    if (-not (Test-PyInstallerWheelHash -Path $WheelPath)) {
        Remove-Item -Force -LiteralPath $WheelPath -ErrorAction SilentlyContinue
        $PreviousSecurityProtocol = [Net.ServicePointManager]::SecurityProtocol
        try {
            [Net.ServicePointManager]::SecurityProtocol = (
                $PreviousSecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            )
            Write-Host "HERFY_PYINSTALLER_DOWNLOAD_BEGIN url=$OfficialWheelUrl"
            Invoke-WebRequest -UseBasicParsing -Uri $OfficialWheelUrl -OutFile $WheelPath
        }
        catch {
            Remove-Item -Force -LiteralPath $WheelPath -ErrorAction SilentlyContinue
            Write-Warning "Direct PyInstaller wheel download failed: $($_.Exception.Message)"
        }
        finally {
            [Net.ServicePointManager]::SecurityProtocol = $PreviousSecurityProtocol
        }
    }

    if (Test-PyInstallerWheelHash -Path $WheelPath) {
        & $Python -m pip install --disable-pip-version-check --no-deps --force-reinstall $WheelPath
        Assert-NativeExitCode 'Install verified PyInstaller wheel'
        Write-Host "HERFY_PYINSTALLER_LOCAL_WHEEL_OK path=$WheelPath sha256=$ExpectedSha256"
    }
    else {
        Write-Warning 'The direct wheel could not be downloaded; trying the official PyPI index with isolated pip configuration.'
        & $Python -m pip install --disable-pip-version-check --isolated --index-url 'https://pypi.org/simple' --prefer-binary --only-binary=:all: $PinnedPyInstallerRequirement
        Assert-NativeExitCode 'Install PyInstaller from official PyPI index'
        Write-Host 'HERFY_PYINSTALLER_OFFICIAL_INDEX_OK'
    }

    & $Python -c "import PyInstaller,sys; raise SystemExit(0 if PyInstaller.__version__ == '$ExpectedVersion' else 1)"
    Assert-NativeExitCode 'Verify installed PyInstaller version'
}

function Assert-RequiredSourceFiles {
    $RequiredFiles = @(
        (Join-Path $ProjectRoot 'main.py'),
        (Join-Path $ProjectRoot 'requirements.txt'),
        (Join-Path $ProjectRoot 'requirements-build.txt'),
        (Join-Path $ProjectRoot 'requirements-test.txt'),
        (Join-Path $ProjectRoot 'requirements-quality.txt'),
        (Join-Path $ProjectRoot 'version.json'),
        $ClientSpecFile,
        $AgentSpecFile,
        $InnoFile,
        $PatchBuilder,
        $RuntimeManifestBuilder,
        $MasterVerifier,
        $StructureVerifier,
        (Join-Path $ProjectRoot 'build\release\source_manifest.py'),
        (Join-Path $ProjectRoot 'build\release\verify_source_manifest.py'),
        (Join-Path $ProjectRoot 'pyproject.toml'),
        $ValidationScript,
        $InnoBootstrap,
        $CodeSigningScript,
        (Join-Path $ProjectRoot 'runtime\resources\images\app_icon.ico'),
        (Join-Path $PSScriptRoot 'app_about.txt'),
        (Join-Path $PSScriptRoot 'terms_and_conditions.txt'),
        (Join-Path $PSScriptRoot 'assets\wizard_side.bmp'),
        (Join-Path $PSScriptRoot 'assets\wizard_header.bmp')
    )
    foreach ($RequiredFile in $RequiredFiles) {
        if (-not (Test-Path -LiteralPath $RequiredFile)) {
            throw "Required build input is missing: $RequiredFile"
        }
    }
}

function Wait-NativeProcess {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)][string]$Step
    )
    if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        throw "$Step timed out after $TimeoutSeconds seconds."
    }
    if ($Process.ExitCode -ne 0) {
        throw "$Step failed with exit code $($Process.ExitCode)."
    }
}

function Remove-DirectoryWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 60)][int]$Attempts = 20,
        [ValidateRange(50, 5000)][int]$DelayMilliseconds = 250
    )

    if (-not (Test-Path -LiteralPath $Path)) { return }
    for ($Attempt = 1; $Attempt -le $Attempts; $Attempt++) {
        try {
            Remove-Item -Recurse -Force -LiteralPath $Path -ErrorAction Stop
            return
        }
        catch {
            if ($Attempt -eq $Attempts) {
                throw "Failed to remove directory after $Attempts attempts: $Path. $($_.Exception.Message)"
            }
            Start-Sleep -Milliseconds $DelayMilliseconds
        }
    }
}

function Assert-NonEmptyFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label was not produced: $Path"
    }
    if ((Get-Item -LiteralPath $Path).Length -le 0) {
        throw "$Label is empty: $Path"
    }
}

function Write-PyInstallerVersionResource {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$FileDescription,
        [Parameter(Mandatory = $true)][string]$OriginalFilename
    )

    $Parts = @($Version.Split('.') | ForEach-Object { [int]$_ })
    if ($Parts.Count -gt 4) { throw "Version has more than four numeric components: $Version" }
    while ($Parts.Count -lt 4) { $Parts += 0 }
    $VersionTuple = "$($Parts[0]), $($Parts[1]), $($Parts[2]), $($Parts[3])"
    $FileVersion = "$($Parts[0]).$($Parts[1]).$($Parts[2]).$($Parts[3])"
    $Content = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($VersionTuple),
    prodvers=($VersionTuple),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName', u'Herfy'),
          StringStruct(u'FileDescription', u'$FileDescription'),
          StringStruct(u'FileVersion', u'$FileVersion'),
          StringStruct(u'InternalName', u'$OriginalFilename'),
          StringStruct(u'LegalCopyright', u'Copyright Herfy'),
          StringStruct(u'OriginalFilename', u'$OriginalFilename'),
          StringStruct(u'ProductName', u'Herfy Client'),
          StringStruct(u'ProductVersion', u'$FileVersion')
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@
    $Parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}

function Assert-WindowsExecutable {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$ExpectedVersion = ''
    )

    Assert-NonEmptyFile -Path $Path -Label $Label
    $Stream = [System.IO.File]::OpenRead($Path)
    try {
        if ($Stream.ReadByte() -ne 0x4D -or $Stream.ReadByte() -ne 0x5A) {
            throw "$Label is not a valid Windows PE executable: $Path"
        }
    }
    finally {
        $Stream.Dispose()
    }

    if (-not [string]::IsNullOrWhiteSpace($ExpectedVersion)) {
        $VersionParts = @($ExpectedVersion.Split('.') | ForEach-Object { [int]$_ })
        while ($VersionParts.Count -lt 4) { $VersionParts += 0 }
        if ($VersionParts.Count -ne 4) { throw "Invalid expected Windows version: $ExpectedVersion" }
        $ExpectedFourPartVersion = ($VersionParts -join '.')
        $VersionInfo = (Get-Item -LiteralPath $Path).VersionInfo
        $Candidates = @([string]$VersionInfo.FileVersion, [string]$VersionInfo.ProductVersion) |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        if (-not ($Candidates | Where-Object { $_ -eq $ExpectedVersion -or $_ -eq $ExpectedFourPartVersion })) {
            throw "$Label does not contain the exact Windows version $ExpectedVersion. FileVersion='$($VersionInfo.FileVersion)' ProductVersion='$($VersionInfo.ProductVersion)'"
        }
    }
}

function Quote-NativeArgument {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value.Contains('"')) { throw "Native argument contains an unsupported quote: $Value" }
    return '"' + $Value + '"'
}

function Invoke-FrozenAgentPatchSmoke {
    param(
        [Parameter(Mandatory = $true)][string]$AgentExe,
        [Parameter(Mandatory = $true)][string]$PatchPath,
        [Parameter(Mandatory = $true)][string]$RuntimeDir,
        [Parameter(Mandatory = $true)][string]$Version
    )

    $SmokeRoot = Join-Path $BuildDir 'frozen-agent-patch-smoke'
    Remove-DirectoryWithRetry -Path $SmokeRoot
    New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
    try {
        [System.IO.File]::WriteAllBytes((Join-Path $SmokeRoot 'HerfyClient.exe'), [byte[]](1, 2, 3, 4))
        $InstalledAgentExe = Join-Path $SmokeRoot 'HerfyClientUpdateAgent.exe'
        Copy-Item -Force -LiteralPath $AgentExe -Destination $InstalledAgentExe
        [System.IO.File]::WriteAllBytes((Join-Path $SmokeRoot 'stale-runtime.dll'), [byte[]](9, 10, 11))
        [System.IO.File]::WriteAllBytes((Join-Path $SmokeRoot 'unins000.exe'), [byte[]](12, 13, 14))
        [System.IO.File]::WriteAllBytes((Join-Path $SmokeRoot 'unins001.dat'), [byte[]](15, 16, 17))
        [System.IO.File]::WriteAllText((Join-Path $SmokeRoot 'installer_defaults.ini'), "language=ar`r`n")
        $InstallerDocuments = Join-Path $SmokeRoot 'installer'
        New-Item -ItemType Directory -Force -Path $InstallerDocuments | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $InstallerDocuments 'terms_and_conditions.txt'), 'fixture')

        $PatchHash = (Get-FileHash -LiteralPath $PatchPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $PatchSize = (Get-Item -LiteralPath $PatchPath).Length
        $RestartPath = Join-Path $SmokeRoot 'HerfyClient.exe'
        $ArgumentList = @(
            '--apply', (Quote-NativeArgument $PatchPath),
            '--root', (Quote-NativeArgument $SmokeRoot),
            '--restart', (Quote-NativeArgument $RestartPath),
            '--wait', '10',
            '--sha256', $PatchHash,
            '--expected-size', [string]$PatchSize,
            '--validation-no-restart'
        )
        # Run the agent from the simulated install root so Windows must release
        # the actual running executable before complete_update.cmd replaces it.
        # The validation-only flag prevents the patched GUI from being launched;
        # the agent accepts it only while this explicit environment marker exists.
        $PreviousAgentValidation = $env:HERFY_UPDATE_AGENT_VALIDATION
        $env:HERFY_UPDATE_AGENT_VALIDATION = '1'
        try {
            $Process = Start-Process -FilePath $InstalledAgentExe -ArgumentList $ArgumentList -PassThru
            Wait-NativeProcess -Process $Process -TimeoutSeconds 90 -Step 'Frozen update agent runtime-patch apply test'
        }
        finally {
            $env:HERFY_UPDATE_AGENT_VALIDATION = $PreviousAgentValidation
        }

        $ExpectedAgentHash = (Get-FileHash -LiteralPath $AgentExe -Algorithm SHA256).Hash
        $ExpectedClientHash = (Get-FileHash -LiteralPath (Join-Path $RuntimeDir 'HerfyClient.exe') -Algorithm SHA256).Hash
        $Deadline = [DateTime]::UtcNow.AddSeconds(60)
        do {
            Start-Sleep -Milliseconds 250
            $InstalledAgent = Join-Path $SmokeRoot 'HerfyClientUpdateAgent.exe'
            $PendingAgent = Join-Path $SmokeRoot '.pending_update\HerfyClientUpdateAgent.exe'
            $InstalledHash = if (Test-Path -LiteralPath $InstalledAgent) { (Get-FileHash -LiteralPath $InstalledAgent -Algorithm SHA256).Hash } else { '' }
            $SelfReplaceComplete = ($InstalledHash -eq $ExpectedAgentHash) -and (-not (Test-Path -LiteralPath $PendingAgent))
        } while ((-not $SelfReplaceComplete) -and ([DateTime]::UtcNow -lt $Deadline))

        if (-not $SelfReplaceComplete) { throw 'Frozen update agent did not complete its self-replacement contract.' }
        $InstalledClient = Join-Path $SmokeRoot 'HerfyClient.exe'
        if ((Get-FileHash -LiteralPath $InstalledClient -Algorithm SHA256).Hash -ne $ExpectedClientHash) {
            throw 'Frozen update agent did not install the expected HerfyClient.exe.'
        }
        if (Test-Path -LiteralPath (Join-Path $SmokeRoot 'stale-runtime.dll')) {
            throw 'Frozen update agent left a stale runtime file behind.'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $SmokeRoot 'unins000.exe'))) {
            throw 'Frozen update agent removed the installer uninstaller executable.'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $SmokeRoot 'unins001.dat'))) {
            throw 'Frozen update agent removed numbered Inno uninstaller data.'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $SmokeRoot 'installer_defaults.ini'))) {
            throw 'Frozen update agent removed installer defaults.'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $SmokeRoot 'installer\terms_and_conditions.txt'))) {
            throw 'Frozen update agent removed installer-managed documents.'
        }
        $InstalledVersion = Get-Content -Raw -Encoding UTF8 (Join-Path $SmokeRoot 'version.json') | ConvertFrom-Json
        if ([string]$InstalledVersion.app_version -ne $Version) {
            throw "Frozen update agent installed version '$($InstalledVersion.app_version)' instead of '$Version'."
        }
        Write-Host "HERFY_FROZEN_AGENT_PATCH_SMOKE_OK version=$Version"
    }
    finally {
        Remove-DirectoryWithRetry -Path $SmokeRoot -Attempts 30 -DelayMilliseconds 250
    }
}


function Invoke-InstallerSmoke {
    param(
        [Parameter(Mandatory = $true)][string]$SetupPath,
        [Parameter(Mandatory = $true)][string]$Version,
        [AllowNull()][hashtable]$SigningSession
    )

    $SmokeRoot = Join-Path $BuildDir 'installed-runtime-smoke'
    Remove-DirectoryWithRetry -Path $SmokeRoot
    New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
    try {
        # Seed a mixed previous installation to verify that the installer removes
        # stale source modules and binaries before copying the new frozen runtime.
        New-Item -ItemType Directory -Force -Path (Join-Path $SmokeRoot 'presentation') | Out-Null
        [System.IO.File]::WriteAllBytes((Join-Path $SmokeRoot 'HerfyClient.exe'), [byte[]](1, 2, 3, 4))
        [System.IO.File]::WriteAllText((Join-Path $SmokeRoot 'presentation\stale_module.py'), 'stale')
        [System.IO.File]::WriteAllBytes((Join-Path $SmokeRoot 'stale-runtime.dll'), [byte[]](5, 6, 7, 8))
        [System.IO.File]::WriteAllText(
            (Join-Path $SmokeRoot 'runtime_files.txt'),
            "HerfyClient.exe`npresentation/stale_module.py`nstale-runtime.dll`n"
        )

        $InstallArguments = @(
            '/VERYSILENT',
            '/SUPPRESSMSGBOXES',
            '/NORESTART',
            '/SP-',
            ("/DIR=" + (Quote-NativeArgument $SmokeRoot))
        )
        $InstallProcess = Start-Process -FilePath $SetupPath -ArgumentList $InstallArguments -PassThru
        Wait-NativeProcess -Process $InstallProcess -TimeoutSeconds 180 -Step 'Silent installer smoke test'

        $InstalledClient = Join-Path $SmokeRoot 'HerfyClient.exe'
        $InstalledAgent = Join-Path $SmokeRoot 'HerfyClientUpdateAgent.exe'
        Assert-WindowsExecutable -Path $InstalledClient -Label 'Installed Herfy Client' -ExpectedVersion $Version
        Assert-WindowsExecutable -Path $InstalledAgent -Label 'Installed update agent' -ExpectedVersion $Version
        if ($null -ne $SigningSession -and [bool]$SigningSession.Enabled) {
            Assert-HerfyAuthenticodeSignature -Session $SigningSession -Path $InstalledClient -Label 'installed-client-executable'
            Assert-HerfyAuthenticodeSignature -Session $SigningSession -Path $InstalledAgent -Label 'installed-update-agent-executable'
        }
        $InstalledManifestPath = Join-Path $SmokeRoot 'runtime_files.txt'
        Assert-NonEmptyFile -Path $InstalledManifestPath -Label 'Installed runtime manifest'
        $SmokeRootFull = [System.IO.Path]::GetFullPath($SmokeRoot).TrimEnd('\', '/')
        $SmokeRootPrefix = $SmokeRootFull + [System.IO.Path]::DirectorySeparatorChar
        $InstalledManifestPaths = @(
            Get-Content -LiteralPath $InstalledManifestPath -Encoding UTF8 |
                ForEach-Object { [string]$_ } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                ForEach-Object {
                    $Entry = $_.Trim().Replace('/', [System.IO.Path]::DirectorySeparatorChar)
                    $Candidate = [System.IO.Path]::GetFullPath((Join-Path $SmokeRoot $Entry))
                    if (-not $Candidate.StartsWith($SmokeRootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                        throw "Installed runtime manifest entry escapes the install root: $_"
                    }
                    $Candidate
                }
        )
        if ($InstalledManifestPaths.Count -eq 0) {
            throw 'Installed runtime manifest contains no runtime files.'
        }
        if (Test-Path -LiteralPath (Join-Path $SmokeRoot 'presentation\stale_module.py')) {
            throw 'Installer smoke test left a stale Python source module.'
        }
        if (Test-Path -LiteralPath (Join-Path $SmokeRoot 'stale-runtime.dll')) {
            throw 'Installer smoke test left a stale runtime DLL.'
        }
        $SourceLeaks = @(
            Get-ChildItem -LiteralPath $SmokeRoot -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Extension.ToLowerInvariant() -in @('.py', '.pyc', '.pyo') }
        )
        if ($SourceLeaks.Count -ne 0) {
            throw "Installed runtime contains source/cache files: $($SourceLeaks.FullName -join ', ')"
        }

        $CheckFile = Join-Path $BuildDir 'installed-runtime-self-check.json'
        Remove-Item -Force -LiteralPath $CheckFile -ErrorAction SilentlyContinue
        $PreviousQtPlatform = $env:QT_QPA_PLATFORM
        $PreviousSelfCheckFile = $env:HERFY_SELF_CHECK_FILE
        $env:QT_QPA_PLATFORM = 'offscreen'
        $env:HERFY_SELF_CHECK_FILE = $CheckFile
        try {
            $CheckProcess = Start-Process -FilePath $InstalledClient -ArgumentList '--self-check' -PassThru
            Wait-NativeProcess -Process $CheckProcess -TimeoutSeconds 120 -Step 'Installed runtime self-check'
        }
        finally {
            $env:QT_QPA_PLATFORM = $PreviousQtPlatform
            $env:HERFY_SELF_CHECK_FILE = $PreviousSelfCheckFile
        }
        if (-not (Test-Path -LiteralPath $CheckFile -PathType Leaf)) {
            throw 'Installed runtime self-check did not create a result file.'
        }
        $Check = Get-Content -Raw -Encoding UTF8 $CheckFile | ConvertFrom-Json
        if (
            [string]$Check.status -ne 'ok' -or
            [string]$Check.version -ne $Version -or
            -not [bool]$Check.frozen -or
            @($Check.critical_missing).Count -ne 0
        ) {
            throw "Installed runtime self-check failed: $($Check | ConvertTo-Json -Compress -Depth 10)"
        }

        $Uninstaller = @(
            Get-ChildItem -LiteralPath $SmokeRoot -File -Filter 'unins*.exe' -ErrorAction SilentlyContinue |
                Sort-Object Name
        ) | Select-Object -First 1
        if ($null -eq $Uninstaller) {
            throw 'Installer smoke test did not create an Inno Setup uninstaller.'
        }
        $UninstallMetadataPaths = @(
            Get-ChildItem -LiteralPath $SmokeRoot -File -Filter 'unins*' -ErrorAction SilentlyContinue |
                ForEach-Object { $_.FullName }
        )
        $UninstallProcess = Start-Process `
            -FilePath $Uninstaller.FullName `
            -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') `
            -PassThru
        Wait-NativeProcess -Process $UninstallProcess -TimeoutSeconds 180 -Step 'Silent uninstaller smoke test'

        $ExpectedRemovedPaths = @(
            $InstalledManifestPaths + @($InstalledManifestPath) + $UninstallMetadataPaths
        ) | Select-Object -Unique
        $RemainingInstalledPaths = @()
        for ($Attempt = 1; $Attempt -le 120; $Attempt++) {
            $RemainingInstalledPaths = @(
                $ExpectedRemovedPaths |
                    Where-Object { Test-Path -LiteralPath $_ }
            )
            if ($RemainingInstalledPaths.Count -eq 0) { break }
            Start-Sleep -Milliseconds 500
        }
        if ($RemainingInstalledPaths.Count -ne 0) {
            throw "Uninstaller left installed runtime files: $($RemainingInstalledPaths -join ', ')"
        }

        $ResidualRuntimeBinaries = @()
        if (Test-Path -LiteralPath $SmokeRoot) {
            $ResidualRuntimeBinaries = @(
                Get-ChildItem -LiteralPath $SmokeRoot -Recurse -File -ErrorAction SilentlyContinue |
                    Where-Object {
                        $_.Extension.ToLowerInvariant() -in @('.exe', '.dll', '.pyd') -or
                        $_.Name -like 'unins*'
                    }
            )
        }
        if ($ResidualRuntimeBinaries.Count -ne 0) {
            throw "Uninstaller left frozen runtime binaries or metadata: $($ResidualRuntimeBinaries.FullName -join ', ')"
        }
        Write-Host "HERFY_INSTALLER_RUNTIME_SMOKE_OK version=$Version root=$SmokeRoot"
    }
    finally {
        Remove-DirectoryWithRetry -Path $SmokeRoot -Attempts 30 -DelayMilliseconds 250
    }
}

Push-Location $ProjectRoot
try {
    $Version = Read-AppVersion
    if ($Version -ne $ExpectedVersion) { throw "Expected version $ExpectedVersion, got $Version" }
    if ($Clean -and $SkipPythonBuild) {
        throw '-Clean cannot be combined with -SkipPythonBuild because cleaning removes the frozen runtime that SkipPythonBuild requires.'
    }

    Assert-RequiredSourceFiles
    Assert-SafeBuildWorkspace -Path $BuildWorkspaceRoot -MinimumFreeSpaceGb 4
    $BuildLockStream = Enter-BuildLock -Path $BuildLockPath

    # Resolve expensive prerequisites before changing any previous build output.
    $Iscc = $null
    if (-not $SkipInno) {
        $Iscc = Resolve-InnoSetupCompiler -InstallIfMissing:(-not $NoAutoInstallBuildTools)
        Write-Host "HERFY_INNO_SETUP_OK compiler=$Iscc"
    }
    if (-not $SkipPythonBuild) {
        # Prove a base interpreter exists before deleting a previously usable venv.
        $null = Resolve-BasePython311X64
    }

    if ($Clean) {
        Remove-DirectoryWithRetry -Path $BuildWorkspaceRoot
        Remove-DirectoryWithRetry -Path $OutputDir
        Write-Host "HERFY_CLEAN_BUILD_ROOT_OK workspace=$BuildWorkspaceRoot output=removed venv=recreated"
    }

    New-Item -ItemType Directory -Force -Path $BuildWorkspaceRoot, $OutputDir | Out-Null
    $ExpectedSigningLabels = @('client-executable', 'update-agent-executable')
    if (-not $SkipInno) { $ExpectedSigningLabels += 'installer' }
    $SigningSession = New-HerfyCodeSigningSession `
        -StatusPath $SigningStatusPath `
        -ExpectedLabels $ExpectedSigningLabels
    $BuildTempDir = Join-Path $BuildWorkspaceRoot 'tmp'
    New-Item -ItemType Directory -Force -Path $BuildTempDir | Out-Null

    $PreviousTemp = $env:TEMP
    $PreviousTmp = $env:TMP
    $PreviousPipCache = $env:PIP_CACHE_DIR
    $PreviousBuildPython = $env:HERFY_BUILD_PYTHON

    $env:TEMP = $BuildTempDir
    $env:TMP = $BuildTempDir
    $env:PIP_CACHE_DIR = Join-Path $BuildWorkspaceRoot 'pip-cache'
    $env:HERFY_BUILD_PYTHON = $PythonExe

    Write-Host "HERFY_SHORT_BUILD_ROOT_OK workspace=$BuildWorkspaceRoot venv=$VenvDir"

    if (-not $SkipPythonBuild) {
        Ensure-BuildPython

        & $PythonExe -m pip install --disable-pip-version-check --upgrade 'pip==25.3'
        Assert-NativeExitCode 'Upgrade pip'

        # Install runtime, test, and quality dependencies.  PyInstaller remains
        # pinned and verified by Install-PinnedPyInstaller below.
        $DependencyPackages = @(
            'altgraph==0.17.5',
            'pefile==2024.8.26',
            'pyinstaller-hooks-contrib==2026.6',
            'pywin32-ctypes==0.2.3'
        )
        $RuntimeRequirements = Join-Path $ProjectRoot 'requirements.txt'
        $TestRequirements = Join-Path $ProjectRoot 'requirements-test.txt'
        $QualityRequirements = Join-Path $ProjectRoot 'requirements-quality.txt'
        $InstallArguments = @(
            '-m', 'pip', 'install', '--disable-pip-version-check',
            '--prefer-binary', '--only-binary=:all:',
            '-r', $RuntimeRequirements,
            '-r', $TestRequirements,
            '-r', $QualityRequirements
        ) + $DependencyPackages
        & $PythonExe @InstallArguments
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'The configured pip source failed; retrying dependencies from official PyPI.'
            $InstallArguments = @(
                '-m', 'pip', 'install', '--disable-pip-version-check',
                '--isolated', '--index-url', 'https://pypi.org/simple',
                '--prefer-binary', '--only-binary=:all:',
                '-r', $RuntimeRequirements,
                '-r', $TestRequirements,
                '-r', $QualityRequirements
            ) + $DependencyPackages
            & $PythonExe @InstallArguments
        }
        Assert-NativeExitCode 'Install runtime, test, and quality dependencies'
        Install-PinnedPyInstaller -Python $PythonExe -WorkspaceRoot $BuildWorkspaceRoot
        & $PythonExe -m pip check
        Assert-NativeExitCode 'Validate installed build dependencies'

        # One canonical validation pipeline owns compile, tests, architecture,
        # runtime contracts, Qt/Windows probes, linting, and final hygiene.
        & $ValidationScript -Python $PythonExe
        Assert-NativeExitCode 'Run canonical source validation pipeline'

        $ClientWorkDir = Join-Path $BuildDir 'client'
        $AgentDistDir = Join-Path $BuildDir 'agent-dist'
        $AgentWorkDir = Join-Path $BuildDir 'agent'
        $ClientVersionInfo = Join-Path $BuildDir 'client-version-info.txt'
        $AgentVersionInfo = Join-Path $BuildDir 'agent-version-info.txt'
        Write-PyInstallerVersionResource -Path $ClientVersionInfo -Version $Version -FileDescription 'Herfy Client Desktop Application' -OriginalFilename 'HerfyClient.exe'
        Write-PyInstallerVersionResource -Path $AgentVersionInfo -Version $Version -FileDescription 'Herfy Client Update Agent' -OriginalFilename 'HerfyClientUpdateAgent.exe'

        $PreviousVersionInfoFile = $env:HERFY_PYINSTALLER_VERSION_FILE
        try {
            $env:HERFY_PYINSTALLER_VERSION_FILE = $ClientVersionInfo
            & $PythonExe -m PyInstaller --noconfirm --clean --distpath $DistRoot --workpath $ClientWorkDir $ClientSpecFile
            Assert-NativeExitCode 'Build HerfyClient.exe'

            $env:HERFY_PYINSTALLER_VERSION_FILE = $AgentVersionInfo
            & $PythonExe -m PyInstaller --noconfirm --clean --distpath $AgentDistDir --workpath $AgentWorkDir $AgentSpecFile
            Assert-NativeExitCode 'Build HerfyClientUpdateAgent.exe'
        }
        finally {
            $env:HERFY_PYINSTALLER_VERSION_FILE = $PreviousVersionInfoFile
        }

        Assert-NoMissingLocalPyInstallerModules -WorkPath $ClientWorkDir -Label 'Herfy Client PyInstaller analysis'
        Assert-NoMissingLocalPyInstallerModules -WorkPath $AgentWorkDir -Label 'Herfy update agent PyInstaller analysis'

        $BuiltAgent = Join-Path $AgentDistDir 'HerfyClientUpdateAgent.exe'
        Assert-WindowsExecutable -Path $BuiltAgent -Label 'PyInstaller update agent' -ExpectedVersion $Version
        Copy-Item -Force -LiteralPath $BuiltAgent -Destination (Join-Path $DistDir 'HerfyClientUpdateAgent.exe')
    }
    elseif (-not (Test-Python311X64 -Executable $PythonExe) -and -not $SkipPatch) {
        throw "SkipPythonBuild with runtime-patch creation requires an existing short build environment at $VenvDir containing Python 3.11 x64. Remove -SkipPythonBuild or add -SkipPatch."
    }

    $ClientExe = Join-Path $DistDir 'HerfyClient.exe'
    $AgentExe = Join-Path $DistDir 'HerfyClientUpdateAgent.exe'
    $RuntimeVersionFile = Join-Path $DistDir 'version.json'
    Assert-WindowsExecutable -Path $ClientExe -Label 'Herfy Client executable' -ExpectedVersion $Version
    Assert-WindowsExecutable -Path $AgentExe -Label 'Herfy update agent executable' -ExpectedVersion $Version
    Assert-NonEmptyFile -Path $RuntimeVersionFile -Label 'Runtime version metadata'

    $RuntimeVersion = Get-Content -Raw -Encoding UTF8 $RuntimeVersionFile | ConvertFrom-Json
    if ([string]$RuntimeVersion.app_version -ne $Version) {
        throw "Frozen runtime version mismatch. Expected $Version, found $($RuntimeVersion.app_version)."
    }

    # Verify the standalone update agent can start and parse its command line.
    $AgentSmokeProcess = Start-Process -FilePath $AgentExe -ArgumentList '--help' -PassThru
    Wait-NativeProcess -Process $AgentSmokeProcess -TimeoutSeconds 30 -Step 'Frozen update agent smoke test'

    $SelfCheckFile = Join-Path $BuildDir 'frozen-self-check.json'
    New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
    Remove-Item -Force -LiteralPath $SelfCheckFile -ErrorAction SilentlyContinue

    $PreviousQtPlatform = $env:QT_QPA_PLATFORM
    $PreviousSelfCheckFile = $env:HERFY_SELF_CHECK_FILE
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:HERFY_SELF_CHECK_FILE = $SelfCheckFile
    try {
        $SelfCheckProcess = Start-Process -FilePath $ClientExe -ArgumentList '--self-check' -PassThru
        Wait-NativeProcess -Process $SelfCheckProcess -TimeoutSeconds $SelfCheckTimeoutSeconds -Step 'Frozen executable self-check'
    }
    finally {
        $env:QT_QPA_PLATFORM = $PreviousQtPlatform
        $env:HERFY_SELF_CHECK_FILE = $PreviousSelfCheckFile
    }

    if (-not (Test-Path -LiteralPath $SelfCheckFile)) {
        throw "Frozen executable self-check did not create $SelfCheckFile"
    }
    $SelfCheck = Get-Content -Raw -Encoding UTF8 $SelfCheckFile | ConvertFrom-Json
    if ([string]$SelfCheck.status -ne 'ok') {
        throw "Frozen executable self-check failed: $($SelfCheck | ConvertTo-Json -Compress -Depth 10)"
    }
    if ([string]$SelfCheck.version -ne $Version) {
        throw "Frozen executable self-check returned version '$($SelfCheck.version)'; expected '$Version'."
    }
    if (-not [bool]$SelfCheck.frozen) {
        throw 'Frozen executable self-check reported frozen=false.'
    }
    if (@($SelfCheck.critical_missing).Count -ne 0) {
        throw "Frozen executable self-check reported missing critical items: $(@($SelfCheck.critical_missing) -join ', ')"
    }

    Optimize-FrozenQtRuntime -RuntimeDir $DistDir

    if (Test-Path -LiteralPath (Join-Path $DistDir '_internal')) {
        throw 'Frozen runtime path drift detected: _internal must not exist.'
    }
    foreach ($RootRuntimeEntry in @(
        'PyQt5',
        'resources',
        'HerfyClient.exe',
        'HerfyClientUpdateAgent.exe',
        'version.json'
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $DistDir $RootRuntimeEntry))) {
            throw "Root-level frozen runtime entry is missing: $RootRuntimeEntry"
        }
    }
    Write-Host 'HERFY_ROOT_LEVEL_FROZEN_RUNTIME_OK'

    $NotificationCheckFile = Join-Path $BuildDir 'frozen-notification-self-check.json'
    Remove-Item -Force -LiteralPath $NotificationCheckFile -ErrorAction SilentlyContinue

    $PreviousNotificationCheckFile = $env:HERFY_NOTIFICATION_SELF_CHECK_FILE
    $PreviousNotificationQtPlatform = $env:QT_QPA_PLATFORM
    $env:HERFY_NOTIFICATION_SELF_CHECK_FILE = $NotificationCheckFile
    $env:QT_QPA_PLATFORM = 'offscreen'
    try {
        $NotificationCheckProcess = Start-Process `
            -FilePath $ClientExe `
            -ArgumentList '--notification-self-check' `
            -PassThru
        Wait-NativeProcess `
            -Process $NotificationCheckProcess `
            -TimeoutSeconds $SelfCheckTimeoutSeconds `
            -Step 'Frozen notification runtime self-check'
    }
    finally {
        $env:HERFY_NOTIFICATION_SELF_CHECK_FILE = $PreviousNotificationCheckFile
        $env:QT_QPA_PLATFORM = $PreviousNotificationQtPlatform
    }

    if (-not (Test-Path -LiteralPath $NotificationCheckFile)) {
        throw "Frozen notification self-check did not create $NotificationCheckFile"
    }

    $NotificationCheck = Get-Content -Raw -Encoding UTF8 $NotificationCheckFile |
        ConvertFrom-Json
    if ([string]$NotificationCheck.status -ne 'ok') {
        throw "Frozen notification runtime self-check failed: $($NotificationCheck | ConvertTo-Json -Compress -Depth 12)"
    }
    if ([string]$NotificationCheck.version -ne $Version) {
        throw "Frozen notification self-check version mismatch: $($NotificationCheck.version)"
    }
    if (-not [bool]$NotificationCheck.frozen) {
        throw 'Frozen notification self-check reported frozen=false.'
    }
    if (@($NotificationCheck.errors).Count -ne 0) {
        throw "Frozen notification self-check errors: $(@($NotificationCheck.errors) -join ', ')"
    }
    if (-not [bool]$NotificationCheck.qt.imports_ok) {
        throw 'Frozen notification self-check could not import required Qt modules.'
    }
    if (-not [bool]$NotificationCheck.qt.print_support_available) {
        throw 'Frozen QtPrintSupport is unavailable.'
    }
    if (-not [bool]$NotificationCheck.qt.multimedia_player_available) {
        throw 'Frozen QtMultimedia is unavailable.'
    }
    if (-not [bool]$NotificationCheck.paths.separate_roots) {
        throw 'Frozen runtime data and installation roots are not separated.'
    }
    Write-Host 'HERFY_FROZEN_NOTIFICATION_RUNTIME_OK thresholds=sounds=qt=tray-contract=roaming'

    Invoke-HerfyCodeSigning -Session $SigningSession -Path $ClientExe -Label 'client-executable'
    Invoke-HerfyCodeSigning -Session $SigningSession -Path $AgentExe -Label 'update-agent-executable'
    Assert-WindowsExecutable -Path $ClientExe -Label 'Signed Herfy Client executable' -ExpectedVersion $Version
    Assert-WindowsExecutable -Path $AgentExe -Label 'Signed Herfy update agent executable' -ExpectedVersion $Version

    & $PythonExe $RuntimeManifestBuilder --runtime $DistDir
    Assert-NativeExitCode 'Generate frozen runtime manifest'
    $RuntimeManifestPath = Join-Path $DistDir 'runtime_files.txt'
    Assert-NonEmptyFile -Path $RuntimeManifestPath -Label 'Frozen runtime manifest'
    Write-Host "HERFY_RUNTIME_MANIFEST_OK path=$RuntimeManifestPath"

    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $PatchPath = Join-Path $OutputDir "HerfyClientRuntime-$Version.zip"
    if ($SkipPatch) {
        Remove-Item -Force -LiteralPath $PatchPath -ErrorAction SilentlyContinue
    }
    else {
        & $PythonExe $PatchBuilder --source $DistDir --output $PatchPath --version $Version
        Assert-NativeExitCode 'Build runtime patch'
        Assert-NonEmptyFile -Path $PatchPath -Label 'Runtime patch'
        Invoke-FrozenAgentPatchSmoke -AgentExe $AgentExe -PatchPath $PatchPath -RuntimeDir $DistDir -Version $Version
    }

    $SetupPath = Join-Path $OutputDir "HerfyClientSetup-$Version.exe"
    if ($SkipInno) {
        Remove-Item -Force -LiteralPath $SetupPath -ErrorAction SilentlyContinue
    }
    else {
        & $Iscc "/DSourceDir=$DistDir" "/DOutputDir=$OutputDir" "/DSetupVersion=$Version" $InnoFile
        Assert-NativeExitCode 'Build Inno Setup installer'
        Assert-WindowsExecutable -Path $SetupPath -Label 'Inno Setup installer' -ExpectedVersion $Version
        Invoke-HerfyCodeSigning -Session $SigningSession -Path $SetupPath -Label 'installer'
        Assert-WindowsExecutable -Path $SetupPath -Label 'Signed Inno Setup installer' -ExpectedVersion $Version
        Invoke-InstallerSmoke -SetupPath $SetupPath -Version $Version -SigningSession $SigningSession
        Write-Host "HERFY_CUSTOM_INSTALLER_OK $SetupPath"
    }

    if (-not $SkipPatch) {
        Write-Host "HERFY_RUNTIME_PATCH_READY $PatchPath"
    }
    $BuildSucceeded = $true
    Write-Host "HERFY_WINDOWS_BUILD_OK version=$Version runtime=$DistDir"
}
finally {
    try {
        Complete-HerfyCodeSigningSession -Session $SigningSession -BuildSucceeded:$BuildSucceeded
    }
    finally {
        Exit-BuildLock -Stream $BuildLockStream -Path $BuildLockPath
        if (Get-Variable -Name PreviousTemp -ErrorAction SilentlyContinue) {
            $env:TEMP = $PreviousTemp
        }
        if (Get-Variable -Name PreviousTmp -ErrorAction SilentlyContinue) {
            $env:TMP = $PreviousTmp
        }
        if (Get-Variable -Name PreviousPipCache -ErrorAction SilentlyContinue) {
            $env:PIP_CACHE_DIR = $PreviousPipCache
        }
        if (Get-Variable -Name PreviousBuildPython -ErrorAction SilentlyContinue) {
            $env:HERFY_BUILD_PYTHON = $PreviousBuildPython
        }
        Pop-Location
    }
}
