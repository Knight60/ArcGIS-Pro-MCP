using System;
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

        /// <summary>Set when auto-start failed, so the Status button can explain.</summary>
        public string StartupError { get; private set; }

        protected override bool Initialize()
        {
            try
            {
                Commands.CommandRegistry.RegisterAll();
            }
            catch (Exception exception)
            {
                StartupError = $"Could not register commands: {exception.Message}";
                return true;   // a broken bridge must not stop ArcGIS Pro loading
            }

            try
            {
                Server.Start();
            }
            catch (Exception exception)
            {
                StartupError = $"Could not start the bridge: {exception.Message}";
            }

            return true;
        }

        protected override void Uninitialize()
        {
            try { Server.Stop(); } catch { /* shutting down */ }
            base.Uninitialize();
        }

        protected override bool CanUnload()
        {
            Server.Stop();
            return true;
        }
    }
}
