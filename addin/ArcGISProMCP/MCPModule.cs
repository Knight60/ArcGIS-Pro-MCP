using System;
using System.IO;
using ArcGIS.Desktop.Framework;
using ArcGIS.Desktop.Framework.Contracts;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP
{
    /// <summary>
    /// The add-in itself. Marked autoLoad in Config.daml, so the bridge comes
    /// up with ArcGIS Pro and there is nothing for the user to start.
    /// </summary>
    internal class MCPModule : Module
    {
        private static MCPModule _instance;

        public static MCPModule Current =>
            _instance ??= (MCPModule)FrameworkApplication.FindModule("ArcGISProMCP_Module");

        public BridgeServer Server { get; } = new BridgeServer();

        /// <summary>MCP straight over HTTP, so no separate server process is needed.</summary>
        public McpHttpServer Mcp { get; } = new McpHttpServer();

        /// <summary>Set when startup failed, so the Status button can explain.</summary>
        public string StartupError { get; private set; }

        /// <summary>
        /// Startup runs before there is any UI to complain to, and a failure
        /// here just looks like "the bridge is not listening". The log is the
        /// only way to find out why without attaching a debugger.
        /// </summary>
        public static string LogPath => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ArcGIS-MCP", "addin.log");

        internal static void Log(string message)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(LogPath));
                File.AppendAllText(LogPath,
                    $"{DateTime.Now:yyyy-MM-dd HH:mm:ss}  {message}{System.Environment.NewLine}");
            }
            catch
            {
                // Logging must never be the thing that breaks startup.
            }
        }

        protected override bool Initialize()
        {
            Log("--- module initialising ---");

            try
            {
                Commands.CommandRegistry.RegisterAll();
                Log($"registered {CommandRouter.Count} commands");
            }
            catch (Exception exception)
            {
                StartupError = $"Could not register commands: {exception}";
                Log(StartupError);
                return true;   // a broken bridge must not stop ArcGIS Pro loading
            }

            try
            {
                Log(Server.Start());
            }
            catch (Exception exception)
            {
                StartupError = $"Could not start the bridge: {exception}";
                Log(StartupError);
            }

            try
            {
                Log(Mcp.Start());
            }
            catch (Exception exception)
            {
                // The TCP bridge still works without this, so it is not fatal.
                Log($"Could not start MCP over HTTP: {exception.Message}");
            }

            return true;
        }

        protected override void Uninitialize()
        {
            try { Log(Mcp.Stop()); } catch { /* shutting down */ }
            try { Log(Server.Stop()); } catch { /* shutting down */ }
            base.Uninitialize();
        }

        protected override bool CanUnload()
        {
            Mcp.Stop();
            Server.Stop();
            return true;
        }
    }
}
