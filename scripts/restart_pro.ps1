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

.PARAMETER CloseTimeoutSeconds
    How long to give ArcGIS Pro to shut down. It can take minutes on a large
    project; the window title says "Shutting down..." while it is working.
#>
[CmdletBinding()]
param(
    [string]$Project,
    [int]$TimeoutSeconds = 180,
    [int]$CloseTimeoutSeconds = 240
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
    # Save through the bridge first. Otherwise Pro asks about unsaved changes
    # on the way out, and a prompt nobody answers stops the whole restart.
    if (Test-Bridge) {
        Write-Host "Saving through the bridge before closing..."
        foreach ($command in @("save_edits", "save_project")) {
            try {
                $client = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 6510)
                $stream = $client.GetStream()
                $payload = [Text.Encoding]::UTF8.GetBytes(
                    "{`"id`":1,`"command`":`"$command`",`"params`":{}}`n")
                $stream.Write($payload, 0, $payload.Length)
                $stream.Flush()
                $client.ReceiveTimeout = 120000
                $buffer = New-Object byte[] 4096
                [void]$stream.Read($buffer, 0, $buffer.Length)
                $client.Close()
                Write-Host "  $command done"
            } catch {
                Write-Host "  $command skipped: $($_.Exception.Message)"
            }
        }
    }

    Write-Host "Closing ArcGIS Pro (pid $($pro.Id))..."
    $null = $pro.CloseMainWindow()
    # Pro's own shutdown can take a couple of minutes on a large project, and
    # it reports progress in the window title -- worth reading before deciding
    # something has gone wrong.
    $waited = 0
    while ((Get-Pro) -and $waited -lt $CloseTimeoutSeconds) {
        Start-Sleep -Seconds 2
        $waited += 2
    }

    if (Get-Pro) {
        $title = (Get-Pro).MainWindowTitle
        Write-Host "ArcGIS Pro is still running after ${waited}s (window: '$title')."
        if ($title -like "*hutting down*") {
            Write-Host "It is still shutting down. Re-run in a moment, or raise -CloseTimeoutSeconds."
        } else {
            Write-Host "It is probably showing a prompt (unsaved changes). Answer it, then re-run."
        }
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

function Test-ProjectOpen {
    # The bridge comes up with the add-in, well before the project has
    # finished opening -- so ask for something that needs Project.Current.
    try {
        $client = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 6510)
        $stream = $client.GetStream()
        $payload = [Text.Encoding]::UTF8.GetBytes(
            "{`"id`":1,`"command`":`"get_project_info`",`"params`":{}}`n")
        $stream.Write($payload, 0, $payload.Length)
        $stream.Flush()
        $client.ReceiveTimeout = 20000
        $buffer = New-Object byte[] 8192
        $read = $stream.Read($buffer, 0, $buffer.Length)
        $client.Close()
        return ([Text.Encoding]::UTF8.GetString($buffer, 0, $read) -like '*"success": true*') -or
               ([Text.Encoding]::UTF8.GetString($buffer, 0, $read) -like '*"success":true*')
    } catch {
        return $false
    }
}

$waited = 0
$listening = $false
while ($waited -lt $TimeoutSeconds) {
    Start-Sleep -Seconds 5
    $waited += 5
    if (-not $listening -and (Test-Bridge)) {
        $listening = $true
        Write-Host "Bridge listening after ${waited}s; waiting for the project..."
    }
    if ($listening -and (Test-ProjectOpen)) {
        Write-Host "Project open and answering after ${waited}s."
        exit 0
    }
}

Write-Host "ArcGIS Pro started but the bridge did not answer within ${TimeoutSeconds}s."
Write-Host "Check $env:LOCALAPPDATA\ArcGIS-MCP\addin.log"
exit 1
