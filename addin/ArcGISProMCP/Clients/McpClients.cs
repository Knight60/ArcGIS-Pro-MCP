using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace ArcGISProMCP.Clients
{
    /// <summary>Where a client keeps its MCP servers, and in what shape.</summary>
    internal enum ConfigShape
    {
        /// <summary>{ "mcpServers": { "arcgis": { ... } } } -- most clients.</summary>
        JsonMcpServers,

        /// <summary>{ "servers": { "arcgis": { ... } } } -- VS Code.</summary>
        JsonServers,

        /// <summary>[mcp_servers.arcgis] -- Codex.</summary>
        Toml,
    }

    /// <summary>How the client reaches the bridge.</summary>
    internal enum Transport
    {
        /// <summary>Straight to the add-in's own HTTP endpoint. No Python.</summary>
        Http,

        /// <summary>
        /// The client launches arcgis-pro-mcp.exe, which relays over TCP.
        /// For clients that cannot speak to an HTTP MCP server.
        /// </summary>
        Stdio,
    }

    /// <summary>
    /// One AI client this add-in can register itself with.
    ///
    /// Every one of these paths and shapes was read off a real installation
    /// rather than guessed: a config written in the wrong shape does not fail,
    /// it is silently ignored, and the user is left looking at a client that
    /// says nothing is wrong and still cannot see ArcGIS Pro.
    /// </summary>
    internal sealed class McpClient
    {
        public string Id { get; set; }
        public string Name { get; set; }
        public string ConfigPath { get; set; }
        public ConfigShape Shape { get; set; }
        public Transport Transport { get; set; }

        /// <summary>The key the URL goes under. Antigravity uses serverUrl.</summary>
        public string UrlKey { get; set; } = "url";

        /// <summary>
        /// Somewhere that exists if the client is installed, even when it has
        /// no config file yet -- which is the normal state before anyone has
        /// added an MCP server.
        /// </summary>
        public string[] InstalledMarkers { get; set; } = Array.Empty<string>();

        public bool IsInstalled =>
            File.Exists(ConfigPath)
            || InstalledMarkers.Any(m => Directory.Exists(m) || File.Exists(m));

        public string ServerName => "arcgis";
    }

    internal static class McpClientCatalog
    {
        public const string HttpUrl = "http://127.0.0.1:6520/mcp";

        private static string Home(params string[] parts) =>
            Path.Combine(new[] { Environment.GetFolderPath(
                Environment.SpecialFolder.UserProfile) }.Concat(parts).ToArray());

        private static string AppData(params string[] parts) =>
            Path.Combine(new[] { Environment.GetFolderPath(
                Environment.SpecialFolder.ApplicationData) }.Concat(parts).ToArray());

        private static string LocalAppData(params string[] parts) =>
            Path.Combine(new[] { Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData) }.Concat(parts).ToArray());

        /// <summary>
        /// Claude Desktop ships two ways on Windows and they do not share a
        /// config file. The classic installer reads %APPDATA%\Claude. The
        /// Microsoft Store build is a packaged app, so what it sees as %APPDATA%
        /// is really its own LocalCache\Roaming inside %LOCALAPPDATA%\Packages.
        /// Writing to the wrong one of the two does not fail -- the file is
        /// simply never read, and the button goes green over nothing.
        /// </summary>
        private static string ClaudeDesktopConfig()
        {
            const string leaf = "claude_desktop_config.json";
            var packages = LocalAppData("Packages");
            if (Directory.Exists(packages))
            {
                foreach (var package in Directory.GetDirectories(packages, "Claude_*"))
                {
                    var packaged = Path.Combine(
                        package, "LocalCache", "Roaming", "Claude", leaf);
                    if (File.Exists(packaged)
                        || Directory.Exists(Path.GetDirectoryName(packaged)))
                        return packaged;
                }
            }
            return AppData("Claude", leaf);
        }

        /// <summary>
        /// The clients, in the order they appear on the ribbon. Order is by how
        /// likely someone is to be using it with ArcGIS Pro, not alphabetical.
        /// </summary>
        public static IReadOnlyList<McpClient> All { get; } = new List<McpClient>
        {
            new McpClient
            {
                Id = "claude-code",
                Name = "Claude Code",
                ConfigPath = Home(".claude.json"),
                Shape = ConfigShape.JsonMcpServers,
                Transport = Transport.Http,
                InstalledMarkers = new[] { Home(".claude"), AppData("Claude Code") },
            },
            new McpClient
            {
                Id = "codex",
                Name = "Codex",
                ConfigPath = Home(".codex", "config.toml"),
                Shape = ConfigShape.Toml,
                // Streamable HTTP connects directly to the installed add-in.
                Transport = Transport.Http,
                InstalledMarkers = new[] { Home(".codex") },
            },
            new McpClient
            {
                Id = "antigravity",
                Name = "Antigravity",
                ConfigPath = Home(".gemini", "antigravity", "mcp_config.json"),
                Shape = ConfigShape.JsonMcpServers,
                Transport = Transport.Http,
                UrlKey = "serverUrl",
                InstalledMarkers = new[]
                {
                    Home(".antigravity"), Home(".gemini", "antigravity"),
                    AppData("Antigravity"),
                },
            },
            new McpClient
            {
                Id = "vscode",
                Name = "VS Code",
                ConfigPath = AppData("Code", "User", "mcp.json"),
                Shape = ConfigShape.JsonServers,
                Transport = Transport.Http,
                InstalledMarkers = new[] { AppData("Code", "User") },
            },
            new McpClient
            {
                Id = "cursor",
                Name = "Cursor",
                ConfigPath = Home(".cursor", "mcp.json"),
                Shape = ConfigShape.JsonMcpServers,
                Transport = Transport.Http,
                InstalledMarkers = new[] { Home(".cursor") },
            },
            new McpClient
            {
                Id = "cline",
                Name = "Cline",
                ConfigPath = Home(".cline", "data", "settings", "cline_mcp_settings.json"),
                Shape = ConfigShape.JsonMcpServers,
                Transport = Transport.Http,
                InstalledMarkers = new[] { Home(".cline") },
            },
            new McpClient
            {
                Id = "gemini-cli",
                Name = "Gemini CLI",
                ConfigPath = Home(".gemini", "settings.json"),
                Shape = ConfigShape.JsonMcpServers,
                Transport = Transport.Http,
                InstalledMarkers = new[] { Home(".gemini") },
            },
            new McpClient
            {
                Id = "claude-desktop",
                Name = "Claude Desktop",
                ConfigPath = ClaudeDesktopConfig(),
                Shape = ConfigShape.JsonMcpServers,
                // Claude Desktop launches servers; it does not dial out to one.
                Transport = Transport.Stdio,
                // The Store build keeps its logs outside the package, so that
                // folder is the marker that it is installed at all.
                InstalledMarkers = new[]
                {
                    AppData("Claude"),
                    LocalAppData("Claude"),
                    Path.GetDirectoryName(ClaudeDesktopConfig()),
                },
            },
        };

        public static McpClient ById(string id) =>
            All.FirstOrDefault(c => c.Id == id);
    }

    /// <summary>Reads and writes the client config files.</summary>
    internal static class McpClientRegistrar
    {
        private static readonly JsonDocumentOptions Lenient = new JsonDocumentOptions
        {
            // VS Code's own files are JSON with comments, and a config that
            // will not parse is worse than one that loses a comment.
            CommentHandling = JsonCommentHandling.Skip,
            AllowTrailingCommas = true,
        };

        /// <summary>
        /// A client that can only launch a server still has to reach the same
        /// HTTP endpoint as every other client, so the add-in writes the piece
        /// that joins the two and points the client at that. Windows PowerShell
        /// ships with Windows, which is the whole point: nothing for the user
        /// to install first, no Python, no Node, no pip.
        /// </summary>
        private const string StdioBridgeScript = @"# ArcGIS Pro MCP -- stdio to HTTP bridge.
#
# Written by the ArcGIS Pro MCP add-in, not by hand. Clients that can only
# launch a server run this, and it forwards each JSON-RPC message to the
# add-in listening inside ArcGIS Pro. It is rewritten whenever the add-in
# registers a client, so an edit here does not survive.

$ErrorActionPreference = 'Stop'
$url = '__URL__'

Add-Type -AssemblyName System.Net.Http
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
[Console]::InputEncoding = $utf8

$client = New-Object System.Net.Http.HttpClient
# Geoprocessing can take a while, and a timeout here would look like the tool
# failing rather than still running.
$client.Timeout = [TimeSpan]::FromMinutes(30)
[void]$client.DefaultRequestHeaders.Accept.ParseAdd('application/json')
[void]$client.DefaultRequestHeaders.Accept.ParseAdd('text/event-stream')

while ($null -ne ($line = [Console]::In.ReadLine())) {
    if ($line.Trim().Length -eq 0) { continue }
    try {
        $content = New-Object System.Net.Http.StringContent($line, $utf8, 'application/json')
        $response = $client.PostAsync($url, $content).GetAwaiter().GetResult()
        $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    } catch {
        # ArcGIS Pro is closed, or the bridge is stopped. A request carries an
        # id and is owed an answer; a notification has none and expects silence.
        $id = $null
        try { $id = (ConvertFrom-Json $line).id } catch { }
        if ($null -eq $id) { continue }
        $body = @{
            jsonrpc = '2.0'
            id      = $id
            error   = @{
                code    = -32000
                message = ""ArcGIS Pro is not answering on $url. Open ArcGIS Pro and check that the MCP tab shows the bridge running.""
            }
        } | ConvertTo-Json -Compress -Depth 6
    }
    # A notification gets 202 and no body, so there is nothing to write.
    if (-not [string]::IsNullOrEmpty($body)) {
        [Console]::Out.Write($body + ""`n"")
        [Console]::Out.Flush()
    }
}
";

        private static string StdioBridgePath() => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ArcGIS Pro MCP", "stdio-bridge.ps1");

        /// <summary>
        /// Writes the bridge and returns its path. Rewritten when it differs,
        /// so upgrading the add-in fixes the bridge at the next registration
        /// rather than leaving an old one behind.
        /// </summary>
        public static string EnsureStdioBridge()
        {
            var path = StdioBridgePath();
            var wanted = StdioBridgeScript.Replace("__URL__", McpClientCatalog.HttpUrl);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            if (!File.Exists(path) || File.ReadAllText(path) != wanted)
                File.WriteAllText(path, wanted, new UTF8Encoding(false));
            return path;
        }

        /// <summary>
        /// The full path: a launched server gets no shell, so no PATH lookup.
        /// </summary>
        private static string PowerShellPath()
        {
            var system = Environment.GetFolderPath(Environment.SpecialFolder.System);
            var full = Path.Combine(system, "WindowsPowerShell", "v1.0", "powershell.exe");
            return File.Exists(full) ? full : "powershell.exe";
        }

        // The params constructor takes JsonNode, so each string converts to a
        // plain JSON value. A collection initializer would call Add<T> and build
        // a customized value instead, which will not serialize without a resolver.
        private static JsonArray StdioArguments(string bridge) => new JsonArray(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", bridge);

        public static bool IsRegistered(McpClient client)
        {
            try
            {
                if (!File.Exists(client.ConfigPath)) return false;
                var text = File.ReadAllText(client.ConfigPath);

                if (client.Shape == ConfigShape.Toml)
                {
                    var tomlSection = Regex.Match(text, TomlSectionPattern(client.ServerName, false));
                    if (!tomlSection.Success) return false;
                    if (client.Transport != Transport.Http) return true;
                    // An old stdio registration needs the Add/Update flow,
                    // not the Remove flow. Do not mark it as HTTP-ready.
                    return Regex.IsMatch(tomlSection.Value,
                        @"(?m)^[ \t]*url[ \t]*=[ \t]*[""']"
                        + Regex.Escape(McpClientCatalog.HttpUrl) + @"[""'][ \t]*(?:#.*)?\r?$")
                        && !Regex.IsMatch(tomlSection.Value, @"(?m)^[ \t]*(command|args)[ \t]*=");
                }

                var root = JsonNode.Parse(text, null, Lenient) as JsonObject;
                var section = root?[SectionName(client)] as JsonObject;
                if (section?[client.ServerName] is not JsonObject entry) return false;
                if (client.Transport != Transport.Stdio) return true;
                // Pointing at the old Python relay is not ready to use, so
                // report it as unregistered and let the button update it.
                return entry["args"] is JsonArray arguments
                    && arguments.Any(a => (string)a == StdioBridgePath());
            }
            catch (Exception)
            {
                // An unreadable config is not a registered one, and the button
                // should still be usable.
                return false;
            }
        }

        /// <summary>
        /// How this client would reach the bridge, in words, so a confirmation
        /// prompt can say what it is about to write. Throws for the same
        /// reasons Register would, so the caller finds out before asking the
        /// user rather than after.
        /// </summary>
        public static string DescribeConnection(McpClient client)
        {
            if (client.Transport == Transport.Http)
                return $"connects to {McpClientCatalog.HttpUrl}";
            return $"launches a PowerShell bridge to {McpClientCatalog.HttpUrl}";
        }

        public static string Register(McpClient client)
        {
            var launcher = client.Transport == Transport.Stdio
                ? EnsureStdioBridge()
                : null;

            Directory.CreateDirectory(Path.GetDirectoryName(client.ConfigPath));
            Backup(client.ConfigPath);

            if (client.Shape == ConfigShape.Toml) return RegisterToml(client, launcher);
            return RegisterJson(client, launcher);
        }

        public static string Unregister(McpClient client)
        {
            if (!File.Exists(client.ConfigPath))
                return $"{client.Name} has no config file, so there is nothing registered.";

            Backup(client.ConfigPath);

            if (client.Shape == ConfigShape.Toml)
            {
                var text = File.ReadAllText(client.ConfigPath);
                var trimmed = RemoveTomlSection(text, client.ServerName);
                if (trimmed == text) return $"'{client.ServerName}' was not in {client.Name}.";
                File.WriteAllText(client.ConfigPath, trimmed);
                return $"Removed '{client.ServerName}' from {client.Name}.";
            }

            var root = JsonNode.Parse(File.ReadAllText(client.ConfigPath), null, Lenient)
                       as JsonObject;
            var section = root?[SectionName(client)] as JsonObject;
            if (section == null || !section.ContainsKey(client.ServerName))
                return $"'{client.ServerName}' was not in {client.Name}.";

            section.Remove(client.ServerName);
            Write(client.ConfigPath, root);
            return $"Removed '{client.ServerName}' from {client.Name}.";
        }

        // --- json --------------------------------------------------------------

        private static string SectionName(McpClient client) =>
            client.Shape == ConfigShape.JsonServers ? "servers" : "mcpServers";

        private static string RegisterJson(McpClient client, string launcher)
        {
            var root = File.Exists(client.ConfigPath)
                ? JsonNode.Parse(File.ReadAllText(client.ConfigPath), null, Lenient) as JsonObject
                  ?? new JsonObject()
                : new JsonObject();

            var name = SectionName(client);
            if (root[name] is not JsonObject section)
            {
                section = new JsonObject();
                root[name] = section;
            }

            JsonObject entry;
            if (client.Transport == Transport.Http)
            {
                entry = new JsonObject { [client.UrlKey] = McpClientCatalog.HttpUrl };
                // Antigravity infers the transport from serverUrl and rejects
                // an unexpected "type"; the others want it stated.
                if (client.UrlKey == "url") entry["type"] = "http";
            }
            else
            {
                entry = new JsonObject
                {
                    ["command"] = PowerShellPath(),
                    ["args"] = StdioArguments(launcher),
                };
            }

            section[client.ServerName] = entry;
            Write(client.ConfigPath, root);

            return $"Registered '{client.ServerName}' with {client.Name}.\n\n"
                 + $"{client.ConfigPath}\n\nRestart {client.Name} to pick it up.";
        }

        private static void Write(string path, JsonNode root)
        {
            File.WriteAllText(path,
                root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }),
                new UTF8Encoding(false));
        }

        // --- toml --------------------------------------------------------------

        private static string RegisterToml(McpClient client, string launcher)
        {
            var text = File.Exists(client.ConfigPath)
                ? RemoveTomlSection(File.ReadAllText(client.ConfigPath), client.ServerName)
                : "";

            if (text.Length > 0 && !text.EndsWith("\n")) text += "\n";

            // Appended at the end: a TOML table runs to the next header, so a
            // new one is only safe after everything already there.
            var section = new StringBuilder();
            section.AppendLine();
            section.AppendLine($"[mcp_servers.{client.ServerName}]");
            if (client.Transport == Transport.Http)
                section.AppendLine($"url = \"{McpClientCatalog.HttpUrl}\"");
            else
            {
                section.AppendLine($"command = '{launcher}'");
                section.AppendLine("args = []");
            }

            File.WriteAllText(client.ConfigPath, text + section, new UTF8Encoding(false));

            return $"Registered '{client.ServerName}' with {client.Name}.\n\n"
                 + $"{client.ConfigPath}\n\nRestart {client.Name} to pick it up.";
        }

        /// <summary>
        /// Drop [mcp_servers.name] and everything under it, up to the next
        /// table header -- which is where a TOML table ends.
        /// </summary>
        private static string RemoveTomlSection(string text, string name)
        {
            return Regex.Replace(text, TomlSectionPattern(name, true), "").TrimEnd() + "\n";
        }

        private static string TomlSectionPattern(string name, bool children)
        {
            var key = Regex.Escape(name);
            var server = $"(?:{key}|\"{key}\"|'{key}')";
            return $@"(?m)^[ \t]*\[mcp_servers[ \t]*\.[ \t]*{server}"
                + (children ? @"(?:\.[^\]]+)?" : "")
                + @"[ \t]*\][^\n]*(?:\n|$)(?:(?![ \t]*\[)[^\n]*\n?)*";
        }

        // --- safety ------------------------------------------------------------

        /// <summary>
        /// Keep a copy before touching someone's editor config. Rewriting the
        /// JSON reformats the whole file and drops any comments, and one of
        /// these files is 50KB of unrelated settings.
        /// </summary>
        private static void Backup(string path)
        {
            if (!File.Exists(path)) return;
            var backup = path + ".arcgis-mcp.bak";
            File.Copy(path, backup, overwrite: true);
        }
    }
}
