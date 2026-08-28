using System;
using System.Text;
using ArcGIS.Desktop.Framework.Contracts;
using ArcGIS.Desktop.Framework.Dialogs;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.UI
{
    /// <summary>
    /// The bridge starts on its own; these are for the times it has to be
    /// restarted, silenced, or explained.
    /// </summary>
    internal class StartServerButton : Button
    {
        protected override void OnClick()
        {
            try
            {
                var message = MCPModule.Current.Server.Start();
                MessageBox.Show(message, "ArcGIS Pro MCP");
            }
            catch (Exception exception)
            {
                MessageBox.Show(exception.Message, "ArcGIS Pro MCP -- could not start");
            }
        }
    }

    internal class StopServerButton : Button
    {
        protected override void OnClick()
        {
            MessageBox.Show(MCPModule.Current.Server.Stop(), "ArcGIS Pro MCP");
        }
    }

    internal class StatusButton : Button
    {
        protected override void OnClick()
        {
            var server = MCPModule.Current.Server;
            var report = new StringBuilder();

            report.AppendLine(server.IsRunning
                ? $"Listening on 127.0.0.1:{server.Port}"
                : "Not listening.");
            report.AppendLine($"Commands implemented here: {CommandRouter.Count}");
            report.AppendLine($"Requests served: {server.RequestCount}");
            if (server.StartedAt.HasValue)
                report.AppendLine($"Started: {server.StartedAt:yyyy-MM-dd HH:mm:ss}");

            report.AppendLine();
            report.AppendLine($"Anything not implemented here is forwarded to the Python "
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
}
