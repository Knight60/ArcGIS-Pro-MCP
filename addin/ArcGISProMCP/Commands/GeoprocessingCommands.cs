using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using ArcGIS.Desktop.Core.Geoprocessing;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>
    /// Running geoprocessing tools through Pro's own API, so the whole
    /// toolbox stays reachable without arcpy.
    /// </summary>
    internal static class GeoprocessingCommands
    {
        private const string Group = "geoprocessing";

        public static void Register()
        {
            // Async: ExecuteToolAsync does its own thread marshalling, and
            // awaiting it from inside QueuedTask would deadlock.
            CommandRouter.RegisterAsync("run_geoprocessing_tool", Group,
                "Run any geoprocessing tool.", RunToolAsync);
        }

        private static async Task<object> RunToolAsync(Params parameters)
        {
            var toolName = parameters.Require("tool_name");

            var positional = ReadArgs(parameters);
            if (positional == null)
            {
                // Pro's API takes positional values only, so a call written
                // with named parameters needs the tool's parameter order.
                // arcpy knows it, so hand the whole call to the Python bridge.
                if (parameters.Has("parameters"))
                {
                    return await PythonFallback
                        .SendAsync("run_geoprocessing_tool", parameters.Root)
                        .ConfigureAwait(false);
                }
                throw new ArgumentException(
                    "Provide args (a positional list) for the add-in to run the tool "
                    + "directly, or parameters (named) to have the Python bridge run it.");
            }

            var flags = GPExecuteToolFlags.Default;
            if (parameters.GetBool("add_to_map")) flags |= GPExecuteToolFlags.AddOutputsToMap;

            var values = Geoprocessing.MakeValueArray(positional.ToArray());
            var result = await Geoprocessing
                .ExecuteToolAsync(toolName, values, null, null, null, flags)
                .ConfigureAwait(false);

            if (result.IsFailed)
            {
                var messages = result.ErrorMessages != null
                    ? string.Join("; ", result.ErrorMessages.Select(m => m.Text))
                    : "no error text";
                throw new InvalidOperationException($"{toolName} failed: {messages}");
            }

            return new Dictionary<string, object>
            {
                ["tool"] = toolName,
                ["messages"] = result.Messages?.Select(m => m.Text).ToList(),
                ["outputs"] = result.Values?.ToList(),
                ["return_value"] = result.ReturnValue,
                ["elapsed_seconds"] = null,
            };
        }

        /// <summary>Positional arguments, or null when none were supplied.</summary>
        private static List<object> ReadArgs(Params parameters)
        {
            var raw = parameters.Raw("args");
            if (raw.ValueKind != JsonValueKind.Array) return null;

            var values = new List<object>();
            foreach (var item in raw.EnumerateArray())
            {
                switch (item.ValueKind)
                {
                    case JsonValueKind.String: values.Add(item.GetString()); break;
                    case JsonValueKind.Number: values.Add(item.GetDouble()); break;
                    case JsonValueKind.True: values.Add(true); break;
                    case JsonValueKind.False: values.Add(false); break;
                    case JsonValueKind.Null: values.Add(null); break;
                    default: values.Add(item.GetRawText()); break;
                }
            }
            return values;
        }
    }
}
