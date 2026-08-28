<#
.SYNOPSIS
    Restart ArcGIS Pro so a freshly built add-in is loaded.

.DESCRIPTION
    ArcGIS Pro loads add-ins at startup, so every change to the add-in needs a
    restart. This closes Pro the way clicking the X does -- Pro runs its own
    shutdown, and any "save changes?" prompt still appears -- then reopens the
    project and waits for the bridge to answer.

    It never kills the process: a forced kill would throw away unsaved edits
    without asking. If Pro is waiting on a prompt, this reports that and stops.

.PARAMETER Project
    The .aprx to reopen. Defaults to whichever project Pro currently has open.

.PARAMETER TimeoutSeconds
    How long to wait for the bridge after the restart.
#>
[CmdletBinding()]
param(
    [string]$Project,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

function Get-Pro { Get-Process ArcGISPro -ErrorAction SilentlyContinue }

function Test-Bridge($port = 6510) {
    $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

# --- work out which project to reopen ----------------------------------------

if (-not $Project) {
    $pro = Get-Pro
    if ($pro) {
        $open = $pro.Modules | Where-Object { $_.FileName -like "*.aprx" } |
                Select-Object -First 1
        if ($open) { $Project = $open.FileName }
    }
    if (-not $Project) {
        $registry = "$env:LOCALAPPDATA\ArcGIS-MCP\last-project.txt"
        if (Test-Path $registry) { $Project = (Get-Content $registry -Raw).Trim() }
    }
}
if ($Project) {
    New-Item -ItemType Directory -Force (Split-Path "$env:LOCALAPPDATA\ArcGIS-MCP\x") | Out-Null
    Set-Content "$env:LOCALAPPDATA\ArcGIS-MCP\last-project.txt" $Project -Encoding utf8
}

# --- close -------------------------------------------------------------------

$pro = Get-Pro
if ($pro) {
    Write-Host "Closing ArcGIS Pro (pid $($pro.Id))..."
    $null = $pro.CloseMainWindow()
    $waited = 0
    while ((Get-Pro) -and $waited -lt 60) { Start-Sleep -Seconds 2; $waited += 2 }

    if (Get-Pro) {
        Write-Host "ArcGIS Pro is still running after ${waited}s."
        Write-Host "It is probably showing a prompt (unsaved changes). Answer it, then re-run."
        exit 2
    }
    Write-Host "Closed after ${waited}s."
} else {
    Write-Host "ArcGIS Pro was not running."
}

# --- reopen ------------------------------------------------------------------

$exe = "C:\Program Files\ArcGIS\Pro\bin\ArcGISPro.exe"
if (-not (Test-Path $exe)) { throw "ArcGIS Pro not found at $exe" }

if ($Project -and (Test-Path $Project)) {
    Write-Host "Starting ArcGIS Pro with $Project"
    Start-Process $exe -ArgumentList "`"$Project`""
} else {
    Write-Host "Starting ArcGIS Pro (no project path known)"
    Start-Process $exe
}

# --- wait for the bridge -----------------------------------------------------

$waited = 0
while ($waited -lt $TimeoutSeconds) {
    Start-Sleep -Seconds 5
    $waited += 5
    if (Test-Bridge) {
        Write-Host "Bridge listening after ${waited}s."
        exit 0
    }
}

Write-Host "ArcGIS Pro started but the bridge did not answer within ${TimeoutSeconds}s."
Write-Host "Check $env:LOCALAPPDATA\ArcGIS-MCP\addin.log"
exit 1
