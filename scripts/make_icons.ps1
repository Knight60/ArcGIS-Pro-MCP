<#
.SYNOPSIS
    Draw the ribbon icons into addin/ArcGISProMCP/Images.

.DESCRIPTION
    The icons are generated rather than committed as opaque PNGs, so a change
    to one is a readable diff instead of a binary blob.

    They are drawn to read at 16px, where ArcGIS Pro shows most of them: bold
    silhouettes, one colour each, nothing thinner than two pixels. Colour
    carries state -- green running, red stopped, grey not set up -- and shape
    repeats it, because colour alone is no use to anyone who cannot tell the
    two apart.
#>
[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $PSScriptRoot "..\addin\ArcGISProMCP\Images"
}
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$OutputDirectory = (Resolve-Path $OutputDirectory).Path

$green = [System.Drawing.Color]::FromArgb(255, 30, 142, 62)
$red = [System.Drawing.Color]::FromArgb(255, 197, 34, 31)
$grey = [System.Drawing.Color]::FromArgb(255, 128, 134, 139)
$blue = [System.Drawing.Color]::FromArgb(255, 26, 115, 232)

function New-Icon([int]$size, [scriptblock]$draw) {
    $bitmap = New-Object System.Drawing.Bitmap($size, $size,
        [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bitmap)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)
    # The scale factor lets each drawing be written once, in 32px coordinates.
    & $draw $g ($size / 32.0)
    $g.Dispose()
    return $bitmap
}

function Save-Icon([string]$name, [scriptblock]$draw) {
    foreach ($size in 16, 32) {
        $bitmap = New-Icon $size $draw
        $path = Join-Path $OutputDirectory "$name$size.png"
        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Dispose()
    }
    Write-Host "  $name 16 + 32"
}

function Get-Brush($color) { New-Object System.Drawing.SolidBrush($color) }
function Get-Pen($color, $width) {
    $pen = New-Object System.Drawing.Pen($color, $width)
    $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    return $pen
}

Write-Host "Drawing icons into $OutputDirectory"

# --- the bridge toggle: play and stop, as on anything that plays -------------

Save-Icon "Start" {
    param($g, $s)
    $brush = Get-Brush $green
    $points = @(
        (New-Object System.Drawing.PointF((8 * $s), (5 * $s))),
        (New-Object System.Drawing.PointF((27 * $s), (16 * $s))),
        (New-Object System.Drawing.PointF((8 * $s), (27 * $s)))
    )
    $g.FillPolygon($brush, $points)
    $brush.Dispose()
}

Save-Icon "Stop" {
    param($g, $s)
    $brush = Get-Brush $red
    $g.FillRectangle($brush, (7 * $s), (7 * $s), (18 * $s), (18 * $s))
    $brush.Dispose()
}

# --- status: a dot broadcasting, or a dot with nothing coming out ------------

function Draw-Signal($g, $s, $color, $listening) {
    if ($listening) {
        # Two arcs either side: something is going out over the wire.
        $pen = Get-Pen $color (2.6 * $s)
        foreach ($radius in 5, 10) {
            $box = New-Object System.Drawing.RectangleF(
                ((16 - $radius) * $s), ((16 - $radius) * $s), (2 * $radius * $s), (2 * $radius * $s))
            $g.DrawArc($pen, $box, -50, 100)
            $g.DrawArc($pen, $box, 130, 100)
        }
        $pen.Dispose()
    } else {
        # A ring where the waves would be, and nothing coming out of it. A
        # slash was tried twice and lost: at 16px the diagonal is the only
        # thing left, and the icon reads as a bar rather than a dead signal.
        $pen = Get-Pen $color (2.2 * $s)
        $g.DrawEllipse($pen, (6 * $s), (6 * $s), (20 * $s), (20 * $s))
        $pen.Dispose()
    }

    $brush = Get-Brush $color
    $g.FillEllipse($brush, (12.5 * $s), (12.5 * $s), (7 * $s), (7 * $s))
    $brush.Dispose()
}

Save-Icon "StatusOn" { param($g, $s) Draw-Signal $g $s $green $true }
Save-Icon "StatusOff" { param($g, $s) Draw-Signal $g $s $grey $false }

# --- AI clients: registered, or waiting to be ---------------------------------

# A link icon was tried first and read as "<->" and "</>" at 16px -- the second
# looks like a code tag. A tick and a plus say the same thing and survive the
# size: this one is set up, that one is a thing you can add.

function Draw-Badge($g, $s, $color, $registered) {
    $pen = Get-Pen $color (2.8 * $s)
    $g.DrawEllipse($pen, (4 * $s), (4 * $s), (24 * $s), (24 * $s))
    $pen.Dispose()

    $pen = Get-Pen $color (3.6 * $s)
    if ($registered) {
        $g.DrawLine($pen, (10 * $s), (16.5 * $s), (14.5 * $s), (21 * $s))
        $g.DrawLine($pen, (14.5 * $s), (21 * $s), (22 * $s), (11.5 * $s))
    } else {
        $g.DrawLine($pen, (16 * $s), (10 * $s), (16 * $s), (22 * $s))
        $g.DrawLine($pen, (10 * $s), (16 * $s), (22 * $s), (16 * $s))
    }
    $pen.Dispose()
}

Save-Icon "ClientLinked" { param($g, $s) Draw-Badge $g $s $green $true }
Save-Icon "ClientUnlinked" { param($g, $s) Draw-Badge $g $s $grey $false }

# --- info --------------------------------------------------------------------

Save-Icon "Info" {
    param($g, $s)
    $pen = Get-Pen $blue (2.8 * $s)
    $g.DrawEllipse($pen, (4 * $s), (4 * $s), (24 * $s), (24 * $s))
    $pen.Dispose()

    # The dot and the stem drawn separately: joined up, the "i" turns into a
    # bar at 16px and the icon stops reading as an i at all.
    $brush = Get-Brush $blue
    $g.FillEllipse($brush, (14.2 * $s), (8.5 * $s), (3.6 * $s), (3.6 * $s))
    $g.FillRectangle($brush, (14.2 * $s), (14 * $s), (3.6 * $s), (9.5 * $s))
    $brush.Dispose()
}

# --- the tab's own icon ------------------------------------------------------

Save-Icon "Mcp" {
    param($g, $s)
    # Three nodes and the links between them: a server something connects to.
    $pen = Get-Pen $blue (2.4 * $s)
    $g.DrawLine($pen, (8 * $s), (10 * $s), (22 * $s), (22 * $s))
    $g.DrawLine($pen, (8 * $s), (22 * $s), (22 * $s), (10 * $s))
    $pen.Dispose()

    $brush = Get-Brush $blue
    foreach ($point in @(@(8, 10), @(8, 22), @(22, 10), @(22, 22))) {
        $g.FillEllipse($brush, (($point[0] - 3.5) * $s), (($point[1] - 3.5) * $s), (7 * $s), (7 * $s))
    }
    $brush.Dispose()
}

Write-Host "Done. $(@(Get-ChildItem $OutputDirectory -Filter *.png).Count) files."
