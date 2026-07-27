Set-StrictMode -Version Latest

$script:HerfyCodeSigningOid = '1.3.6.1.5.5.7.3.3'
$script:HerfyDefaultTimestampUrl = 'http://timestamp.digicert.com'

function ConvertTo-HerfyBoolean {
    param(
        [AllowNull()][object]$Value,
        [bool]$Default = $false
    )

    if ($null -eq $Value) { return $Default }
    $Text = ([string]$Value).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($Text)) { return $Default }
    if ($Text -in @('1', 'true', 'yes', 'on')) { return $true }
    if ($Text -in @('0', 'false', 'no', 'off')) { return $false }
    throw "Invalid boolean value '$Value'."
}

function Resolve-HerfySignTool {
    $Configured = ([string]$env:HERFY_SIGNTOOL_PATH).Trim()
    if (-not [string]::IsNullOrWhiteSpace($Configured)) {
        $FullConfigured = [System.IO.Path]::GetFullPath($Configured)
        if (-not (Test-Path -LiteralPath $FullConfigured -PathType Leaf)) {
            throw "HERFY_SIGNTOOL_PATH does not point to a file: $FullConfigured"
        }
        return $FullConfigured
    }

    $Command = Get-Command 'signtool.exe' -ErrorAction SilentlyContinue
    if ($null -ne $Command -and -not [string]::IsNullOrWhiteSpace($Command.Source)) {
        return [System.IO.Path]::GetFullPath([string]$Command.Source)
    }

    $ProgramFilesX86 = [string]${env:ProgramFiles(x86)}
    if (-not [string]::IsNullOrWhiteSpace($ProgramFilesX86)) {
        $SdkBin = Join-Path $ProgramFilesX86 'Windows Kits\10\bin'
        if (Test-Path -LiteralPath $SdkBin -PathType Container) {
            $Candidates = @(
                Get-ChildItem -LiteralPath $SdkBin -Directory -ErrorAction SilentlyContinue |
                    Sort-Object Name -Descending |
                    ForEach-Object { Join-Path $_.FullName 'x64\signtool.exe' } |
                    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
            )
            if ($Candidates.Count -gt 0) {
                return [System.IO.Path]::GetFullPath([string]$Candidates[0])
            }
        }
    }
    return $null
}

function Normalize-HerfyCertificateThumbprint {
    param([Parameter(Mandatory = $true)][string]$Thumbprint)

    $Normalized = ($Thumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
    if ($Normalized -notmatch '^[0-9A-F]{40}$') {
        throw 'The code-signing certificate thumbprint must contain exactly 40 hexadecimal characters.'
    }
    return $Normalized
}

function Get-HerfyCodeSigningCertificate {
    param([Parameter(Mandatory = $true)][string]$Thumbprint)

    $Normalized = Normalize-HerfyCertificateThumbprint -Thumbprint $Thumbprint
    $Certificate = Get-ChildItem -Path 'Cert:\CurrentUser\My' -ErrorAction Stop |
        Where-Object { $_.Thumbprint -eq $Normalized } |
        Select-Object -First 1
    if ($null -eq $Certificate) {
        throw "Code-signing certificate was not found in Cert:\CurrentUser\My: $Normalized"
    }
    if (-not $Certificate.HasPrivateKey) {
        throw "Code-signing certificate does not have an accessible private key: $Normalized"
    }

    $Now = [DateTime]::UtcNow
    if ($Certificate.NotBefore.ToUniversalTime() -gt $Now) {
        throw "Code-signing certificate is not valid yet: $Normalized"
    }
    if ($Certificate.NotAfter.ToUniversalTime() -le $Now) {
        throw "Code-signing certificate has expired: $Normalized"
    }

    $EnhancedKeyUsageOids = @(
        $Certificate.Extensions |
            Where-Object { $_.Oid.Value -eq '2.5.29.37' } |
            ForEach-Object {
                $EnhancedUsage = [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]$_
                $EnhancedUsage.EnhancedKeyUsages | ForEach-Object { $_.Value }
            }
    )
    if ($EnhancedKeyUsageOids -notcontains $script:HerfyCodeSigningOid) {
        throw "Certificate is not authorized for code signing: $Normalized"
    }
    return $Certificate
}

function Import-HerfySigningPfx {
    param(
        [Parameter(Mandatory = $true)][string]$Base64,
        [Parameter(Mandatory = $true)][string]$Password
    )

    if ([string]::IsNullOrWhiteSpace($Password)) {
        throw 'HERFY_SIGNING_PFX_PASSWORD is required when HERFY_SIGNING_PFX_BASE64 is configured.'
    }

    $TemporaryPfx = Join-Path ([System.IO.Path]::GetTempPath()) (
        'herfy-signing-' + [Guid]::NewGuid().ToString('N') + '.pfx'
    )
    $Imported = @()
    try {
        try {
            $Bytes = [Convert]::FromBase64String($Base64.Trim())
        }
        catch {
            throw 'HERFY_SIGNING_PFX_BASE64 is not valid Base64.'
        }
        if ($Bytes.Length -eq 0) { throw 'The configured signing PFX is empty.' }
        [System.IO.File]::WriteAllBytes($TemporaryPfx, $Bytes)
        $SecurePassword = ConvertTo-SecureString -String $Password -AsPlainText -Force
        $Imported = @(
            Import-PfxCertificate `
                -FilePath $TemporaryPfx `
                -CertStoreLocation 'Cert:\CurrentUser\My' `
                -Password $SecurePassword `
                -Exportable:$false `
                -ErrorAction Stop
        )
        $SigningCertificate = $Imported |
            Where-Object {
                $_.HasPrivateKey -and
                @($_.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId.Value }) -contains $script:HerfyCodeSigningOid
            } |
            Select-Object -First 1
        if ($null -eq $SigningCertificate) {
            throw 'The imported PFX does not contain a private code-signing certificate.'
        }
        $ImportedThumbprints = @(
            $Imported |
                Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.Thumbprint) } |
                ForEach-Object { Normalize-HerfyCertificateThumbprint -Thumbprint $_.Thumbprint } |
                Select-Object -Unique
        )
        return [pscustomobject]@{
            SigningThumbprint = Normalize-HerfyCertificateThumbprint -Thumbprint $SigningCertificate.Thumbprint
            ImportedThumbprints = $ImportedThumbprints
        }
    }
    catch {
        foreach ($Certificate in @($Imported)) {
            if ([string]::IsNullOrWhiteSpace([string]$Certificate.Thumbprint)) { continue }
            $ImportedThumbprint = Normalize-HerfyCertificateThumbprint -Thumbprint $Certificate.Thumbprint
            Remove-Item -Force -LiteralPath ("Cert:\CurrentUser\My\" + $ImportedThumbprint) -ErrorAction SilentlyContinue
        }
        throw
    }
    finally {
        if (Test-Path -LiteralPath $TemporaryPfx) {
            Remove-Item -Force -LiteralPath $TemporaryPfx -ErrorAction SilentlyContinue
        }
    }
}

function Write-HerfySigningStatus {
    param([Parameter(Mandatory = $true)][hashtable]$Session)

    $StatusPath = [string]$Session.StatusPath
    $Parent = Split-Path -Parent $StatusPath
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    $Payload = [ordered]@{
        schema_version = 1
        status = [string]$Session.Status
        required = [bool]$Session.Required
        enabled = [bool]$Session.Enabled
        timestamp_url = [string]$Session.TimestampUrl
        certificate_thumbprint = [string]$Session.Thumbprint
        certificate_source = [string]$Session.CertificateSource
        started_utc = [string]$Session.StartedUtc
        completed_utc = [string]$Session.CompletedUtc
        reason = [string]$Session.Reason
        expected_labels = @($Session.ExpectedLabels)
        artifacts = @($Session.Artifacts)
    }
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        $StatusPath,
        ($Payload | ConvertTo-Json -Depth 10),
        $Utf8NoBom
    )
}

function New-HerfyCodeSigningSession {
    param(
        [Parameter(Mandatory = $true)][string]$StatusPath,
        [string[]]$ExpectedLabels = @('client-executable', 'update-agent-executable', 'installer')
    )

    $Required = ConvertTo-HerfyBoolean -Value $env:HERFY_REQUIRE_CODE_SIGNING -Default $false
    $ConfiguredThumbprint = ([string]$env:HERFY_SIGNING_CERT_THUMBPRINT).Trim()
    $PfxBase64 = ([string]$env:HERFY_SIGNING_PFX_BASE64).Trim()
    $PfxPassword = [string]$env:HERFY_SIGNING_PFX_PASSWORD
    $env:HERFY_SIGNING_PFX_BASE64 = ''
    $env:HERFY_SIGNING_PFX_PASSWORD = ''
    $TimestampUrl = ([string]$env:HERFY_TIMESTAMP_URL).Trim()
    if ([string]::IsNullOrWhiteSpace($TimestampUrl)) {
        $TimestampUrl = $script:HerfyDefaultTimestampUrl
    }

    $TimestampUri = $null
    if (-not [Uri]::TryCreate($TimestampUrl, [UriKind]::Absolute, [ref]$TimestampUri)) {
        throw "HERFY_TIMESTAMP_URL is not an absolute URI: $TimestampUrl"
    }
    if ($TimestampUri.Scheme -notin @('http', 'https')) {
        throw 'HERFY_TIMESTAMP_URL must use HTTP or HTTPS.'
    }
    if (-not [string]::IsNullOrWhiteSpace($ConfiguredThumbprint) -and -not [string]::IsNullOrWhiteSpace($PfxBase64)) {
        throw 'Configure either HERFY_SIGNING_CERT_THUMBPRINT or HERFY_SIGNING_PFX_BASE64, not both.'
    }
    if ([string]::IsNullOrWhiteSpace($PfxBase64) -and -not [string]::IsNullOrWhiteSpace($PfxPassword)) {
        throw 'HERFY_SIGNING_PFX_PASSWORD was configured without HERFY_SIGNING_PFX_BASE64.'
    }

    $Session = @{
        StatusPath = [System.IO.Path]::GetFullPath($StatusPath)
        Required = $Required
        Enabled = $false
        Status = 'skipped'
        SignTool = ''
        Thumbprint = ''
        CertificateSource = ''
        ImportedThumbprints = @()
        TimestampUrl = $TimestampUrl
        StartedUtc = [DateTime]::UtcNow.ToString('o')
        CompletedUtc = ''
        Reason = ''
        ExpectedLabels = @($ExpectedLabels)
        Artifacts = [System.Collections.ArrayList]::new()
    }

    try {
        if ([string]::IsNullOrWhiteSpace($ConfiguredThumbprint) -and [string]::IsNullOrWhiteSpace($PfxBase64)) {
            $Session.Reason = 'certificate_not_configured'
            if ($Required) {
                $Session.Status = 'failed'
                throw 'Code signing is required, but no signing certificate was configured.'
            }
            Write-HerfySigningStatus -Session $Session
            Write-Host 'HERFY_CODE_SIGNING_SKIPPED reason=certificate_not_configured'
            return $Session
        }

        if (-not [string]::IsNullOrWhiteSpace($PfxBase64)) {
            $PfxImport = Import-HerfySigningPfx -Base64 $PfxBase64 -Password $PfxPassword
            $Session.Thumbprint = [string]$PfxImport.SigningThumbprint
            $Session.ImportedThumbprints = @($PfxImport.ImportedThumbprints)
            $Session.CertificateSource = 'temporary-pfx-import'
        }
        else {
            $Session.Thumbprint = Normalize-HerfyCertificateThumbprint -Thumbprint $ConfiguredThumbprint
            $Session.CertificateSource = 'current-user-certificate-store'
        }

        $null = Get-HerfyCodeSigningCertificate -Thumbprint $Session.Thumbprint
        $SignTool = Resolve-HerfySignTool
        if ([string]::IsNullOrWhiteSpace([string]$SignTool)) {
            throw 'signtool.exe was not found. Install the Windows SDK signing tools or configure HERFY_SIGNTOOL_PATH.'
        }

        $Session.SignTool = $SignTool
        $Session.Enabled = $true
        $Session.Status = 'pending'
        $Session.Reason = ''
        Write-HerfySigningStatus -Session $Session
        Write-Host "HERFY_CODE_SIGNING_READY signtool=$SignTool timestamp=$TimestampUrl"
        return $Session
    }
    catch {
        $Session.Status = 'failed'
        $Session.Reason = $_.Exception.Message
        $Session.CompletedUtc = [DateTime]::UtcNow.ToString('o')
        Write-HerfySigningStatus -Session $Session
        foreach ($ImportedThumbprint in @($Session.ImportedThumbprints)) {
            Remove-Item -Force -LiteralPath ("Cert:\CurrentUser\My\" + $ImportedThumbprint) -ErrorAction SilentlyContinue
        }
        $Session.ImportedThumbprints = @()
        throw
    }
}

function Assert-HerfyAuthenticodeSignature {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Session,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not [bool]$Session.Enabled) { return }
    $FullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) {
        throw "Cannot verify missing signed artifact: $FullPath"
    }

    $VerifyArguments = @('verify', '/pa', '/all', '/v', $FullPath)
    & ([string]$Session.SignTool) @VerifyArguments
    if ($LASTEXITCODE -ne 0) {
        throw "signtool verify failed with exit code $LASTEXITCODE for $Label."
    }

    $Signature = Get-AuthenticodeSignature -FilePath $FullPath
    if ([string]$Signature.Status -ne 'Valid') {
        throw "Authenticode verification did not return Valid for ${Label}: $($Signature.StatusMessage)"
    }
    if ($null -eq $Signature.SignerCertificate) {
        throw "Authenticode signer certificate is missing for $Label."
    }
    if ($null -eq $Signature.TimeStamperCertificate) {
        throw "RFC 3161 timestamp is missing for $Label."
    }
    $SignerThumbprint = Normalize-HerfyCertificateThumbprint -Thumbprint $Signature.SignerCertificate.Thumbprint
    if ($SignerThumbprint -ne [string]$Session.Thumbprint) {
        throw "Authenticode signer thumbprint mismatch for $Label."
    }
}

function Invoke-HerfyCodeSigning {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Session,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not [bool]$Session.Enabled) { return }
    $FullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) {
        throw "Cannot sign missing artifact: $FullPath"
    }

    try {
        $SignArguments = @(
            'sign', '/sha1', [string]$Session.Thumbprint,
            '/s', 'My', '/fd', 'SHA256',
            '/tr', [string]$Session.TimestampUrl,
            '/td', 'SHA256', '/v', $FullPath
        )
        & ([string]$Session.SignTool) @SignArguments
        if ($LASTEXITCODE -ne 0) {
            throw "signtool sign failed with exit code $LASTEXITCODE for $Label."
        }

        Assert-HerfyAuthenticodeSignature -Session $Session -Path $FullPath -Label $Label

        $Record = [ordered]@{
            label = $Label
            file = [System.IO.Path]::GetFileName($FullPath)
            status = 'passed'
            sha256 = (Get-FileHash -LiteralPath $FullPath -Algorithm SHA256).Hash.ToLowerInvariant()
            size = (Get-Item -LiteralPath $FullPath).Length
            timestamped = $true
        }
        [void]$Session.Artifacts.Add($Record)
        Write-HerfySigningStatus -Session $Session
        Write-Host "HERFY_AUTHENTICODE_OK label=$Label file=$([System.IO.Path]::GetFileName($FullPath))"
    }
    catch {
        $Session.Status = 'failed'
        $Session.Reason = $_.Exception.Message
        $Session.CompletedUtc = [DateTime]::UtcNow.ToString('o')
        Write-HerfySigningStatus -Session $Session
        throw
    }
}

function Complete-HerfyCodeSigningSession {
    param(
        [AllowNull()][hashtable]$Session,
        [bool]$BuildSucceeded
    )

    if ($null -eq $Session) { return }
    try {
        if ([bool]$Session.Enabled) {
            if ($BuildSucceeded) {
                $RequiredLabels = @($Session.ExpectedLabels)
                $PassedLabels = @(
                    $Session.Artifacts |
                        Where-Object { $_.status -eq 'passed' } |
                        ForEach-Object { [string]$_.label }
                )
                $MissingLabels = @($RequiredLabels | Where-Object { $_ -notin $PassedLabels })
                if ($MissingLabels.Count -ne 0) {
                    $Session.Status = 'failed'
                    $Session.Reason = 'missing_signed_artifacts:' + ($MissingLabels -join ',')
                    throw "Code signing did not cover every release executable: $($MissingLabels -join ', ')"
                }
                $Session.Status = 'passed'
                $Session.Reason = ''
            }
            elseif ($Session.Status -ne 'failed') {
                $Session.Status = 'failed'
                $Session.Reason = 'build_failed_after_signing_session_started'
            }
        }
        elseif ($BuildSucceeded -and [bool]$Session.Required) {
            $Session.Status = 'failed'
            $Session.Reason = 'required_signing_was_not_executed'
            throw 'Required code signing was not executed.'
        }
    }
    finally {
        $Session.CompletedUtc = [DateTime]::UtcNow.ToString('o')
        Write-HerfySigningStatus -Session $Session
        foreach ($ImportedThumbprint in @($Session.ImportedThumbprints)) {
            Remove-Item -Force -LiteralPath ("Cert:\CurrentUser\My\" + $ImportedThumbprint) -ErrorAction SilentlyContinue
        }
        $Session.ImportedThumbprints = @()
    }

    if ([string]$Session.Status -eq 'passed') {
        Write-Host "HERFY_CODE_SIGNING_COMPLETE artifacts=$($Session.Artifacts.Count)"
    }
}
