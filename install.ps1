<#
.SYNOPSIS
    Install the ArcGIS Pro MCP server and register it with your AI clients.

.DESCRIPTION
    Installs the Python package, registers the MCP server with whichever of
    Claude Code / Codex CLI / Gemini CLI are present, and sets up auto-start so
    the bridge inside ArcGIS Pro comes up on its own when Pro launches.

    Existing client config files are backed up (.bak) before they are changed.

.PARAMETER Python
    Python 3.10+ interpreter to install the MCP server into. Defaults to the
    "python" on PATH. This does NOT have to be ArcGIS Pro's Python -- the MCP
    server runs outside Pro.

.PARAMETER Clients
    Which clients to register: claude, codex, gemini, all, none.
    Defaults to every client detected on this machine.

.PARAMETER SkipInstall
    Register the clients without running pip install.

.PARAMETER NoAutoStart
    Do not install the auto-start hook into ArcGIS Pro's Python environment.
    The bridge then has to be started from the ArcGIS MCP toolbox each session.

.PARAMETER ProPython
    ArcGIS Pro's python.exe. Auto-detected from the registry when omitted.

.PARAMETER Uninstall
    Remove the auto-start hook (leaves the Python package and client configs).

.EXAMPLE
    .\install.ps1

.EXAMPLE
    .\install.ps1 -Clients claude -NoAutoStart

.EXAMPLE
    .\install.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$Python = "python",
    [string[]]$Clients = @("auto"),
    [switch]$SkipInstall,
    [switch]$NoAutoStart,
    [string]$ProPython,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pluginDir = Join-Path $repoRoot "arcgis_pro_plugin"
$stateDir = Join-Path $env:LOCALAPPDATA "ArcGIS-MCP"
$pthName = "arcgis-mcp-autostart.pth"
$autostartModule = "arcgis_mcp_autostart.py"

function Write-Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "   [ok] $text" -ForegroundColor Green }
function Write-Warn2($text){ Write-Host "   [!]  $text" -ForegroundColor Yellow }

function Get-ProPython {
    if ($ProPython) {
        if (-not (Test-Path $ProPython)) { throw "ArcGIS Pro Python not found: $ProPython" }
        return $ProPython
    }
    $candidates = @()
    foreach ($key in @("HKLM:\SOFTWARE\ESRI\ArcGISPro", "HKCU:\SOFTWARE\ESRI\ArcGISPro")) {
        try {
            $installDir = (Get-ItemProperty -Path $key -ErrorAction Stop).InstallDir
            if ($installDir) {
                $candidates += (Join-Path $installDir "bin\Python\envs\arcgispro-py3\python.exe")
            }
        } catch { }
    }
    $candidates += "C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Get-SitePackages($proPython) {
    $script = "import site,os;print([p for p in site.getsitepackages() if p.endswith('site-packages')][0])"
    return (& $proPython -c $script)
}

function Test-Writable($directory) {
    $probe = Join-Path $directory ".arcgis-mcp-write-test"
    try {
        [System.IO.File]::WriteAllText($probe, "x")
        Remove-Item $probe -Force
        return $true
    } catch {
        return $false
    }
}

# --- uninstall path ----------------------------------------------------------

if ($Uninstall) {
    Write-Step "Removing the ArcGIS Pro auto-start hook"
    $proPython = Get-ProPython
    if ($null -eq $proPython) {
        Write-Warn2 "ArcGIS Pro Python not found -- nothing to remove there"
    } else {
        $sitePackages = Get-SitePackages $proPython
        foreach ($name in @($pthName, $autostartModule)) {
            $target = Join-Path $sitePackages $name
            if (Test-Path $target) {
                Remove-Item $target -Force
                Write-Ok "Removed $target"
            }
        }
    }
    $configPath = Join-Path $stateDir "autostart.json"
    if (Test-Path $configPath) {
        Remove-Item $configPath -Force
        Write-Ok "Removed $configPath"
    }
    Write-Host "`nAuto-start removed. Start the bridge from the ArcGIS MCP toolbox instead.`n"
    exit 0
}

# --- 1. Python ---------------------------------------------------------------

Write-Step "Checking Python"
$pythonExe = $null
try {
    $pythonExe = (Get-Command $Python -ErrorAction Stop).Source
} catch {
    throw "Python not found: '$Python'. Install Python 3.10+ or pass -Python <path to python.exe>."
}
$version = & $pythonExe -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Ok "$pythonExe (Python $version)"
$parts = $version.Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    throw "Python 3.10 or newer is required; found $version."
}

# --- 2. Package --------------------------------------------------------------

if (-not $SkipInstall) {
    Write-Step "Installing arcgis-pro-mcp"
    & $pythonExe -m pip install -e $repoRoot --quiet --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE." }
    Write-Ok "Installed in editable mode from $repoRoot"
} else {
    Write-Step "Skipping pip install (-SkipInstall)"
}

$toolCount = & $pythonExe -c "from arcgis_pro_mcp.catalog import CATALOG; print(len(CATALOG))"
Write-Ok "$toolCount MCP tools available"

# --- 3. Client registration --------------------------------------------------

$serverConfig = [ordered]@{ command = $pythonExe; args = @("-m", "arcgis_pro_mcp") }

function Backup-File($path) {
    if (Test-Path $path) {
        Copy-Item $path "$path.bak" -Force
        Write-Ok "Backed up $path -> $path.bak"
    }
}

function Register-JsonClient($path, $label) {
    $dir = Split-Path -Parent $path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    $config = @{}
    if (Test-Path $path) {
        Backup-File $path
        $raw = Get-Content $path -Raw
        if ($raw.Trim().Length -gt 0) {
            $parsed = $raw | ConvertFrom-Json
            $config = @{}
            foreach ($property in $parsed.PSObject.Properties) {
                $config[$property.Name] = $property.Value
            }
        }
    }
    $servers = @{}
    if ($config.ContainsKey("mcpServers") -and $null -ne $config["mcpServers"]) {
        foreach ($property in $config["mcpServers"].PSObject.Properties) {
            $servers[$property.Name] = $property.Value
        }
    }
    $servers["arcgis"] = $serverConfig
    $config["mcpServers"] = $servers
    ($config | ConvertTo-Json -Depth 10) | Out-File -FilePath $path -Encoding utf8
    Write-Ok "$label registered in $path"
}

function Register-Claude {
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if ($null -ne $claude) {
        & claude mcp add arcgis --scope user -- $pythonExe -m arcgis_pro_mcp
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Claude Code registered (user scope)"
            return
        }
        Write-Warn2 "'claude mcp add' failed; falling back to the project .mcp.json"
    }
    Register-JsonClient (Join-Path $repoRoot ".mcp.json") "Claude Code (project scope)"
}

function Register-Codex {
    $path = Join-Path $env:USERPROFILE ".codex\config.toml"
    $dir = Split-Path -Parent $path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    $escaped = $pythonExe.Replace("\", "\\")
    $block = @"

[mcp_servers.arcgis]
command = "$escaped"
args = ["-m", "arcgis_pro_mcp"]
"@
    if (Test-Path $path) {
        $existing = Get-Content $path -Raw
        if ($existing -match "\[mcp_servers\.arcgis\]") {
            Write-Warn2 "Codex already has an [mcp_servers.arcgis] entry -- left as is"
            return
        }
        Backup-File $path
    }
    Add-Content -Path $path -Value $block -Encoding utf8
    Write-Ok "Codex CLI registered in $path"
}

function Register-Gemini {
    Register-JsonClient (Join-Path $env:USERPROFILE ".gemini\settings.json") "Gemini CLI"
}

$requested = $Clients
if ($requested -contains "auto" -or $requested -contains "all") {
    $requested = @()
    if ($Clients -contains "all") {
        $requested = @("claude", "codex", "gemini")
    } else {
        if (Get-Command claude -ErrorAction SilentlyContinue) { $requested += "claude" }
        if (Test-Path (Join-Path $env:USERPROFILE ".codex"))   { $requested += "codex" }
        if (Test-Path (Join-Path $env:USERPROFILE ".gemini"))  { $requested += "gemini" }
        if ($requested.Count -eq 0) { $requested = @("claude") }
    }
}

if ($requested -contains "none") {
    Write-Step "Skipping client registration"
} else {
    Write-Step "Registering MCP clients: $($requested -join ', ')"
    foreach ($client in $requested) {
        switch ($client) {
            "claude" { Register-Claude }
            "codex"  { Register-Codex }
            "gemini" { Register-Gemini }
            default  { Write-Warn2 "Unknown client '$client' -- skipped" }
        }
    }
}

# --- 4. Auto-start inside ArcGIS Pro -----------------------------------------

$autoStartInstalled = $false
if ($NoAutoStart) {
    Write-Step "Skipping auto-start (-NoAutoStart)"
} else {
    Write-Step "Setting up auto-start inside ArcGIS Pro"
    $proPython = Get-ProPython
    if ($null -eq $proPython) {
        Write-Warn2 "ArcGIS Pro Python not found. Pass -ProPython <path to python.exe>,"
        Write-Warn2 "or start the bridge from the ArcGIS MCP toolbox each session."
    } else {
        $proVersion = & $proPython -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
        Write-Ok "ArcGIS Pro Python: $proPython (Python $proVersion)"
        $sitePackages = Get-SitePackages $proPython

        if (-not (Test-Writable $sitePackages)) {
            Write-Warn2 "$sitePackages is not writable."
            Write-Warn2 "Re-run this script from an elevated PowerShell to enable auto-start,"
            Write-Warn2 "or use -NoAutoStart and start the bridge from the toolbox."
        } else {
            if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Force $stateDir | Out-Null }
            $config = [ordered]@{
                enabled    = $true
                plugin_dir = $pluginDir
                port       = 6510
                installed  = (Get-Date).ToString("s")
            }
            # Written without a BOM: the hook parses this from Python.
            [System.IO.File]::WriteAllText(
                (Join-Path $stateDir "autostart.json"),
                ($config | ConvertTo-Json),
                (New-Object System.Text.UTF8Encoding $false))

            Copy-Item (Join-Path $pluginDir $autostartModule) `
                      (Join-Path $sitePackages $autostartModule) -Force
            "import $([System.IO.Path]::GetFileNameWithoutExtension($autostartModule))" |
                Out-File -FilePath (Join-Path $sitePackages $pthName) -Encoding ascii

            Write-Ok "Auto-start hook installed in $sitePackages"
            Write-Ok "Config: $(Join-Path $stateDir 'autostart.json')"
            Write-Ok "Log:    $(Join-Path $stateDir 'autostart.log')"
            $autoStartInstalled = $true
        }
    }
}

# --- 5. What is left to do ---------------------------------------------------

if ($autoStartInstalled) {
    Write-Step "Next, inside ArcGIS Pro"
    Write-Host @"
   1. Restart ArcGIS Pro and open a project. The bridge starts on its own a
      few seconds later -- nothing to click.

   2. Install the main-thread dispatcher. Paste this into the Python window
      once -- it returns immediately and does not tie the window up:

         import mcp_bridge; mcp_bridge.start_pump()

      ArcGIS Pro only exposes the open project to its own main thread, and
      this is what lets commands reach it. Remove it with the stop_pump tool
      or:  python -m arcgis_pro_mcp stop-pump

   The ArcGIS MCP toolbox is now optional; add it only to start, stop or
   diagnose the bridge by hand:
      $(Join-Path $pluginDir 'ArcGISMCP.pyt')

   Turn auto-start off again with:  .\install.ps1 -Uninstall
"@
} else {
    Write-Step "Next, inside ArcGIS Pro"
    Write-Host @"
   Paste this into the ArcGIS Pro Python window -- it starts the bridge and
   the main-thread pump that gives it access to the open project:

      import sys; sys.path.insert(0, r"$pluginDir")
      import mcp_bridge; print(mcp_bridge.start_server())
      print(mcp_bridge.start_pump())

   Both lines return immediately -- ArcGIS Pro is never tied up. Remove the
   dispatcher with the stop_pump tool or 'python -m arcgis_pro_mcp stop-pump'.

   The toolbox route works too (Catalog > Toolboxes > Add Toolbox >
   $(Join-Path $pluginDir 'ArcGISMCP.pyt'), then 'Start MCP Server'), but the
   pump still has to be started from the Python window.
"@
}

Write-Step "Then verify"
Write-Host "   $pythonExe -m arcgis_pro_mcp doctor"
Write-Host ""
