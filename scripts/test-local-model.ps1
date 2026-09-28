# Bounded local inference test. Only a count on our named test layer is executable.
$ErrorActionPreference = 'Stop'
$endpoint = 'http://127.0.0.1:6520/mcp'
$credentialPath = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ArcGIS-MCP\security\http-token.txt'
$headers = @{Authorization=('Bearer ' + [IO.File]::ReadAllText($credentialPath))}
$listBody = @{jsonrpc='2.0';id=1;method='tools/list';params=@{}} | ConvertTo-Json -Compress
$catalog = (Invoke-RestMethod $endpoint -Method Post -Headers $headers -ContentType 'application/json' -Body $listBody -MaximumRedirection 0).result.tools
$tool = $catalog | Where-Object name -eq 'count_features'
$messages = @(@{role='user';content='Use count_features to count rows in layer mcp_test_points in map Knight60 MCP Test. Do not guess the count.'})
$request = @{model='llama3.1:latest';stream=$false;messages=$messages;options=@{temperature=0;num_predict=150};tools=@(@{type='function';function=@{name=$tool.name;description=$tool.description;parameters=$tool.inputSchema}})}
$choice = Invoke-RestMethod 'http://127.0.0.1:11434/api/chat' -Method Post -ContentType 'application/json' -Body ($request | ConvertTo-Json -Depth 20 -Compress) -TimeoutSec 90
$calls = @($choice.message.tool_calls)
if($calls.Count -ne 1 -or $calls[0].function.name -ne 'count_features'){throw 'Model did not choose the permitted tool'}
$arguments = $calls[0].function.arguments
if($arguments.layer_name -ne 'mcp_test_points' -or $arguments.map_name -ne 'Knight60 MCP Test' -or $arguments.where){throw 'Model arguments outside test scope'}
$body = @{jsonrpc='2.0';id=2;method='tools/call';params=@{name='count_features';arguments=@{layer_name='mcp_test_points';map_name='Knight60 MCP Test'}}} | ConvertTo-Json -Depth 10 -Compress
$result = (Invoke-RestMethod $endpoint -Method Post -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec 15 -MaximumRedirection 0).result
if($result.isError){throw $result.content[0].text}
$count = ($result.content[0].text | ConvertFrom-Json).count
if($count -ne 3){throw "Unexpected fixture count $count"}
$messages += $choice.message
$messages += @{role='tool';tool_name='count_features';content=$result.content[0].text}
$request.messages = $messages
$request.Remove('tools')
$answer = Invoke-RestMethod 'http://127.0.0.1:11434/api/chat' -Method Post -ContentType 'application/json' -Body ($request | ConvertTo-Json -Depth 20 -Compress) -TimeoutSec 90
Write-Output "PASS local llama3.1 chose count_features with scoped arguments; MCP returned $count"
Write-Output "Local model answer: $($answer.message.content)"
