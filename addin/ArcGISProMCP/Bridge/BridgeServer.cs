using System;
namespace ArcGISProMCP.Bridge
{
    // Compatibility status surface. The unauthenticated TCP transport is retired.
    internal sealed class BridgeServer : IDisposable
    {
        public const int DefaultPort = 6510;
        public bool IsRunning => false;
        public int Port => 0;
        public int RequestCount => 0;
        public string LastError => null;
        public DateTime? StartedAt => null;
        public string Start(int port = DefaultPort, bool autoPort = true) =>
            throw new NotSupportedException("Legacy TCP is disabled. Use authenticated MCP HTTP on port 6520.");
        public string Stop() => "Legacy TCP is disabled.";
        public void Dispose() { }
    }
}
