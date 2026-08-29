using System;
using System.Collections.Generic;
using System.Text;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using ArcGIS.Desktop.Framework.Contracts;
using ArcGIS.Desktop.Framework.Dialogs;
using ArcGISProMCP.Bridge;
using ArcGISProMCP.Clients;

namespace ArcGISProMCP.UI
{
    /// <summary>
    /// Ribbon images, loaded once each. The URIs are the pack form the
    /// assembly's own resources live under.
    /// </summary>
    internal static class Icons
    {
        private static readonly Dictionary<string, ImageSource> Cache =
            new Dictionary<string, ImageSource>();

        public static ImageSource Get(string name, int size = 32)
        {
            var key = name + size;
            lock (Cache)
            {
                if (Cache.TryGetValue(key, out var cached)) return cached;
                ImageSource image = null;
                try
                {
                    image = new BitmapImage(new Uri(
                        "pack://application:,,,/ArcGISProMCP;component/Images/"
                        + $"{name}{size}.png"));
                }
                catch (Exception)
                {
                    // A missing image must not take the ribbon down with it.
                }
                Cache[key] = image;
                return image;
            }
        }
    }

    /// <summary>
    /// Whether each AI client is installed, and whether it already has this
    /// server in its config.
    ///
    /// Buttons ask on every OnUpdate, which ArcGIS Pro calls whenever the UI
    /// goes idle, so the answers are cached: reading eight config files at
    /// idle rate would be pointless disk traffic. A click invalidates it, so
    /// the tick appears the moment the config changes.
    /// </summary>
    internal static class ClientStates
    {
        private sealed class State
        {
            public bool Installed;
            public bool Registered;
        }

        private static readonly Dictionary<string, State> Cache =
            new Dictionary<string, State>();
        private static DateTime _readAt = DateTime.MinValue;
        private static readonly TimeSpan MaxAge = TimeSpan.FromSeconds(5);

        public static void Invalidate() => _readAt = DateTime.MinValue;

        private static void EnsureFresh()
        {
            if (DateTime.UtcNow - _readAt < MaxAge) return;
            foreach (var client in McpClientCatalog.All)
            {
                var installed = client.IsInstalled;
                Cache[client.Id] = new State
                {
                    Installed = installed,
                    Registered = installed && McpClientRegistrar.IsRegistered(client),
                };
            }
            _readAt = DateTime.UtcNow;
        }

        public static bool IsInstalled(string id)
        {
            lock (Cache) { EnsureFresh(); return Cache[id].Installed; }
        }

        public static bool IsRegistered(string id)
        {
            lock (Cache) { EnsureFresh(); return Cache[id].Registered; }
        }
    }

    /// <summary>
    /// One button for both directions, the way a play button does it: the icon
    /// is what the next click will do.
    ///
    /// Two separate buttons meant one of them was always the wrong one to
    /// press, and neither said whether the bridge was actually running.
    /// </summary>
    internal class ToggleServerButton : Button
    {
        protected override void OnUpdate()
        {
            var running = MCPModule.Current?.Server?.IsRunning ?? false;

            Caption = running ? "Stop bridge" : "Start bridge";
            LargeImage = Icons.Get(running ? "Stop" : "Start");
            SmallImage = Icons.Get(running ? "Stop" : "Start", 16);
            TooltipHeading = running ? "Stop the MCP bridge" : "Start the MCP bridge";
            Tooltip = running
                ? $"Listening on 127.0.0.1:{MCPModule.Current.Server.Port}. Stopping it "
                  + "takes this ArcGIS Pro session away from every AI client."
                : "Start listening so AI assistants can drive this ArcGIS Pro session.";
        }

        protected override void OnClick()
        {
            var server = MCPModule.Current.Server;
            try
            {
                var message = server.IsRunning ? server.Stop() : server.Start();
                MessageBox.Show(message, "ArcGIS Pro MCP");
            }
            catch (Exception exception)
            {
                MessageBox.Show(exception.Message, "ArcGIS Pro MCP -- could not switch");
            }
        }
    }

    /// <summary>
    /// The state of everything, and an icon that shows the important half of
    /// it without being clicked.
    /// </summary>
    internal class StatusButton : Button
    {
        protected override void OnUpdate()
        {
            var server = MCPModule.Current?.Server;
            var running = server?.IsRunning ?? false;

            LargeImage = Icons.Get(running ? "StatusOn" : "StatusOff");
            SmallImage = Icons.Get(running ? "StatusOn" : "StatusOff", 16);
            Caption = running ? $"Port {server.Port}" : "Not running";
            TooltipHeading = running ? "Bridge is listening" : "Bridge is stopped";
            Tooltip = "Port, commands served, which AI clients are connected, "
                    + "and anything that has gone wrong.";
        }

        protected override void OnClick()
        {
            var server = MCPModule.Current.Server;
            var report = new StringBuilder();

            report.AppendLine(server.IsRunning
                ? $"Listening on 127.0.0.1:{server.Port}"
                : "Not listening.");
            report.AppendLine($"MCP over HTTP: {McpClientCatalog.HttpUrl}");
            report.AppendLine($"Commands implemented here: {CommandRouter.Count}");
            report.AppendLine($"Requests served: {server.RequestCount}");
            if (server.StartedAt.HasValue)
                report.AppendLine($"Started: {server.StartedAt:yyyy-MM-dd HH:mm:ss}");

            ClientStates.Invalidate();
            report.AppendLine();
            report.AppendLine("AI clients:");
            foreach (var client in McpClientCatalog.All)
            {
                var state = !ClientStates.IsInstalled(client.Id)
                    ? "not installed"
                    : ClientStates.IsRegistered(client.Id) ? "connected" : "not connected";
                report.AppendLine($"  {client.Name,-16} {state}");
            }

            report.AppendLine();
            report.AppendLine("Anything not implemented here is forwarded to the Python "
                            + $"bridge on port {PythonFallback.Port}, which is where arcpy "
                            + "and execute_arcpy_code live. That bridge is optional.");

            if (!string.IsNullOrEmpty(MCPModule.Current.StartupError))
            {
                report.AppendLine();
                report.AppendLine("Startup problem: " + MCPModule.Current.StartupError);
            }
            if (!string.IsNullOrEmpty(server.LastError))
            {
                report.AppendLine();
                report.AppendLine("Last error:");
                report.AppendLine(Trim(server.LastError, 600));
            }

            MessageBox.Show(report.ToString(), "ArcGIS Pro MCP status");
        }

        private static string Trim(string text, int limit)
        {
            return text.Length <= limit ? text : text.Substring(0, limit) + " ...";
        }
    }

    /// <summary>
    /// Adds or removes this add-in from one AI client's config, and shows which
    /// of the two the click will do: a tick means it is already there.
    ///
    /// Adding a client is a catalog entry, a DAML button and a two-line subclass.
    /// </summary>
    internal abstract class ClientButtonBase : Button
    {
        protected abstract string ClientId { get; }

        private McpClient Client => McpClientCatalog.ById(ClientId);

        protected override void OnUpdate()
        {
            var client = Client;
            if (client == null) { Enabled = false; return; }

            var installed = ClientStates.IsInstalled(ClientId);
            var registered = installed && ClientStates.IsRegistered(ClientId);

            Enabled = installed;
            LargeImage = Icons.Get(registered ? "ClientLinked" : "ClientUnlinked");
            SmallImage = Icons.Get(registered ? "ClientLinked" : "ClientUnlinked", 16);

            if (!installed)
            {
                TooltipHeading = $"{client.Name} was not found";
                DisabledTooltip =
                    $"Nothing is installed at {client.ConfigPath}. Install {client.Name} "
                    + "first, or add the server by hand.";
                return;
            }

            TooltipHeading = registered
                ? $"{client.Name}: connected"
                : $"{client.Name}: not connected";
            Tooltip = registered
                ? $"'arcgis' is in {client.ConfigPath}.\nClick to remove it."
                : $"Click to add the 'arcgis' server to {client.ConfigPath}.";
        }

        /// <summary>
        /// Both directions ask first, and say which file is about to change.
        /// These are the user's own editor and assistant configs; a button that
        /// edited one on a single click -- possibly a misaimed one, since the
        /// same button does both jobs -- is not a button anyone can trust.
        /// </summary>
        protected override void OnClick()
        {
            var client = Client;
            if (client == null) return;

            try
            {
                if (McpClientRegistrar.IsRegistered(client)) ConfirmRemove(client);
                else ConfirmAdd(client);
            }
            catch (Exception exception)
            {
                MessageBox.Show(exception.Message, $"ArcGIS Pro MCP -- {client.Name}");
            }
            finally
            {
                // So the tick changes now, not in five seconds.
                ClientStates.Invalidate();
            }
        }

        private static void ConfirmAdd(McpClient client)
        {
            // Asked before the prompt, not after: a client that cannot be
            // registered should say so rather than confirm and then fail.
            var how = McpClientRegistrar.DescribeConnection(client);
            var exists = System.IO.File.Exists(client.ConfigPath);

            // TOML is edited as text -- one section appended -- so nothing else
            // in the file moves. The JSON files go through a parse and rewrite,
            // which reflows the whole file and loses comments. Saying "the JSON
            // is reformatted" about Codex's config.toml was simply untrue.
            var caveat = !exists ? ""
                : client.Shape == ConfigShape.Toml
                    ? "The file is copied to .arcgis-mcp.bak first. One section is "
                      + "appended; the rest of the file is left exactly as it is.\n\n"
                    : "The file is copied to .arcgis-mcp.bak first. Rewriting the JSON "
                      + "reflows the whole file and drops any comments in it.\n\n";

            var question =
                $"Add the 'arcgis' MCP server to {client.Name}?\n\n"
                + $"File:  {client.ConfigPath}\n"
                + (exists ? "" : "       (will be created)\n")
                + $"How:   {how}\n\n"
                + caveat
                + $"No other server in {client.Name}'s configuration is touched.";

            if (MessageBox.Show(question, "ArcGIS Pro MCP",
                                System.Windows.MessageBoxButton.YesNo)
                != System.Windows.MessageBoxResult.Yes) return;

            MessageBox.Show(McpClientRegistrar.Register(client), "ArcGIS Pro MCP");
        }

        private static void ConfirmRemove(McpClient client)
        {
            var question =
                $"Remove the 'arcgis' MCP server from {client.Name}?\n\n"
                + $"File:  {client.ConfigPath}\n\n"
                + $"{client.Name} will no longer be able to drive this ArcGIS Pro "
                + "session. The file is copied to .arcgis-mcp.bak first, and the "
                + "other servers in it are left alone.";

            if (MessageBox.Show(question, "ArcGIS Pro MCP",
                                System.Windows.MessageBoxButton.YesNo)
                != System.Windows.MessageBoxResult.Yes) return;

            MessageBox.Show(McpClientRegistrar.Unregister(client), "ArcGIS Pro MCP");
        }
    }

    /// <summary>Opens the project's page in the default browser.</summary>
    internal class InfoButton : Button
    {
        public const string ProjectUrl = "https://github.com/Knight60/ArcGIS-Pro-MCP";

        protected override void OnUpdate()
        {
            LargeImage = Icons.Get("Info");
            SmallImage = Icons.Get("Info", 16);
            TooltipHeading = "About ArcGIS Pro MCP";
            Tooltip = $"Open {ProjectUrl} in your browser:\n"
                    + "documentation, the tool list, and where to report a problem.";
        }

        protected override void OnClick()
        {
            try
            {
                // UseShellExecute, so Windows opens the URL with whatever the
                // default browser is. Without it .NET tries to execute the
                // string as a file and throws.
                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
                {
                    FileName = ProjectUrl,
                    UseShellExecute = true,
                });
            }
            catch (Exception exception)
            {
                MessageBox.Show(
                    $"Could not open a browser: {exception.Message}\n\n{ProjectUrl}",
                    "ArcGIS Pro MCP");
            }
        }
    }

    internal class ClaudeCodeButton : ClientButtonBase
    { protected override string ClientId => "claude-code"; }

    internal class CodexButton : ClientButtonBase
    { protected override string ClientId => "codex"; }

    internal class AntigravityButton : ClientButtonBase
    { protected override string ClientId => "antigravity"; }

    internal class VSCodeButton : ClientButtonBase
    { protected override string ClientId => "vscode"; }

    internal class CursorButton : ClientButtonBase
    { protected override string ClientId => "cursor"; }

    internal class ClineButton : ClientButtonBase
    { protected override string ClientId => "cline"; }

    internal class GeminiCliButton : ClientButtonBase
    { protected override string ClientId => "gemini-cli"; }

    internal class ClaudeDesktopButton : ClientButtonBase
    { protected override string ClientId => "claude-desktop"; }
}
