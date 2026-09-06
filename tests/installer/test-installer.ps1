param([string]$Package = "$PSScriptRoot\..\..\artifacts\candidates\pro-3.7\ArcGISProMCP.esriAddinX")
$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path "$PSScriptRoot\..\..").Path
$source = Join-Path $repository 'scripts\install_addin.ps1'
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($source, [ref]$null, [ref]$parseErrors)
if ($parseErrors) { throw $parseErrors }
# Load the actual discovery/removal functions without running installer entry
# points or changing the real Documents directory, certificates or registry.
foreach ($name in 'Say','Good','Get-AddInVersion','Find-InstalledCopies','Remove-EmptyAddInFolders','Uninstall-AddIn') {
    $definition = $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $true) |
        Where-Object Name -eq $name
    if (-not $definition) { throw "Missing function $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
$target = Join-Path $repository ('artifacts\installer-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $target | Out-Null
$Package = (Resolve-Path -LiteralPath $Package).Path
$expected = ([xml](Get-Content (Join-Path $repository 'addin\ArcGISProMCP\Config.daml') -Raw)).ArcGIS.AddInInfo.version
if ((Get-AddInVersion $Package) -ne $expected) { throw "Candidate is not version $expected" }
Copy-Item -LiteralPath $Package -Destination (Join-Path $target 'renamed-package.esriAddinX')
$nested = Join-Path $target 'nested'
New-Item -ItemType Directory -Path $nested | Out-Null
Copy-Item -LiteralPath $Package -Destination (Join-Path $nested 'ArcGISProMCP-old.esriAddinX')
$unrelated = Join-Path $target 'ArcGISProMCP-unrelated.esriAddinX'
Set-Content -LiteralPath $unrelated -Value 'not our package'
# RegisterAddIn.exe leaves a folder named after the add-in id behind.
$leftover = Join-Path $target '{2e4cb7d3-56a7-4caf-911f-390b5821de61}'
New-Item -ItemType Directory -Path $leftover | Out-Null
$occupied = Join-Path $target 'SomeoneElse'
New-Item -ItemType Directory -Path $occupied | Out-Null
Set-Content -LiteralPath (Join-Path $occupied 'keep.txt') -Value 'keep me'
$copies = Find-InstalledCopies
if ($copies.Count -ne 2) { throw 'Discovery must match package identity, including renamed copies' }
foreach ($copy in $copies) {
    if (-not $copy.FullName.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Test escaped sandbox' }
}
Uninstall-AddIn $copies
if ((Find-InstalledCopies).Count -ne 0) { throw 'Uninstall left a package behind' }
if (-not (Test-Path -LiteralPath $unrelated)) { throw 'Uninstall removed unrelated data' }
if (Test-Path -LiteralPath $leftover) { throw 'Uninstall left the empty add-in id folder behind' }
if (Test-Path -LiteralPath $nested) { throw 'Uninstall left an emptied folder behind' }
if (-not (Test-Path -LiteralPath (Join-Path $occupied 'keep.txt'))) { throw 'Uninstall emptied a folder that was not ours' }
Remove-Item -LiteralPath $target -Recurse -Force
Write-Host 'PASS installer: renamed/nested discovery, uninstall, empty folders cleared, unrelated data preserved'
