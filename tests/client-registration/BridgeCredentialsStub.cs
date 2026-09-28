using System.IO;
namespace ArcGISProMCP.Bridge
{
    // Test-only credential; no real credential path is read or modified.
    internal static class BridgeCredentials
    {
        internal static string Token => "TEST-ONLY-CREDENTIAL";
        internal static void RejectLinks(string path) { }
        internal static void WritePrivateText(string path, string text) => File.WriteAllText(path, text);
    }
}
