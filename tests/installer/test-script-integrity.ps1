# The installer shipped for two releases calling Remove-EmptyAddInFolders after
# its definition had been deleted. With $ErrorActionPreference = 'Stop', every
# uninstall died on CommandNotFoundException after the package was already
# gone. Nothing caught it because the call sites parse perfectly well.
#
# This needs no ArcGIS Pro and no built package, so CI runs it too.
$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path "$PSScriptRoot\..\..").Path
$failures = 0

function Check($what, $ok, $detail = '') {
    $mark = if ($ok) { 'PASS' } else { 'FAIL' }
    Write-Host "$mark  $what $detail"
    if (-not $ok) { $script:failures++ }
}

foreach ($name in 'install_addin.ps1', 'build.ps1', 'sign_addin.ps1', 'restart_pro.ps1') {
    $path = Join-Path $repository "scripts\$name"
    if (-not (Test-Path -LiteralPath $path)) { Check "$name exists" $false; continue }

    $parseErrors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$parseErrors)
    Check "$name parses" (-not $parseErrors) ($parseErrors -join '; ')
    if ($parseErrors) { continue }

    $defined = @($ast.FindAll({
        param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]
    }, $true) | ForEach-Object Name)

    # Every command the script invokes has to be either a function it defines
    # or something PowerShell can resolve on its own.
    $missing = @($ast.FindAll({
        param($node) $node -is [Management.Automation.Language.CommandAst]
    }, $true) | ForEach-Object {
        $_.GetCommandName()
    } | Where-Object {
        $_ -and $_ -notmatch '^\$' -and $defined -notcontains $_ -and
        -not (Get-Command $_ -ErrorAction SilentlyContinue)
    } | Sort-Object -Unique)

    Check "$name calls nothing undefined" ($missing.Count -eq 0) ($missing -join ', ')
}

if ($failures) { exit 1 }
Write-Host 'PASS installer scripts: parse, and every command they call resolves'
