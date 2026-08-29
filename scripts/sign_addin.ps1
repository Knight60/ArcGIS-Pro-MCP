<#
.SYNOPSIS
    Digitally sign the built .esriAddinX so ArcGIS Pro can load it without
    "Load all Add-Ins without restrictions".

.DESCRIPTION
    ArcGIS Pro decides whether to load an add-in from
    HKCU\SOFTWARE\ESRI\ArcGISPro\Settings\BlockAddIns:

        0  load everything (what an unsigned add-in needs)
        1  load only add-ins signed by a trusted publisher
        2  load only add-ins signed by Esri

    An .esriAddinX is a zip, so it cannot carry an Authenticode signature the
    way an .exe does. Pro signs it as an OPC package instead, and ships the
    tool that does it: ArcGISSignAddIn.exe, in Pro's bin folder. Run with no
    arguments it opens a wizard; it also takes /cert-thumbprint:, /c:, /p:,
    /n: and /s (silent), which is what this script uses.

    Signing alone changes nothing: the certificate has to be trusted too.
    Tested against Pro 3.7.1, what it actually requires is narrower than the
    setting's wording suggests -- the signature must chain to a trusted root,
    and the certificate must not have expired. It does not check the Code
    Signing EKU, and it does not require the publisher to be in Trusted
    Publishers. -Trust adds the certificate to both Root and Trusted
    Publishers anyway, for the current user only: Root is what Pro needs, and
    Trusted Publishers is where anyone looking for it would expect to find it.

    That is a real decision. Anything else signed by this certificate becomes
    trusted too, so keep the .pfx private, and see -Untrust to undo it.

.PARAMETER AddInPath
    The .esriAddinX to sign. Defaults to the Release build.

.PARAMETER Subject
    Subject name of the signing certificate, created if -CreateCertificate is
    given and reused on later runs.

.PARAMETER CreateCertificate
    Create a self-signed code-signing certificate in the current user's
    personal store if there is not one with this subject already.

.PARAMETER Trust
    Copy the certificate into the current user's Trusted Publishers (and
    Trusted Root, which a self-signed certificate needs) so Pro will accept
    the signature.

.PARAMETER Untrust
    Remove the certificate from those stores again.

.PARAMETER ValidYears
    How long a newly created certificate lasts. Long by default, on purpose:
    ArcGIS Pro rejects an add-in whose signing certificate has expired, and the
    signature carries no RFC 3161 timestamp -- only a SignatureTime the signer
    wrote itself -- so there is nothing to prove the signing happened while the
    certificate was valid. The signature dies with the certificate, and every
    copy of the add-in stops loading on the same day. A certificate you issue
    yourself gains nothing from a short life.

.PARAMETER SetProSecurity
    Set BlockAddIns to 1 -- signed by a trusted publisher only. Without this
    the script leaves Pro's setting alone.

.EXAMPLE
    # First time: make a certificate, sign, trust it, and tighten Pro
    .\scripts\sign_addin.ps1 -CreateCertificate -Trust -SetProSecurity

.EXAMPLE
    # Later builds: the certificate already exists, so just sign
    .\scripts\sign_addin.ps1
#>
[CmdletBinding()]
param(
    [string]$AddInPath,
    [string]$Subject = "CN=ArcGIS MCP Add-In",
    [switch]$CreateCertificate,
    [switch]$Trust,
    [switch]$Untrust,
    [switch]$SetProSecurity,
    [int]$ValidYears = 20
)

$ErrorActionPreference = "Stop"

$signer = "C:\Program Files\ArcGIS\Pro\bin\ArcGISSignAddIn.exe"
if (-not (Test-Path $signer)) { throw "ArcGIS Pro's signing tool is not at $signer" }

if (-not $AddInPath) {
    $AddInPath = Join-Path $PSScriptRoot "..\addin\ArcGISProMCP\bin\Release\ArcGISProMCP.esriAddinX"
}
$AddInPath = (Resolve-Path $AddInPath).Path

# --- the certificate ---------------------------------------------------------

function Get-SigningCertificate {
    Get-ChildItem Cert:\CurrentUser\My |
        Where-Object { $_.Subject -eq $Subject -and $_.HasPrivateKey } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
}

$certificate = Get-SigningCertificate

if (-not $certificate -and $CreateCertificate) {
    Write-Host "Creating a code-signing certificate for $Subject..."
    $certificate = New-SelfSignedCertificate -Type CodeSigningCert -Subject $Subject `
        -CertStoreLocation Cert:\CurrentUser\My -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddYears($ValidYears)
}

if (-not $certificate) {
    throw "No certificate with subject '$Subject' in Cert:\CurrentUser\My. " +
          "Re-run with -CreateCertificate to make a self-signed one, or pass " +
          "-Subject to name one you already have."
}

Write-Host "Certificate: $($certificate.Subject)"
Write-Host "  thumbprint $($certificate.Thumbprint), expires $($certificate.NotAfter.ToString('yyyy-MM-dd'))"

# --- trust -------------------------------------------------------------------

function Set-StoreMembership($storeName, $add) {
    $store = New-Object System.Security.Cryptography.X509Certificates.X509Store(
        $storeName, "CurrentUser")
    $store.Open("ReadWrite")
    try {
        $existing = $store.Certificates | Where-Object { $_.Thumbprint -eq $certificate.Thumbprint }
        if ($add -and -not $existing) {
            $store.Add($certificate)
            Write-Host "  added to CurrentUser\$storeName"
        } elseif (-not $add -and $existing) {
            foreach ($c in $existing) { $store.Remove($c) }
            Write-Host "  removed from CurrentUser\$storeName"
        } else {
            Write-Host "  CurrentUser\$storeName already as wanted"
        }
    } finally {
        $store.Close()
    }
}

if ($Untrust) {
    Write-Host "Removing trust..."
    Set-StoreMembership "TrustedPublisher" $false
    Set-StoreMembership "Root" $false
    Write-Host "Done. ArcGIS Pro will no longer accept add-ins signed with this certificate."
    exit 0
}

if ($Trust) {
    Write-Host "Trusting the certificate for the current user..."
    # Trusted Root as well: a self-signed certificate is its own issuer, and
    # Pro checks that the chain is valid, not just that the publisher is listed.
    Set-StoreMembership "Root" $true
    Set-StoreMembership "TrustedPublisher" $true
}

# --- sign --------------------------------------------------------------------

if (-not (Test-Path $AddInPath)) {
    throw "No add-in at $AddInPath. Build it first: " +
          "dotnet build addin\ArcGISProMCP\ArcGISProMCP.csproj -c Release"
}

Write-Host "Signing $AddInPath"
& $signer $AddInPath "/cert-thumbprint:$($certificate.Thumbprint)" "/s"
if ($LASTEXITCODE -ne 0) { throw "ArcGISSignAddIn.exe failed with exit code $LASTEXITCODE" }

# The tool reports success by exit code alone, so confirm the signature parts
# are really in the package rather than taking its word for it.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($AddInPath)
try {
    $signatureParts = $zip.Entries | Where-Object { $_.FullName -like "package/services/digital-signature/*" }
} finally {
    $zip.Dispose()
}

if (-not $signatureParts) { throw "The add-in came back without a signature. It was not signed." }
Write-Host "Signed: $($signatureParts.Count) signature parts in the package."

# --- Pro's setting -----------------------------------------------------------

$settings = "HKCU:\SOFTWARE\ESRI\ArcGISPro\Settings"
$current = (Get-ItemProperty $settings -Name BlockAddIns -ErrorAction SilentlyContinue).BlockAddIns

if ($SetProSecurity) {
    if (-not (Test-Path $settings)) { New-Item -Path $settings -Force | Out-Null }
    Set-ItemProperty $settings -Name BlockAddIns -Value 1 -Type DWord
    Write-Host "ArcGIS Pro add-in security: $current -> 1 (trusted publishers only)"
    Write-Host "Restart ArcGIS Pro, then check the MCP tab is there."
    Write-Host "If it is not, set it back with:"
    Write-Host "  Set-ItemProperty '$settings' -Name BlockAddIns -Value 0"
} else {
    Write-Host "ArcGIS Pro add-in security is $current. To require a trusted publisher, re-run with -SetProSecurity."
}
