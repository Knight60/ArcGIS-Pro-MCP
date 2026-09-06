<#
.SYNOPSIS
    Capture the ArcGIS Pro window for the README screenshot.

.DESCRIPTION
    docs/images/mcp-menu.png shows the MCP tab. It has to be retaken whenever
    the ribbon changes -- a screenshot that disagrees with the add-in is worse
    than none, because a reader trusts the picture over the prose. It went out
    of date once already, showing "Port 6510" after the caption became the MCP
    port.

    Bring ArcGIS Pro to the front with the MCP tab selected, then run this. It
    captures that window only, not the desktop.

.PARAMETER Output
    Where to write the PNG. Defaults to docs/images/mcp-menu.png.

.PARAMETER Delay
    Seconds to wait before capturing, to let the window finish drawing.
#>
param(
    [string]$Output = (Join-Path $PSScriptRoot '..\docs\images\mcp-menu.png'),
    [int]$Delay = 2
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class Win {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    // The window rectangle including the drop shadow is wrong for a
    // screenshot; this one is the visible frame.
    [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(
        IntPtr h, int attribute, out RECT value, int size);
}
'@

$pro = Get-Process ArcGISPro -ErrorAction SilentlyContinue |
       Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $pro) { throw 'ArcGIS Pro is not running, or has no window.' }

$handle = $pro.MainWindowHandle
if ([Win]::IsIconic($handle)) { [void][Win]::ShowWindow($handle, 9) }  # SW_RESTORE
# Windows refuses to let a background process pull a window to the front, so
# this often does nothing. The delay is the real mechanism: click ArcGIS Pro
# yourself while it counts down.
[void][Win]::SetForegroundWindow($handle)
Write-Host "Click the ArcGIS Pro window now -- capturing in $Delay seconds."
Start-Sleep -Seconds $Delay

# Capturing whatever happens to be on top produces a screenshot of the wrong
# application, which is worse than failing: it looks like it worked.
if ([Win]::GetForegroundWindow() -ne $handle) {
    throw 'ArcGIS Pro is not the front window. Click it and run this again.'
}

$rect = New-Object Win+RECT
# 9 = DWMWA_EXTENDED_FRAME_BOUNDS
if ([Win]::DwmGetWindowAttribute($handle, 9, [ref]$rect, 16) -ne 0) {
    throw 'Could not measure the ArcGIS Pro window.'
}
$width  = $rect.R - $rect.L
$height = $rect.B - $rect.T
if ($width -le 0 -or $height -le 0) { throw "Window measured $width x $height." }

$bitmap = New-Object Drawing.Bitmap $width, $height
$graphics = [Drawing.Graphics]::FromImage($bitmap)
try {
    $graphics.CopyFromScreen($rect.L, $rect.T, 0, 0, $bitmap.Size)
} finally {
    $graphics.Dispose()
}

$Output = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Force (Split-Path $Output) | Out-Null
$bitmap.Save($Output, [Drawing.Imaging.ImageFormat]::Png)
$bitmap.Dispose()

Write-Host "Captured $width x $height to $Output"
Write-Host 'Check the MCP tab is the selected one before using it.'
