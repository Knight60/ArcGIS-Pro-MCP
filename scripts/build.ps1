<#
.SYNOPSIS
    Build, sign and package the ArcGIS Pro MCP add-in for release.

.DESCRIPTION
    Produces everything a release needs into dist\:

        ArcGISProMCP.esriAddinX      the add-in. Double-clicking it installs it.
        Install-ArcGISProMCP.cmd     one self-contained file: the add-in is
                                     embedded in it, so there is nothing else
                                     to download and no repository to clone.

    The single-file installer exists because the add-in alone cannot fix a
    machine that has add-in security turned on -- it can only be installed and
    then silently not load. The installer looks, says which of the two states
    it found, and offers the fix.

    Building needs ArcGIS Pro installed: the project references Pro's own
    assemblies by path. See BUILD.md.

.PARAMETER Configuration
    Release (default) or Debug.

.PARAMETER Sign
    Sign the add-in with the certificate named by -CertificateSubject. Without
    this the output is unsigned, which is fine on a machine that has not had
    add-in security turned on -- most of them.

.PARAMETER CertificateSubject
    Subject of the signing certificate. See scripts\sign_addin.ps1.

.PARAMETER SkipTests
    Skip the client-registration tests. They do not need ArcGIS Pro.

.EXAMPLE
    .\scripts\build.ps1
    # dist\ArcGISProMCP.esriAddinX and dist\Install-ArcGISProMCP.cmd

.EXAMPLE
    .\scripts\build.ps1 -Sign
    # the same, signed, for machines that require a trusted publisher
#>
[CmdletBinding()]
param(
    [ValidateSet("Release", "Debug")]
    [string]$Configuration = "Release",
    [switch]$Sign,
    [string]$CertificateSubject = "CN=ArcGIS MCP Add-In",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$project = Join-Path $repository "addin\ArcGISProMCP\ArcGISProMCP.csproj"
$dist = Join-Path $repository "dist"

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

# --- generated inputs --------------------------------------------------------

Step "Tool schemas"
# tools.json is generated from catalog.py, the single definition of the MCP
# surface, and embedded in the assembly. Building without regenerating it ships
# an add-in whose tool list disagrees with the Python server's.
$python = (Get-Command python -ErrorAction SilentlyContinue)
if ($python) {
    & $python.Source (Join-Path $repository "scripts\export_tool_schemas.py")
    if ($LASTEXITCODE -ne 0) { throw "export_tool_schemas.py failed" }
} else {
    Write-Warning "python not on PATH -- keeping the tools.json already in the tree"
}

Step "Icons"
& (Join-Path $PSScriptRoot "make_icons.ps1")

# --- build -------------------------------------------------------------------

Step "Build ($Configuration)"
& dotnet build $project -c $Configuration --nologo -v minimal
if ($LASTEXITCODE -ne 0) { throw "dotnet build failed" }

$addIn = Join-Path $repository "addin\ArcGISProMCP\bin\$Configuration\ArcGISProMCP.esriAddinX"
if (-not (Test-Path $addIn)) { throw "The build produced no .esriAddinX at $addIn" }

if (-not $SkipTests) {
    Step "Tests"
    & dotnet run --project (Join-Path $repository "tests\client-registration") `
        -c $Configuration --nologo -v quiet
    if ($LASTEXITCODE -ne 0) { throw "client-registration tests failed" }
}

# --- package -----------------------------------------------------------------

New-Item -ItemType Directory -Force $dist | Out-Null
$packaged = Join-Path $dist "ArcGISProMCP.esriAddinX"
Copy-Item $addIn $packaged -Force

if ($Sign) {
    Step "Sign"
    & (Join-Path $PSScriptRoot "sign_addin.ps1") -AddInPath $packaged -Subject $CertificateSubject
    if ($LASTEXITCODE -ne 0) { throw "signing failed" }
}

Step "Single-file installer"

$installer = Join-Path $repository "scripts\install_addin.ps1"
if (-not (Test-Path $installer)) { throw "No installer script at $installer" }

# The add-in is embedded as base64 rather than shipped beside the script: one
# file is the whole point, and a script that needs a second file next to it is
# a script people will run from the wrong folder.
$payload = [Convert]::ToBase64String([IO.File]::ReadAllBytes($packaged))
$wrapped = ($payload -split '(.{120})' | Where-Object { $_ }) -join "`n"

# The packaged installer takes the same switches as the source one, minus
# -AddInPath which it supplies itself. Derived rather than restated: a switch
# added to install_addin.ps1 would otherwise silently not reach the packaged
# copy, and the failure would look like the switch not working.
$source = Get-Content $installer -Raw
if ($source -notmatch '(?s)\[CmdletBinding\(\)\]\s*param\s*\((.*?)\r?\n\)') {
    throw "Could not find the param block in $installer"
}
# Re-indented rather than sliced out, because trimming the block as a whole
# takes the first surviving line's indent with it.
$parameters = (($matches[1] -split "`n" |
    Where-Object { $_.Trim() -and $_ -notmatch '\$AddInPath' } |
    ForEach-Object { "    " + $_.Trim() }) -join "`n").TrimEnd(',')
$paramBlock = "param(`n$parameters`n)"

$version = ([xml](Get-Content (Join-Path $repository "addin\ArcGISProMCP\Config.daml"))
            ).ArcGIS.AddInInfo.version
$built = (Get-Date).ToString("yyyy-MM-dd")
$signedNote = if ($Sign) { "signed" } else { "unsigned" }

# A .cmd that is also a PowerShell script. Double-clicking a .ps1 does not run
# it, and running one from a prompt fails outright on a default Windows client,
# where the execution policy is Restricted -- which is exactly the machine this
# installer exists for. cmd.exe has no such policy, so the batch half re-invokes
# PowerShell with -ExecutionPolicy Bypass on the PowerShell half of this same
# file. It is extracted to a temp .ps1 rather than piped through iex so that the
# param block still binds and switches still work.
$header = @"
@echo off
rem ArcGIS Pro MCP -- self-contained installer. Double-click, or run it from a
rem prompt with switches: -TrustPublisher, -AllowAllAddIns, -Uninstall, -Reinstall
rem Version $version, built $built, $signedNote. Generated by scripts\build.ps1.
setlocal
set "PSPART=%TEMP%\ArcGISProMCP-install-%RANDOM%.ps1"
rem The marker is spelled in two halves on purpose. Written whole, this line
rem would itself contain the marker, IndexOf would find it here, and the file
rem would cut itself at the wrong place.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "`$t=[IO.File]::ReadAllText('%~f0'); [IO.File]::WriteAllText(`$env:PSPART, `$t.Substring(`$t.IndexOf('#PS'+'PART>')+9))"
if errorlevel 1 goto :done
powershell -NoProfile -ExecutionPolicy Bypass -File "%PSPART%" %*
:done
set RC=%ERRORLEVEL%
del "%PSPART%" >nul 2>&1
if "%1"=="" pause
endlocal & exit /b %RC%
#PSPART>
[CmdletBinding()]
$paramBlock

`$ErrorActionPreference = "Stop"

`$payload = @'
$wrapped
'@

`$temporary = Join-Path ([IO.Path]::GetTempPath()) "ArcGISProMCP-$version.esriAddinX"
[IO.File]::WriteAllBytes(`$temporary, [Convert]::FromBase64String((`$payload -replace '\s', '')))

try {
"@

# The installer's own body, re-used verbatim: one implementation, so the
# packaged installer cannot drift from the one in the repository.
$body = (Get-Content $installer -Raw)
$body = $body -replace '(?s)^<#.*?#>', ''             # its comment-based help
# One pattern for CmdletBinding and the param block together. Removing them
# separately left a newline where CmdletBinding had been, so the ^-anchored
# param pattern no longer matched and a bare "param(" ended up halfway down
# the generated file.
$body = $body -replace '(?s)\[CmdletBinding\(\)\]\s*param\s*\(.*?\r?\n\)', ''
$body = $body -replace '(?m)^\$ErrorActionPreference = "Stop"\s*$', ''
$body = $body.Trim()
if ($body -match '(?m)^\s*param\s*\(') { throw "The param block was not stripped." }
$body = ($body -split "`n" | ForEach-Object { if ($_.Trim()) { "    $_" } else { "" } }) -join "`n"

$footer = @"

} finally {
    Remove-Item `$temporary -ErrorAction SilentlyContinue
}
"@

$outputPath = Join-Path $dist "Install-ArcGISProMCP.cmd"
# The installer body takes -AddInPath; the packaged one always uses the file it
# just unpacked.
$header = $header -replace '(?m)^try \{$', "`$AddInPath = `$temporary`n`ntry {"
# A here-string drops the newline before its terminator, so without this
# the body starts on the same line as "try {".
Set-Content $outputPath ($header + "`n" + $body + $footer) -Encoding UTF8

# Only the PowerShell half can be parsed -- the batch header would be a syntax
# error on its own. Split it out the same way the batch header does at runtime.
$generated = [IO.File]::ReadAllText($outputPath)
$marker = $generated.IndexOf("#PSPART>")
if ($marker -lt 0) { throw "The generated installer has no #PSPART> marker." }
$psHalf = $generated.Substring($marker + 9)

$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput(
    $psHalf, [ref]$null, [ref]$errors)
if ($errors) {
    $errors | ForEach-Object { Write-Host "  line $($_.Extent.StartLineNumber): $($_.Message)" }
    throw "The generated installer does not parse."
}

# --- report ------------------------------------------------------------------

Write-Host ""
Write-Host "dist\" -ForegroundColor Green
foreach ($file in Get-ChildItem $dist | Sort-Object Name) {
    "  {0,-32} {1,10:N0} bytes" -f $file.Name, $file.Length
}
Write-Host ""
Write-Host "Install by double-clicking the .esriAddinX, or run the installer:"
Write-Host "  dist\Install-ArcGISProMCP.cmd    (or double-click it)"
