<#
.SYNOPSIS
    Install the ArcGIS Pro MCP add-in.

.DESCRIPTION
    Copies the add-in where ArcGIS Pro looks for it, then checks whether Pro
    will actually load it and says what to do if not.

    It does the least that works. On a machine nobody has configured, ArcGIS
    Pro loads add-ins without restriction, so installing is one file copy: no
    certificate, no registry, no administrator. Only if this machine has been
    tightened does the script offer anything further, and it explains the
    trade before doing it.

    What Pro checks, tested against 3.7.1, is narrower than the setting's
    wording suggests: the signature has to chain to a trusted root and the
    certificate must not have expired. It does not require the Code Signing
    EKU, and it does not require the publisher to be in Trusted Publishers.

.PARAMETER AddInPath
    The .esriAddinX to install. Defaults to the one beside this script, then
    to the Release build.

.PARAMETER TrustPublisher
    Also import the add-in's signing certificate, so Pro will load it while
    add-in security stays at "trusted publisher only". Windows shows its own
    security warning for this and it cannot be skipped -- read it. Trusting a
    self-signed certificate means trusting everything signed with that key,
    not just this add-in.

.PARAMETER AllowAllAddIns
    Set add-in security to 0 (load everything) for the current user. Simpler
    than importing a certificate, and weaker: any add-in will load.

.PARAMETER Uninstall
    Remove every copy of the add-in this finds, and stop.

.PARAMETER Reinstall
    Install over an existing copy of the same version without asking. Running
    this with nothing already installed does the same thing either way.

.EXAMPLE
    .\install.ps1
    # Copies the add-in and reports whether Pro will load it.

.EXAMPLE
    .\install.ps1 -TrustPublisher
    # For a machine set to "trusted publisher only".
#>
[CmdletBinding()]
param(
    [string]$AddInPath,
    [switch]$TrustPublisher,
    [switch]$AllowAllAddIns,
    [switch]$Uninstall,
    [switch]$Reinstall
)

$ErrorActionPreference = "Stop"

function Say($text) { Write-Host $text }
function Warn($text) { Write-Host $text -ForegroundColor Yellow }
function Good($text) { Write-Host $text -ForegroundColor Green }

# --- everywhere ArcGIS Pro looks ---------------------------------------------

# GetFolderPath, not %USERPROFILE%\Documents: with OneDrive's folder backup on
# they are different directories, and the add-in lands where Pro will never
# look for it.
$documents = [Environment]::GetFolderPath("MyDocuments")
$target = Join-Path $documents "ArcGIS\AddIns\ArcGISPro"

function Get-AddInVersion($path) {
    # The version lives in Config.daml at the root of the package, which is a
    # plain zip. Reading it beats trusting a file name or a date.
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($path)
        try {
            $entry = $zip.Entries | Where-Object { $_.FullName -eq "Config.daml" }
            if (-not $entry) { return $null }
            $reader = New-Object IO.StreamReader($entry.Open())
            try { $daml = [xml]$reader.ReadToEnd() } finally { $reader.Close() }
            return $daml.ArcGIS.AddInInfo.version
        } finally { $zip.Dispose() }
    } catch {
        return $null
    }
}

function Choose($question, $options) {
    # The options name the action -- "Install", "Uninstall", "Cancel" -- rather
    # than Yes and No. Asked "Uninstall it? [Y/N]", someone who came to install
    # cannot tell which answer gets them what they came for, and the wrong
    # guess removes a working add-in.
    #
    # PromptForChoice throws where there is no console to prompt on: a scheduled
    # task, a CI job. Hanging there would be worse than declining and saying
    # which switch says it outright.
    try {
        $choices = [Management.Automation.Host.ChoiceDescription[]](
            $options | ForEach-Object {
                New-Object Management.Automation.Host.ChoiceDescription $_
            })
        Say ""
        return $Host.UI.PromptForChoice("", $question, $choices, 0)
    } catch {
        Warn "There is no console to ask on."
        Warn "Pass -Reinstall to install, or -Uninstall to remove."
        return -1
    }
}

function Find-InstalledCopies {
    # Pro scans this folder and its subfolders, and RegisterAddIn.exe unpacks
    # into a subfolder of its own. Two copies of the same add-in id is not an
    # error anyone is told about -- Pro loads one of them and the other's
    # changes appear not to take effect, which is a bad afternoon.
    if (-not (Test-Path $target)) { return @() }
    return @(Get-ChildItem $target -Recurse -Filter "*.esriAddinX" -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -like "ArcGISProMCP*" })
}

function Uninstall-AddIn($copies) {
    foreach ($copy in $copies) {
        Remove-Item $copy.FullName -Force
        Good "Removed $($copy.FullName)"
    }
    Remove-EmptyAddInFolders
    Say ""
    Good "Uninstalled. Restart ArcGIS Pro and the MCP tab will be gone."
    Say  "Run this installer again to put it back."
    Say  "Any certificate imported earlier is left in place; remove it with"
    Say  "scripts\sign_addin.ps1 -Untrust."
}

if ($Uninstall) {
    $copies = Find-InstalledCopies
    if (-not $copies) {
        Say "ArcGIS Pro MCP is not installed. Nothing to uninstall."
        exit 0
    }
    Uninstall-AddIn $copies
    exit 0
}

# --- find the add-in ---------------------------------------------------------

if (-not $AddInPath) {
    $candidates = @(
        (Join-Path $PSScriptRoot "ArcGISProMCP.esriAddinX"),
        (Join-Path $PSScriptRoot "..\ArcGISProMCP.esriAddinX"),
        (Join-Path $PSScriptRoot "..\addin\ArcGISProMCP\bin\Release\ArcGISProMCP.esriAddinX"),
        (Join-Path $PSScriptRoot "..\addin\ArcGISProMCP\bin\Debug\ArcGISProMCP.esriAddinX")
    )
    $AddInPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $AddInPath -or -not (Test-Path $AddInPath)) {
    throw "No .esriAddinX found. Pass -AddInPath, or put the file next to this script."
}
$AddInPath = (Resolve-Path $AddInPath).Path

# --- install or uninstall? ---------------------------------------------------

# One installer does both jobs, so it says which state it found before asking
# anything, and the question names the action rather than offering Yes and No.
$installed = Find-InstalledCopies
$incoming = Get-AddInVersion $AddInPath
$current = if ($installed) { Get-AddInVersion $installed[0].FullName } else { $null }

Say ""
if ($installed) {
    Good "ArcGIS Pro MCP $current is INSTALLED on this machine."
    Say  "  $($installed[0].FullName)"
    if ($installed.Count -gt 1) {
        Warn "  ...and $($installed.Count - 1) more copy(ies). Two copies of one"
        Warn "  add-in is one too many: ArcGIS Pro loads one and ignores the rest."
    }
} else {
    Say "ArcGIS Pro MCP is NOT INSTALLED on this machine."
    Say "  This installer carries version $incoming."
}

if (-not $Reinstall) {
    if (-not $installed) {
        # Nothing there: the only question is whether to put it there.
        $answer = Choose "Install ArcGIS Pro MCP $incoming?" @(
            "&Install    - copy it to $target",
            "&Cancel     - change nothing and quit")
        if ($answer -ne 0) { Say ""; Say "Cancelled. Nothing was changed."; exit 0 }

    } elseif ($current -and $incoming -and $current -ne $incoming) {
        # A different version: upgrading is the likely intent, removing is not.
        $answer = Choose "This installer carries version $incoming. What would you like to do?" @(
            "&Upgrade    - replace $current with $incoming",
            "&Remove     - uninstall $current and install nothing",
            "&Cancel     - change nothing and quit")
        if ($answer -eq 1) { Uninstall-AddIn $installed; exit 0 }
        if ($answer -ne 0) { Say ""; Say "Cancelled. Nothing was changed."; exit 0 }

    } else {
        # Same version already there: reinstalling achieves nothing, so removing
        # is the only thing worth offering.
        $answer = Choose "Version $current is already installed. What would you like to do?" @(
            "&Uninstall  - remove it from this machine",
            "&Keep       - leave it installed and quit",
            "&Reinstall  - install this copy over it")
        if ($answer -eq 0) { Uninstall-AddIn $installed; exit 0 }
        if ($answer -ne 2) { Say ""; Say "Left as it is. Nothing was changed."; exit 0 }
    }
}

# --- install -----------------------------------------------------------------

# Anything already there goes first. Leaving an older copy behind is the
# failure this has actually caused: Pro picks one, and every change made to
# the other silently does nothing.
$stale = Find-InstalledCopies |
    Where-Object { $_.FullName -ne (Join-Path $target "ArcGISProMCP.esriAddinX") }
foreach ($copy in $stale) {
    Remove-Item $copy.FullName -Force
    Say "Removed an older copy: $($copy.FullName)"
}
if ($stale) { Remove-EmptyAddInFolders }

New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item $AddInPath (Join-Path $target "ArcGISProMCP.esriAddinX") -Force
Good "Installed to $target"

# --- read the signature out of the package -----------------------------------

Add-Type -AssemblyName System.IO.Compression.FileSystem
$signerCertificate = $null
$zip = [IO.Compression.ZipFile]::OpenRead($AddInPath)
try {
    $entry = $zip.Entries | Where-Object {
        $_.FullName -like "package/services/digital-signature/certificate/*.cer"
    } | Select-Object -First 1
    if ($entry) {
        # The signing certificate travels inside the signed package, so there
        # is no second file to hand out and no way to import the wrong one.
        $stream = $entry.Open()
        $buffer = New-Object byte[] $entry.Length
        [void]$stream.Read($buffer, 0, $buffer.Length)
        $stream.Close()
        $signerCertificate =
            New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(, $buffer)
    }
} finally {
    $zip.Dispose()
}

if ($signerCertificate) {
    Say "Signed by $($signerCertificate.Subject), expires $($signerCertificate.NotAfter.ToString('yyyy-MM-dd'))"
    if ($signerCertificate.NotAfter -lt (Get-Date)) {
        Warn "That certificate has expired. ArcGIS Pro will refuse the add-in if"
        Warn "add-in security is on; it has to be signed again."
    }
} else {
    Say "This add-in is not signed."
}

# --- will ArcGIS Pro load it? ------------------------------------------------

function Get-Setting($hive) {
    $key = "$($hive):\SOFTWARE\ESRI\ArcGISPro\Settings"
    if (-not (Test-Path $key)) { return $null }
    return (Get-ItemProperty $key -Name BlockAddIns -ErrorAction SilentlyContinue).BlockAddIns
}

# The per-user value wins where it exists; the installer writes 0 machine-wide.
$user = Get-Setting "HKCU"
$machine = Get-Setting "HKLM"
$effective = if ($null -ne $user) { $user } else { $machine }
if ($null -eq $effective) { $effective = 0 }

$meaning = @{
    0 = "load all add-ins"
    1 = "only add-ins signed by a trusted publisher"
    2 = "only Esri add-ins"
    3 = "no add-ins at all"
}
Say ""
Say "Add-in security on this machine: $effective ($($meaning[[int]$effective]))"

function Test-Trusted($certificate) {
    if (-not $certificate) { return $false }
    $chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
    $chain.ChainPolicy.RevocationMode = "NoCheck"
    return $chain.Build($certificate)
}

$willLoad = switch ([int]$effective) {
    0 { $true }
    1 { Test-Trusted $signerCertificate }
    default { $false }
}

if ($willLoad) {
    Good ""
    Good "Ready. Restart ArcGIS Pro and look for the MCP tab."
    Say  "Then point your AI client at it from that tab, or run:"
    Say  "  claude mcp add --transport http arcgis http://127.0.0.1:6520/mcp"
    exit 0
}

# --- it will not load, so explain the two ways forward -----------------------

Say ""
Warn "ArcGIS Pro will not load this add-in as things stand."

if ([int]$effective -ge 2) {
    Warn "Security is set to $effective, which excludes every add-in that is not Esri's."
    Say  "Lower it with -AllowAllAddIns, or set it to 1 and re-run with -TrustPublisher."
}

if ($TrustPublisher) {
    if (-not $signerCertificate) { throw "This add-in is not signed, so there is nothing to trust." }

    Say ""
    Say "Importing the publisher certificate."
    Warn "Windows will now ask you to confirm. It cannot be skipped, and you should"
    Warn "read it: trusting a self-signed certificate trusts everything signed with"
    Warn "that key, not only this add-in. Undo it later in certmgr.msc, under"
    Warn "Trusted Root Certification Authorities."
    Say  "  Subject:    $($signerCertificate.Subject)"
    Say  "  Thumbprint: $($signerCertificate.Thumbprint)"

    foreach ($storeName in "Root", "TrustedPublisher") {
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store(
            $storeName, "CurrentUser")
        $store.Open("ReadWrite")
        try {
            $already = $store.Certificates | Where-Object {
                $_.Thumbprint -eq $signerCertificate.Thumbprint }
            if ($already) { Say "  already in CurrentUser\$storeName" }
            else { $store.Add($signerCertificate); Say "  added to CurrentUser\$storeName" }
        } finally { $store.Close() }
    }

    if (Test-Trusted $signerCertificate) {
        Good ""
        Good "Trusted. Restart ArcGIS Pro and look for the MCP tab."
        exit 0
    }
    Warn "The certificate was not trusted -- the prompt was probably declined."
    exit 1
}

if ($AllowAllAddIns) {
    $key = "HKCU:\SOFTWARE\ESRI\ArcGISPro\Settings"
    if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
    Set-ItemProperty $key -Name BlockAddIns -Value 0 -Type DWord
    Good ""
    Good "Add-in security set to 0 for your user. Restart ArcGIS Pro."
    Say  "To put it back:  Set-ItemProperty '$key' -Name BlockAddIns -Value $effective"
    exit 0
}

Say ""
Say "Two ways forward. Re-run this script with one of them:"
Say ""
Say "  -TrustPublisher    trust the certificate that signed this add-in."
Say "                     Narrow, but you are trusting a key, not a file."
Say ""
Say "  -AllowAllAddIns    let ArcGIS Pro load any add-in, for your user only."
Say "                     Nothing to trust, and nothing checked either."
Say ""
Say "Neither needs administrator rights, and both are reversible."
exit 1
