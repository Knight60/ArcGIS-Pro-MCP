using System;
using System.IO;
using ArcGIS.Desktop.Framework;
using ArcGIS.Desktop.Framework.Contracts;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP
{
    /// <summary>
    /// The add-in itself. Marked autoLoad in Config.daml, so the MCP server
    /// comes up with ArcGIS Pro and there is nothing for the user to start.
    /// </summary>
    internal class MCPModule : Module
    {
        private static MCPModule _instance;

        public static MCPModule Current =>
            _instance ??= (MCPModule)FrameworkApplication.FindModule("ArcGISProMCP_Module");

        /// <summary>
        /// MCP over HTTP on 127.0.0.1:6520 -- the one port the add-in opens,
        /// and the one the ribbon's Start/Stop button and Status report on.
        /// </summary>
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
                Log(Mcp.Start());
            }
            catch (Exception exception)
            {
                StartupError = $"Could not start MCP over HTTP: {exception.Message}";
                Log(StartupError);
            }

            return true;
        }

        protected override void Uninitialize()
        {
            try { Log(Mcp.Stop()); } catch { /* shutting down */ }
            base.Uninitialize();
        }

        protected override bool CanUnload()
        {
            Mcp.Stop();
            return true;
        }
    }
}
