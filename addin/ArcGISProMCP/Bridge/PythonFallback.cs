using System;
using System.Text.Json;
using System.Threading.Tasks;
namespace ArcGISProMCP.Bridge
{
    internal static class PythonFallback
    {
        public const int DefaultPort = 6511;
        public static int Port { get; set; } = DefaultPort;
        public static object Describe() => new { enabled = false, note = "Python fallback disabled by hardened security policy." };
        public static Task<object> SendAsync(string command, JsonElement parameters) =>
            throw new NotSupportedException("Python fallback is disabled.");
    }
}
