<#
.SYNOPSIS
    Restart ArcGIS Pro so a freshly built add-in is loaded.

.DESCRIPTION
    ArcGIS Pro loads add-ins at startup, so every change to the add-in needs a
    restart. This closes Pro the way clicking the X does -- Pro runs its own
    shutdown -- then reopens the project and waits for the bridge to answer.

    Pro asks whether to save on the way out, and nothing answers a prompt in an
    unattended restart, so the close stalls there. By default this answers
    "Don't Save": a restart is for reloading the add-in, and the project
    changes it discards are the ones testing just made. Pass -Save to save
    through the bridge instead and keep them.

    It never kills the process. A forced kill would leave the project's locks
    behind; the prompt is answered rather than bypassed.

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
    [switch]$Save,
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

function Send-Command($command, $timeoutMs = 120000) {
    $client = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 6510)
    try {
        $stream = $client.GetStream()
        $payload = [Text.Encoding]::UTF8.GetBytes(
            "{`"id`":1,`"command`":`"$command`",`"params`":{}}`n")
        $stream.Write($payload, 0, $payload.Length)
        $stream.Flush()
        $client.ReceiveTimeout = $timeoutMs
        $buffer = New-Object byte[] 8192
        $read = $stream.Read($buffer, 0, $buffer.Length)
        return [Text.Encoding]::UTF8.GetString($buffer, 0, $read)
    } finally {
        $client.Close()
    }
}

# Pro's "save changes?" prompt is a WPF dialog inside the main window, not a
# separate top-level window, so it is found by walking the automation tree.
function Answer-SavePrompt($process) {
    try {
        Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes -ErrorAction Stop
    } catch {
        return $false
    }

    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $byPid = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $process.Id)
    $window = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $byPid)
    if (-not $window) { return $false }

    $isButton = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Button)

    try {
        $buttons = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $isButton)
    } catch {
        # The tree walk times out while Pro is busy. Not a prompt; try later.
        return $false
    }

    foreach ($button in $buttons) {
        # Only a live prompt has an enabled, on-screen discard button. The
        # ribbon's own Save buttons are disabled while no dialog is up.
        if ($button.Current.Name -notmatch "^(Don't Save|Do not save|No)$") { continue }
        if ($button.Current.IsOffscreen -or -not $button.Current.IsEnabled) { continue }

        $pattern = $button.GetCurrentPattern(
            [System.Windows.Automation.InvokePattern]::Pattern)
        $pattern.Invoke()
        Write-Host "  answered the save prompt: $($button.Current.Name)"
        return $true
    }
    return $false
}

$pro = Get-Pro
if ($pro) {
    if ($Save -and (Test-Bridge)) {
        Write-Host "Saving through the bridge before closing..."
        foreach ($command in @("save_edits", "save_project")) {
            try {
                $reply = Send-Command $command
                if ($reply -match '"success"\s*:\s*true') {
                    Write-Host "  $command ok"
                } else {
                    # This used to print "done" whatever came back, which hid a
                    # save that was failing every time.
                    Write-Host "  $command FAILED: $reply"
                }
            } catch {
                Write-Host "  $command skipped: $($_.Exception.Message)"
            }
        }
    } elseif (-not $Save) {
        Write-Host "Not saving: the save prompt will be answered 'Don't Save'."
    }

    Write-Host "Closing ArcGIS Pro (pid $($pro.Id))..."
    $null = $pro.CloseMainWindow()

    # Pro's own shutdown can take a couple of minutes on a large project, and
    # it reports progress in the window title -- worth reading before deciding
    # something has gone wrong.
    $waited = 0
    $answered = $false
    while ($waited -lt $CloseTimeoutSeconds) {
        $running = Get-Pro
        if (-not $running) { break }
        Start-Sleep -Seconds 2
        $waited += 2

        if (-not $Save -and -not $answered -and $waited % 6 -eq 0) {
            $answered = Answer-SavePrompt $running
        }
        if ($waited % 30 -eq 0) {
            Write-Host ("  {0}s: '{1}', responding={2}" -f `
                $waited, $running.MainWindowTitle, $running.Responding)
        }
    }

    if (Get-Pro) {
        $title = (Get-Pro).MainWindowTitle
        Write-Host "ArcGIS Pro is still running after ${waited}s (window: '$title')."
        if ($title -like "*hutting down*") {
            Write-Host "It is still shutting down. Re-run in a moment, or raise -CloseTimeoutSeconds."
        } else {
            Write-Host "Answer whatever it is asking, or close it by hand, then re-run."
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
        return (Send-Command "get_project_info" 20000) -match '"success"\s*:\s*true'
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
