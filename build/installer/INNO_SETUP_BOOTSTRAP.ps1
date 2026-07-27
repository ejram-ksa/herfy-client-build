Set-StrictMode -Version Latest

function Test-HerfyAdministrator {
    try {
        $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
        return $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    }
    catch {
        return $false
    }
}

function Find-InnoSetupCompiler {
    $Candidates = New-Object System.Collections.Generic.List[string]

    if (-not [string]::IsNullOrWhiteSpace($env:HERFY_ISCC_PATH)) {
        $Candidates.Add([string]$env:HERFY_ISCC_PATH)
    }

    foreach ($Base in @(
        ${env:ProgramFiles(x86)},
        $env:ProgramFiles,
        $env:LOCALAPPDATA
    )) {
        if ([string]::IsNullOrWhiteSpace($Base)) { continue }
        foreach ($Relative in @(
            'Inno Setup 6\ISCC.exe',
            'Programs\Inno Setup 6\ISCC.exe',
            'Inno Setup 7\ISCC.exe',
            'Programs\Inno Setup 7\ISCC.exe'
        )) {
            $Candidates.Add((Join-Path $Base $Relative))
        }
    }

    foreach ($RegistryPath in @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe'
    )) {
        if (-not (Test-Path -LiteralPath $RegistryPath)) { continue }
        try {
            $Value = (Get-Item -LiteralPath $RegistryPath).GetValue('')
            if (-not [string]::IsNullOrWhiteSpace([string]$Value)) {
                $Candidates.Add([string]$Value)
            }
        }
        catch { }
    }

    foreach ($UninstallRoot in @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
    )) {
        if (-not (Test-Path -LiteralPath $UninstallRoot)) { continue }
        foreach ($Entry in @(Get-ChildItem -LiteralPath $UninstallRoot -ErrorAction SilentlyContinue)) {
            try {
                $Properties = Get-ItemProperty -LiteralPath $Entry.PSPath -ErrorAction Stop
                if ([string]$Properties.DisplayName -notlike 'Inno Setup*') { continue }
                if (-not [string]::IsNullOrWhiteSpace([string]$Properties.InstallLocation)) {
                    $Candidates.Add((Join-Path ([string]$Properties.InstallLocation) 'ISCC.exe'))
                }
            }
            catch { }
        }
    }

    $Command = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($Command -and -not [string]::IsNullOrWhiteSpace([string]$Command.Source)) {
        $Candidates.Add([string]$Command.Source)
    }

    foreach ($Candidate in $Candidates) {
        if ([string]::IsNullOrWhiteSpace($Candidate)) { continue }
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    return $null
}

function Invoke-HerfyNativeInstaller {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $Process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -Wait -PassThru
    if ($Process.ExitCode -ne 0) {
        throw "$Label failed with exit code $($Process.ExitCode)."
    }
}

function Install-InnoSetup6 {
    Write-Host 'HERFY_BUILD_TOOL_MISSING: Inno Setup compiler was not found. Installing Inno Setup 6 automatically...'
    $IsAdministrator = Test-HerfyAdministrator

    $Winget = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
    if ($Winget) {
        $Scope = if ($IsAdministrator) { 'machine' } else { 'user' }
        $Arguments = @(
            'install',
            '--id', 'JRSoftware.InnoSetup',
            '--exact',
            '--source', 'winget',
            '--scope', $Scope,
            '--silent',
            '--accept-package-agreements',
            '--accept-source-agreements',
            '--disable-interactivity'
        )
        Write-Host "Installing Inno Setup 6 through WinGet (scope=$Scope)..."
        $WingetPath = [string]$Winget.Source
        & $WingetPath @Arguments | Out-Host
        $Compiler = Find-InnoSetupCompiler
        if ($Compiler) { return $Compiler }
        Write-Warning "WinGet did not make ISCC.exe available (exit code $LASTEXITCODE). Trying the next installation method."
    }

    $Chocolatey = Get-Command 'choco.exe' -ErrorAction SilentlyContinue
    if ($Chocolatey -and $IsAdministrator) {
        Write-Host 'Installing Inno Setup 6 through Chocolatey...'
        $ChocolateyPath = [string]$Chocolatey.Source
        & $ChocolateyPath install innosetup -y --no-progress | Out-Host
        $Compiler = Find-InnoSetupCompiler
        if ($Compiler) { return $Compiler }
        Write-Warning "Chocolatey did not make ISCC.exe available (exit code $LASTEXITCODE). Trying the verified direct installer."
    }

    # Verified stable fallback from the Microsoft WinGet community manifest.
    $DownloadUrls = @(
        'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe',
        'https://jrsoftware.org/download.php/innosetup-6.7.3.exe'
    )
    $ExpectedSha256 = '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732'
    $TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('Herfy-InnoSetup-' + [Guid]::NewGuid().ToString('N'))
    $InstallerPath = Join-Path $TempRoot 'innosetup-6.7.3.exe'
    New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
    try {
        Write-Host 'Downloading the verified Inno Setup 6 installer...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $DownloadError = $null
        foreach ($DownloadUrl in $DownloadUrls) {
            try {
                Remove-Item -Force -LiteralPath $InstallerPath -ErrorAction SilentlyContinue
                Invoke-WebRequest -UseBasicParsing -Uri $DownloadUrl -OutFile $InstallerPath
                if (Test-Path -LiteralPath $InstallerPath -PathType Leaf) { break }
            }
            catch {
                $DownloadError = $_
                Write-Warning "Download failed from $DownloadUrl. Trying the next verified source."
            }
        }
        if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
            if ($DownloadError) { throw $DownloadError }
            throw 'The Inno Setup installer download did not produce a file.'
        }
        $ActualSha256 = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualSha256 -ne $ExpectedSha256) {
            throw "Inno Setup installer SHA256 mismatch. Expected $ExpectedSha256, got $ActualSha256."
        }

        $InstallArguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-')
        if ($IsAdministrator) {
            $InstallArguments += '/ALLUSERS'
        }
        else {
            $InstallArguments += '/CURRENTUSER'
        }
        Invoke-HerfyNativeInstaller -FilePath $InstallerPath -ArgumentList $InstallArguments -Label 'Verified Inno Setup 6 installation'
    }
    finally {
        Remove-Item -Recurse -Force -LiteralPath $TempRoot -ErrorAction SilentlyContinue
    }

    $Compiler = Find-InnoSetupCompiler
    if ($Compiler) { return $Compiler }
    throw 'Inno Setup installation completed but ISCC.exe could not be located. Set HERFY_ISCC_PATH to the full ISCC.exe path and rerun the build.'
}

function Resolve-InnoSetupCompiler {
    param([switch]$InstallIfMissing)

    $Compiler = Find-InnoSetupCompiler
    if ($Compiler) { return $Compiler }
    if (-not $InstallIfMissing) {
        throw 'Inno Setup 6 compiler ISCC.exe was not found and automatic build-tool installation was disabled.'
    }
    return (Install-InnoSetup6)
}
