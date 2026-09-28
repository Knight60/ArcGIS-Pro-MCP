"""Read-only stdlib test of the installed authenticated PowerShell relay."""
import json
import os
import pathlib
import subprocess

relay = pathlib.Path(os.environ["LOCALAPPDATA"]) / "ArcGIS Pro MCP" / "stdio-bridge.ps1"
shell = pathlib.Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
requests = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_project_info", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "execute_arcpy_code", "arguments": {}}},
]
# Match the generated client registration exactly; no persistent execution-policy change.
completed = subprocess.run([str(shell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(relay)],
    input="".join(json.dumps(item) + "\n" for item in requests), capture_output=True,
    text=True, encoding="utf-8", timeout=60, check=True)
results = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
assert [r["id"] for r in results] == [1, 2, 3, 4]
assert results[0]["result"]["serverInfo"]["version"] == "1.1.2.0"
assert len(results[1]["result"]["tools"]) == 18
assert not results[2]["result"].get("isError")
assert results[3]["result"]["isError"]
print("PASS authenticated stdio: initialize, 18 tools, project read, arbitrary code denied")
