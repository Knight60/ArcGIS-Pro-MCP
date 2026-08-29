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
                // Codex's stable config takes command/args. Rather than bet on
                // which build supports a url, it launches the Python entry
                // point, which relays to this same add-in.
                Transport = Transport.Stdio,
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
                ConfigPath = AppData("Claude", "claude_desktop_config.json"),
                Shape = ConfigShape.JsonMcpServers,
                // Claude Desktop launches servers; it does not dial out to one.
                Transport = Transport.Stdio,
                InstalledMarkers = new[] { AppData("Claude") },
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
        /// The Python relay, for the clients that can only launch a server.
        /// Null when it is not installed, which is worth saying out loud
        /// rather than writing a config that points at nothing.
        /// </summary>
        public static string StdioLauncher()
        {
            var candidates = new List<string>();
            var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            var python = Path.Combine(appData, "Python");
            if (Directory.Exists(python))
            {
                foreach (var version in Directory.GetDirectories(python))
                    candidates.Add(Path.Combine(version, "Scripts", "arcgis-pro-mcp.exe"));
            }

            var pathVariable = Environment.GetEnvironmentVariable("PATH") ?? "";
            foreach (var folder in pathVariable.Split(Path.PathSeparator))
            {
                if (string.IsNullOrWhiteSpace(folder)) continue;
                candidates.Add(Path.Combine(folder.Trim(), "arcgis-pro-mcp.exe"));
            }

            return candidates.FirstOrDefault(File.Exists);
        }

        public static bool IsRegistered(McpClient client)
        {
            try
            {
                if (!File.Exists(client.ConfigPath)) return false;
                var text = File.ReadAllText(client.ConfigPath);

                if (client.Shape == ConfigShape.Toml)
                    return Regex.IsMatch(text,
                        $@"^\s*\[mcp_servers\.{Regex.Escape(client.ServerName)}\]",
                        RegexOptions.Multiline);

                var root = JsonNode.Parse(text, null, Lenient) as JsonObject;
                var section = root?[SectionName(client)] as JsonObject;
                return section != null && section.ContainsKey(client.ServerName);
            }
            catch (Exception)
            {
                // An unreadable config is not a registered one, and the button
                // should still be usable.
                return false;
            }
        }

        public static string Register(McpClient client)
        {
            var launcher = client.Transport == Transport.Stdio ? StdioLauncher() : null;
            if (client.Transport == Transport.Stdio && launcher == null)
                throw new InvalidOperationException(
                    $"{client.Name} launches an MCP server rather than connecting to a "
                    + "URL, so it needs the Python relay -- and arcgis-pro-mcp.exe is not "
                    + "installed. Install it with:  pip install arcgis-pro-mcp");

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
                    ["command"] = launcher,
                    ["args"] = new JsonArray(),
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
            section.AppendLine($"command = '{launcher}'");
            section.AppendLine("args = []");

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
            var pattern = $@"(?m)^[ \t]*\[mcp_servers\.{Regex.Escape(name)}(\.[^\]]+)?\][^\n]*\n"
                        + @"(?:(?![ \t]*\[)[^\n]*\n?)*";
            return Regex.Replace(text, pattern, "").TrimEnd() + "\n";
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
