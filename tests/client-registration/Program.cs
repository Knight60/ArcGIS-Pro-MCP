using System;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using ArcGISProMCP.Clients;

// Exercises the registrar against copies, so nothing here touches a real
// config. What is being checked is that a register/unregister round trip
// leaves the rest of the file exactly as it was -- these are files with a
// user's unrelated settings in them.

var failures = 0;

void Check(string what, bool ok, string detail = null)
{
    Console.WriteLine($"{(ok ? "PASS" : "FAIL")}  {what}{(detail == null ? "" : "  " + detail)}");
    if (!ok) failures++;
}

var sandbox = Path.Combine(Path.GetTempPath(), "mcp-client-test-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(sandbox);

// --- detection on this machine, read only ------------------------------------

Console.WriteLine("Detected on this machine:");
foreach (var c in McpClientCatalog.All)
{
    var installed = c.IsInstalled;
    var registered = installed && McpClientRegistrar.IsRegistered(c);
    Console.WriteLine($"  {c.Name,-16} installed={installed,-5} registered={registered,-5} "
                      + $"{c.Transport}  {c.ConfigPath}");
}
Console.WriteLine();
Console.WriteLine($"stdio launcher: {McpClientRegistrar.StdioLauncher() ?? "(not installed)"}");
Console.WriteLine();

// --- a JSON client with unrelated settings that must survive -----------------

McpClient Copy(McpClient source, string fileName)
{
    return new McpClient
    {
        Id = source.Id,
        Name = source.Name,
        ConfigPath = Path.Combine(sandbox, fileName),
        Shape = source.Shape,
        Transport = source.Transport,
        UrlKey = source.UrlKey,
        InstalledMarkers = new[] { sandbox },
    };
}

var claude = Copy(McpClientCatalog.ById("claude-code"), "claude.json");
var original = """
{
  "numStartups": 42,
  "theme": "dark",
  "mcpServers": {
    "qgis": { "type": "stdio", "command": "uvx.exe", "args": ["qgis-mcp-server"] }
  }
}
""";
File.WriteAllText(claude.ConfigPath, original);

Check("json: not registered before", !McpClientRegistrar.IsRegistered(claude));
McpClientRegistrar.Register(claude);
Check("json: registered after", McpClientRegistrar.IsRegistered(claude));

var written = JsonNode.Parse(File.ReadAllText(claude.ConfigPath)).AsObject();
Check("json: unrelated keys kept",
    (int)written["numStartups"] == 42 && (string)written["theme"] == "dark");
Check("json: other server kept",
    written["mcpServers"]["qgis"] != null);
Check("json: http entry shape",
    (string)written["mcpServers"]["arcgis"]["url"] == McpClientCatalog.HttpUrl
    && (string)written["mcpServers"]["arcgis"]["type"] == "http",
    written["mcpServers"]["arcgis"].ToJsonString());
Check("json: backup written", File.Exists(claude.ConfigPath + ".arcgis-mcp.bak"));

McpClientRegistrar.Unregister(claude);
Check("json: gone after unregister", !McpClientRegistrar.IsRegistered(claude));
var after = JsonNode.Parse(File.ReadAllText(claude.ConfigPath)).AsObject();
Check("json: round trip left the rest alone",
    (int)after["numStartups"] == 42 && after["mcpServers"]["qgis"] != null);

// --- Antigravity writes serverUrl and no type --------------------------------

var antigravity = Copy(McpClientCatalog.ById("antigravity"), "antigravity.json");
McpClientRegistrar.Register(antigravity);
var ag = JsonNode.Parse(File.ReadAllText(antigravity.ConfigPath)).AsObject();
Check("antigravity: serverUrl, no type",
    (string)ag["mcpServers"]["arcgis"]["serverUrl"] == McpClientCatalog.HttpUrl
    && ag["mcpServers"]["arcgis"]["type"] == null,
    ag["mcpServers"]["arcgis"].ToJsonString());

// --- VS Code uses "servers", not "mcpServers" --------------------------------

var vscode = Copy(McpClientCatalog.ById("vscode"), "vscode.json");
McpClientRegistrar.Register(vscode);
var vs = JsonNode.Parse(File.ReadAllText(vscode.ConfigPath)).AsObject();
Check("vscode: under servers", vs["servers"]?["arcgis"] != null && vs["mcpServers"] == null);

// --- TOML, the one that edits text rather than a parse tree ------------------

var codex = Copy(McpClientCatalog.ById("codex"), "config.toml");
var toml = """
model = "gpt-5.5"
notify = [ "a", "b" ]

[mcp_servers.node_repl]
args = []
command = 'C:\node_repl.exe'
startup_timeout_sec = 120

[mcp_servers.node_repl.env]
CODEX_HOME = 'C:\Users\x\.codex'

[plugins."browser@openai-bundled"]
enabled = true
""";
File.WriteAllText(codex.ConfigPath, toml);

Check("toml: not registered before", !McpClientRegistrar.IsRegistered(codex));
McpClientRegistrar.Register(codex);
Check("toml: registered after", McpClientRegistrar.IsRegistered(codex));

var tomlAfter = File.ReadAllText(codex.ConfigPath);
Check("toml: other server kept whole",
    tomlAfter.Contains("[mcp_servers.node_repl]")
    && tomlAfter.Contains("[mcp_servers.node_repl.env]")
    && tomlAfter.Contains("startup_timeout_sec = 120"));
Check("toml: unrelated tables kept",
    tomlAfter.Contains("[plugins.\"browser@openai-bundled\"]")
    && tomlAfter.Contains("model = \"gpt-5.5\""));
Check("toml: our section added", tomlAfter.Contains("[mcp_servers.arcgis]"));
Check("codex: direct HTTP transport", codex.Transport == Transport.Http);
Check("toml: HTTP URL without relay", tomlAfter.Contains($"url = \"{McpClientCatalog.HttpUrl}\"")
    && !tomlAfter.Contains("arcgis-pro-mcp.exe"));
Check("toml: original backup", File.ReadAllText(codex.ConfigPath + ".arcgis-mcp.bak") == toml);

foreach (var newline in new[] { "\n", "\r\n" })
{
    var legacy = toml + newline + "[mcp_servers.arcgis]" + newline
        + "command = 'C:\\missing\\arcgis-pro-mcp.exe'" + newline + "args = []" + newline
        + "[mcp_servers.arcgis.env]" + newline + "OLD_RELAY = 'yes'" + newline
        + "[mcp_servers.arcgis_other]" + newline + "url = 'http://other'" + newline;
    File.WriteAllText(codex.ConfigPath, legacy);
    Check("toml: legacy stdio needs update", !McpClientRegistrar.IsRegistered(codex));
    McpClientRegistrar.Register(codex);
    var migrated = File.ReadAllText(codex.ConfigPath);
    Check("toml: legacy migration " + newline.Length,
        migrated.StartsWith(toml) && !migrated.Contains("OLD_RELAY")
        && !migrated.Contains("missing") && migrated.Contains("[mcp_servers.arcgis_other]")
        && migrated.Contains($"url = \"{McpClientCatalog.HttpUrl}\""));
    Check("toml: migration backup", File.ReadAllText(codex.ConfigPath + ".arcgis-mcp.bak") == legacy);
}
foreach (var key in new[] { "\"arcgis\"", "'arcgis'" })
{
    File.WriteAllText(codex.ConfigPath, toml + $"\n[mcp_servers.{key}]\ncommand = 'missing.exe'\n");
    McpClientRegistrar.Register(codex);
    var migrated = File.ReadAllText(codex.ConfigPath);
    Check("toml: quoted key migration " + key, McpClientRegistrar.IsRegistered(codex)
        && !migrated.Contains("missing.exe") && !migrated.Contains($"[mcp_servers.{key}]")
        && migrated.StartsWith(toml));
}
File.WriteAllText(codex.ConfigPath, toml + "\n[mcp_servers.arcgis]");
McpClientRegistrar.Register(codex);
Check("toml: section at EOF replaced", File.ReadAllText(codex.ConfigPath)
    .Split("[mcp_servers.arcgis]").Length - 1 == 1);

// Registering twice must not leave two copies of the section.
McpClientRegistrar.Register(codex);
var twice = File.ReadAllText(codex.ConfigPath);
Check("toml: register twice is idempotent",
    twice.Split("[mcp_servers.arcgis]").Length - 1 == 1,
    $"{twice.Split("[mcp_servers.arcgis]").Length - 1} copies");

McpClientRegistrar.Unregister(codex);
var removed = File.ReadAllText(codex.ConfigPath);
Check("toml: gone after unregister", !McpClientRegistrar.IsRegistered(codex));
Check("toml: node_repl still intact",
    removed.Contains("[mcp_servers.node_repl]")
    && removed.Contains("CODEX_HOME = 'C:\\Users\\x\\.codex'"));
Check("toml: nothing else lost",
    removed.Contains("model = \"gpt-5.5\"")
    && removed.Contains("[plugins.\"browser@openai-bundled\"]"));

Console.WriteLine();
Console.WriteLine("--- codex config after the round trip ---");
Console.WriteLine(removed);

Console.WriteLine(failures == 0 ? "ALL PASSED" : $"{failures} FAILED");
return failures == 0 ? 0 : 1;
