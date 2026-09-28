# Read-only live security regression. Requires the named scratch fixture from the initial install test.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$endpoint='http://127.0.0.1:6520/mcp'
$credentialPath=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ArcGIS-MCP\security\http-token.txt'
$headers=@{Authorization=('Bearer '+[IO.File]::ReadAllText($credentialPath))}
$script:sequence=0
function Rpc($method,$parameters=@{}) {
    $script:sequence++
    $body=@{jsonrpc='2.0';id=$script:sequence;method=$method;params=$parameters}|ConvertTo-Json -Depth 20 -Compress
    $reply=Invoke-RestMethod $endpoint -Method Post -Headers $headers -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 30 -MaximumRedirection 0
    if ($reply.error) { throw 'Unexpected JSON-RPC error' }
    if ($reply.id -ne $script:sequence) { throw 'Mismatched response ID' }
    return $reply.result
}
function Tool($name,$arguments=@{}) {
    $result=Rpc 'tools/call' @{name=$name;arguments=$arguments}
    if ($result.isError) { throw "Read tool failed: $name ($($result.content[0].text))" }
    Write-Host "PASS live read: $name"
    return ($result.content|Where-Object type -eq 'text'|Select-Object -First 1).text|ConvertFrom-Json
}
function Denied($name,$arguments=@{}) {
    $result=Rpc 'tools/call' @{name=$name;arguments=$arguments}
    if (-not $result.isError) { throw "Security regression: $name unexpectedly succeeded" }
    Write-Host "PASS live denied: $name"
}
$init=Rpc 'initialize' @{protocolVersion='2025-03-26';capabilities=@{};clientInfo=@{name='hardened-live-regression';version='1'}}
if ($init.serverInfo.version -ne '1.1.2.0') { throw 'Restart ArcGIS Pro to load hardened version 1.1.2.0.' }
$catalog=(Rpc 'tools/list').tools
if ($catalog.Count -ne 18) { throw 'Unexpected hardened tool catalog' }
foreach ($auth in @(@{},@{Authorization='Bearer incorrect'})) {
    $response=Invoke-WebRequest $endpoint -Method Post -Headers $auth -ContentType 'application/json' -Body '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' -SkipHttpErrorCheck -MaximumRedirection 0
    if ($response.StatusCode -ne 401) { throw 'Unauthenticated access did not fail closed' }
}
Write-Host 'PASS live authentication: missing/incorrect credentials rejected'
$browserHeaders=@{Authorization=$headers.Authorization;Origin='https://attacker.invalid'}
$browser=Invoke-WebRequest $endpoint -Method Post -Headers $browserHeaders -ContentType 'application/json' -Body '{}' -SkipHttpErrorCheck -MaximumRedirection 0
if ($browser.StatusCode -ne 403) { throw 'Browser Origin accepted' }
Write-Host 'PASS live browser-origin rejection'
$project=Tool 'get_project_info'
if ($project.path -notlike '*\artifacts\live-test-*\Knight60-MCP-Test.aprx\Knight60-MCP-Test.aprx') { throw 'Open the scratch Knight60-MCP-Test project for fixture checks.' }
$p=@{layer_name='mcp_test_points';map_name='Knight60 MCP Test'}
$count=Tool 'count_features' $p
if ($count.count -ne 3) { throw 'Expected three fixture rows' }
Tool 'ping'|Out-Null
$capabilities=Tool 'get_capabilities'
if ($capabilities.editing_enabled) { throw 'Expected read-only mode' }
Tool 'get_arcgis_info'|Out-Null
Tool 'list_maps'|Out-Null
Tool 'get_layers' @{map_name=$p.map_name}|Out-Null
Tool 'get_layer_info' $p|Out-Null
Tool 'get_map_view' @{map_name=$p.map_name}|Out-Null
Tool 'list_bookmarks' @{map_name=$p.map_name}|Out-Null
$fields=Tool 'list_fields' $p
$oid=($fields.fields|Where-Object type -eq 'OID'|Select-Object -First 1).name
if (-not $oid) { throw 'Missing fixture OID field' }
$features=Tool 'get_features' ($p+@{limit=10;fields=@('LABEL',$oid)})
if ($features.count -ne 3) { throw 'Feature count mismatch' }
$unique=Tool 'get_unique_values' ($p+@{field='LABEL'})
if ($unique.distinct_count -ne 3) { throw 'Distinct count mismatch' }
$stats=Tool 'get_field_statistics' ($p+@{field=$oid})
if ($stats.count -ne 3) { throw 'Statistics count mismatch' }
$summary=Tool 'summarize_features' ($p+@{group_by=@('LABEL');value_field=$oid})
if ($summary.group_count -ne 3) { throw 'Group count mismatch' }
Denied 'rename_layer' ($p+@{new_name='should_not_change'})
Denied 'set_layer_visibility' ($p+@{visible=$false})
Denied 'set_layer_transparency' ($p+@{transparency=90})
# Empty arguments never perform damage even if a server has regressed; assert policy rejection.
$all=(Get-Content (Join-Path $PSScriptRoot '..\addin\ArcGISProMCP\Resources\tools.json') -Raw|ConvertFrom-Json).tools
foreach ($tool in $all) {
    if ($tool.name -in $catalog.name) { continue }
    $result=Rpc 'tools/call' @{name=$tool.name;arguments=@{}}
    if (-not $result.isError -or $result.content[0].text -notlike '*disabled by the hardened security policy*') { throw "Missing policy denial: $($tool.name)" }
}
Write-Host 'PASS live deny-all coverage: 94 disabled catalog tools'
Denied 'get_features' ($p+@{where='1=1'})
Denied 'get_features' ($p+@{limit=1001})
Denied 'count_features' @{layer_name='C:\unrelated.gdb\secret'}
$after=Tool 'count_features' $p
if ($after.count -ne 3) { throw 'Fixture rows changed' }
$listeners=Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue|Where-Object LocalPort -in 6510,6511
if ($listeners) { throw 'A legacy bridge listener remains; investigate its owning process.' }
Write-Host 'PASS no legacy TCP/Python listeners on ports 6510/6511; fixture unchanged; all 15 read tools exercised'
