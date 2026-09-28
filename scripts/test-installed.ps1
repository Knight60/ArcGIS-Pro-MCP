[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
throw 'Historical mutation smoke test retired. Use scripts/test-hardened-installed.ps1 with the saved scratch fixture; the hardened server deliberately denies these mutation tools.'
$script:requestId = 0
$endpoint = 'http://127.0.0.1:6520/mcp'
function Rpc($method, $parameters) {
    $script:requestId++
    $body = @{jsonrpc='2.0'; id=$script:requestId; method=$method; params=$parameters} | ConvertTo-Json -Depth 20 -Compress
    $reply = Invoke-RestMethod -Uri $endpoint -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 90
    if ($reply.error) { throw ($reply.error | ConvertTo-Json -Compress) }
    return $reply.result
}
function Tool($name, $parameters=@{}) {
    $result = Rpc 'tools/call' @{name=$name; arguments=$parameters}
    if ($result.isError) { throw "$name failed: $($result.content[0].text)" }
    Write-Host "PASS $name"
    return ($result.content | Where-Object type -eq 'text' | Select-Object -First 1).text | ConvertFrom-Json
}
$init = Rpc 'initialize' @{protocolVersion='2025-03-26'; capabilities=@{};clientInfo=@{name='installed-smoke-test';version='1'}}
if ($init.serverInfo.name -ne 'ArcGIS Pro MCP') { throw 'Unexpected endpoint' }
$tools = (Rpc 'tools/list' @{}).tools
if ($tools.Count -ne 112) { throw "Expected 112 tools; got $($tools.Count)" }
$ping = Tool 'ping'
$project = Tool 'get_project_info'
if ($project.path -notmatch 'ArcGISProTemp\d+.*Untitled' -or @($project.maps).Count -ne 0) {
    throw 'This mutation test requires an empty Start without a template session. No test data was created.'
}
$testDir = Join-Path (Split-Path $PSScriptRoot -Parent) ('artifacts\live-test-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $testDir | Out-Null
$mapName = 'Knight60 MCP Test'
$layerName = 'mcp_test_points'
$gdb = Join-Path $testDir 'smoke.gdb'
Tool 'create_map' @{name=$mapName;epsg=4326;basemap='NONE'} | Out-Null
Tool 'activate_map' @{map_name=$mapName} | Out-Null
Tool 'create_file_geodatabase' @{folder=$testDir;name='smoke.gdb'} | Out-Null
Tool 'create_feature_class' @{name=$layerName;geometry_type='POINT';epsg=4326;out_path=$gdb;map_name=$mapName;add_to_map=$true} | Out-Null
Tool 'add_field' @{layer_name=$layerName;field_name='LABEL';field_type='TEXT';field_length=80;map_name=$mapName} | Out-Null
Tool 'insert_features' @{layer_name=$layerName;map_name=$mapName;features=@(
    @{attributes=@{LABEL='Alpha'};geometry=@(0.0,0.0)},
    @{attributes=@{LABEL='Beta'};geometry=@(1.0,1.0)},
    @{attributes=@{LABEL='Gamma'};geometry=@(2.0,0.0)}
)} | Out-Null
Tool 'save_edits' | Out-Null
$count = Tool 'count_features' @{layer_name=$layerName;map_name=$mapName}
if ($count.count -ne 3) { throw "Wrong inserted count: $($count | ConvertTo-Json -Compress)" }
$features = Tool 'get_features' @{layer_name=$layerName;map_name=$mapName;limit=10}
Tool 'select_features' @{layer_name=$layerName;map_name=$mapName;where="LABEL = 'Beta'"} | Out-Null
$selection = Tool 'get_selection' @{map_name=$mapName}
if ($selection.total_selected -ne 1) { throw 'Expected one selected test feature' }
Tool 'clear_selection' @{map_name=$mapName} | Out-Null
# This intentionally invalid request must not remove any rows.
$guard = Rpc 'tools/call' @{name='delete_features';arguments=@{layer_name=$layerName;map_name=$mapName}}
if (!$guard.isError) { throw 'Unfiltered deletion was not refused' }
$countAfter = Tool 'count_features' @{layer_name=$layerName;map_name=$mapName}
if ($countAfter.count -ne 3) { throw 'Delete guard changed data' }
Write-Host 'PASS unfiltered delete refused, three rows retained'
Tool 'zoom_to_layer' @{layer_name=$layerName;map_name=$mapName} | Out-Null
# The SDK preserves scale when exporting at a smaller pixel width. Give the
# fixture margin so its outer points remain inside the 800x600 export.
Tool 'set_map_view' @{map_name=$mapName;scale=1400000} | Out-Null
Tool 'export_map_view' @{map_name=$mapName;output_path=(Join-Path $testDir 'map.png');width=800;height=600;return_image=$false} | Out-Null
$diagnostics = Tool 'diagnose'
if (!$diagnostics.ok) { throw "Diagnose failed: $($diagnostics | ConvertTo-Json -Depth 10)" }
Tool 'save_project' @{save_as_path=(Join-Path $testDir 'Knight60-MCP-Test.aprx')} | Out-Null
$savedProject = Tool 'get_project_info'
if (!(Test-Path -LiteralPath $savedProject.path -PathType Leaf)) { throw 'Saved project file missing' }
$originResponse = Invoke-WebRequest -Uri $endpoint -Method Post -Headers @{Origin='https://attacker.invalid'} -ContentType 'application/json' -Body '{}' -SkipHttpErrorCheck
if ([int]$originResponse.StatusCode -ne 403) { throw 'Installed build did not reject Origin' }
Write-Host 'PASS installed Origin rejection'
Write-Host "PASS live installed test. Artifacts: $testDir"
Write-Output (@{test_directory=$testDir;pid=$ping.pid;tool_count=$tools.Count;feature_count=$countAfter.count;features=$features;selection=$selection;diagnostics=$diagnostics} | ConvertTo-Json -Depth 15)
