using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using ArcGIS.Desktop.Core.Geoprocessing;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>
    /// Running geoprocessing tools, so the whole toolbox stays reachable
    /// without arcpy.
    ///
    /// ArcGIS Pro's API takes parameter values by position and offers no way
    /// to ask a tool what its parameters are called. arcpy does know, so the
    /// ordering is dumped once by scripts/dump_gp_parameters.py and embedded
    /// here -- that is what lets these commands accept named parameters.
    /// </summary>
    internal static class GeoprocessingCommands
    {
        private const string Group = "geoprocessing";
        private const string ParameterResource = "ArcGISProMCP.Resources.gp-parameters.json";

        private static readonly Lazy<Dictionary<string, string[]>> ParameterOrder =
            new Lazy<Dictionary<string, string[]>>(LoadParameterOrder);

        public static void Register()
        {
            CommandRouter.RegisterAsync("run_geoprocessing_tool", Group,
                "Run any geoprocessing tool, by named or positional parameters.",
                RunToolAsync);
            CommandRouter.Register("list_geoprocessing_tools", Group,
                "Search the available geoprocessing tools by name.", ListTools,
                runOnMct: false);
            CommandRouter.Register("describe_geoprocessing_tool", Group,
                "A tool's parameter names, in the order it takes them.",
                DescribeTool, runOnMct: false);
            CommandRouter.Register("list_toolboxes", Group,
                "List the toolbox aliases tools are grouped under.", ListToolboxes,
                runOnMct: false);
            CommandRouter.RegisterAsync("run_python_toolbox_tool", Group,
                "Run a tool from a .pyt, .atbx or .tbx toolbox on disk.",
                RunToolboxToolAsync);
            CommandRouter.Register("check_extension", Group,
                "Check an ArcGIS extension licence.", CheckExtension, runOnMct: false);
            CommandRouter.Register("get_messages", Group,
                "Messages from the most recent geoprocessing run.", GetMessages,
                runOnMct: false);
        }

        // --- the parameter table ---------------------------------------------

        private static Dictionary<string, string[]> LoadParameterOrder()
        {
            var table = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase);
            try
            {
                var assembly = typeof(GeoprocessingCommands).Assembly;
                using (var stream = assembly.GetManifestResourceStream(ParameterResource))
                {
                    if (stream == null) return table;
                    using (var reader = new StreamReader(stream))
                    using (var document = JsonDocument.Parse(reader.ReadToEnd()))
                    {
                        foreach (var entry in document.RootElement.EnumerateObject())
                        {
                            table[entry.Name] = entry.Value.EnumerateArray()
                                .Select(v => v.GetString()).ToArray();
                        }
                    }
                }
            }
            catch
            {
                // Without the table only positional calls work, which is still
                // better than failing to load.
            }
            return table;
        }

        private static string[] OrderFor(string toolName)
        {
            var table = ParameterOrder.Value;
            if (table.TryGetValue(toolName, out var order)) return order;

            // Accept either "analysis.Buffer" or "Buffer_analysis".
            if (toolName.Contains("."))
            {
                var parts = toolName.Split('.');
                var flipped = $"{parts[parts.Length - 1]}_{parts[parts.Length - 2]}";
                if (table.TryGetValue(flipped, out order)) return order;
            }
            else if (toolName.Contains("_"))
            {
                var index = toolName.LastIndexOf('_');
                var flipped = $"{toolName.Substring(index + 1)}.{toolName.Substring(0, index)}";
                if (table.TryGetValue(flipped, out order)) return order;
            }
            return null;
        }

        // --- running ---------------------------------------------------------

        private static object ValueOf(JsonElement element)
        {
            switch (element.ValueKind)
            {
                case JsonValueKind.String: return element.GetString();
                case JsonValueKind.Number: return element.GetDouble();
                case JsonValueKind.True: return true;
                case JsonValueKind.False: return false;
                case JsonValueKind.Null: return null;
                case JsonValueKind.Array:
                    return string.Join(";", element.EnumerateArray().Select(ValueOf));
                default: return element.GetRawText();
            }
        }

        private static async Task<object> RunToolAsync(Params parameters)
        {
            var toolName = parameters.Require("tool_name");
            var values = new List<object>();
            var usedNames = new List<string>();

            var positional = parameters.Raw("args");
            if (positional.ValueKind == JsonValueKind.Array)
            {
                values.AddRange(positional.EnumerateArray().Select(ValueOf));
            }
            else
            {
                var named = parameters.GetObject("parameters");
                if (named == null)
                    throw new ArgumentException(
                        "Provide parameters (named) or args (positional).");

                var order = OrderFor(toolName);
                if (order == null)
                    throw new ArgumentException(
                        $"The parameter order for '{toolName}' is not known, so named "
                        + "parameters cannot be placed. Pass args as a positional list, "
                        + "or check the name with describe_geoprocessing_tool.");

                var unknown = named.Keys.Where(
                    key => !order.Contains(key, StringComparer.OrdinalIgnoreCase)).ToList();
                if (unknown.Count > 0)
                    throw new ArgumentException(
                        $"{toolName} has no parameter(s) named {string.Join(", ", unknown)}. "
                        + $"It takes: {string.Join(", ", order)}");

                // Positional values, trimmed after the last one actually given.
                var slots = new object[order.Length];
                var lastUsed = -1;
                for (var i = 0; i < order.Length; i++)
                {
                    var match = named.Keys.FirstOrDefault(
                        key => string.Equals(key, order[i], StringComparison.OrdinalIgnoreCase));
                    if (match == null) continue;
                    slots[i] = ValueOf(named[match]);
                    usedNames.Add(order[i]);
                    lastUsed = i;
                }
                values.AddRange(slots.Take(lastUsed + 1));
            }

            var flags = FlagsFor(parameters.GetBool("add_to_map"));

            var environments = MapCommands.Environment.Count > 0
                ? Geoprocessing.MakeEnvironmentArray(
                    workspace: MapCommands.Environment.TryGetValue("workspace", out var ws) ? ws : null,
                    outputCoordinateSystem: MapCommands.Environment.TryGetValue(
                        "outputCoordinateSystem", out var cs) ? cs : null,
                    extent: MapCommands.Environment.TryGetValue("extent", out var ex) ? ex : null,
                    mask: MapCommands.Environment.TryGetValue("mask", out var mask) ? mask : null,
                    cellSize: MapCommands.Environment.TryGetValue("cellSize", out var cell) ? cell : null,
                    overwriteoutput: parameters.Has("overwrite")
                        ? parameters.GetBool("overwrite")
                        : (bool?)null)
                : (parameters.Has("overwrite")
                    ? Geoprocessing.MakeEnvironmentArray(
                        overwriteoutput: parameters.GetBool("overwrite"))
                    : null);

            var started = DateTime.Now;
            var result = await Geoprocessing.ExecuteToolAsync(
                toolName, Geoprocessing.MakeValueArray(values.ToArray()),
                environments, null, null, flags).ConfigureAwait(false);
            LastResult = result;

            if (result.IsFailed)
            {
                var messages = result.ErrorMessages != null && result.ErrorMessages.Any()
                    ? string.Join("; ", result.ErrorMessages.Select(m => m.Text))
                    : "the tool reported no error text";
                throw new InvalidOperationException($"{toolName} failed: {messages}");
            }

            var data = new Dictionary<string, object>
            {
                ["tool"] = toolName,
                ["outputs"] = result.Values?.ToList(),
                ["return_value"] = result.ReturnValue,
                ["elapsed_seconds"] = Math.Round((DateTime.Now - started).TotalSeconds, 2),
                ["messages"] = result.Messages?.Select(m => m.Text).Take(50).ToList(),
            };
            if (usedNames.Count > 0) data["parameters_used"] = usedNames;
            return data;
        }

        /// <summary>
        /// A tool in a toolbox on disk is addressed by the toolbox path plus
        /// the tool name. No parameter-order table exists for one, so the
        /// values have to come in positionally.
        /// </summary>
        private static async Task<object> RunToolboxToolAsync(Params parameters)
        {
            var toolboxPath = parameters.Require("toolbox_path");
            var toolName = parameters.Require("tool_name");

            if (!File.Exists(toolboxPath) && !Directory.Exists(toolboxPath))
                throw new ArgumentException($"No toolbox at {toolboxPath}");

            var positional = parameters.Raw("args");
            var values = new List<object>();
            if (positional.ValueKind == JsonValueKind.Array)
            {
                values.AddRange(positional.EnumerateArray().Select(ValueOf));
            }
            else
            {
                var named = parameters.GetObject("parameters");
                if (named != null && named.Count > 0)
                    // A custom toolbox publishes no parameter order this add-in
                    // can read, so named values would have to be guessed into
                    // slots. Saying so beats putting them in the wrong ones.
                    throw new ArgumentException(
                        "Tools from a toolbox on disk take positional values: pass "
                        + "args as a list in the tool's own parameter order. Named "
                        + "parameters work only for the built-in tools, whose order "
                        + "is known.");
            }

            var started = DateTime.Now;
            var result = await Geoprocessing.ExecuteToolAsync(
                Path.Combine(toolboxPath, toolName),
                Geoprocessing.MakeValueArray(values.ToArray()),
                null, null, null,
                FlagsFor(parameters.GetBool("add_to_map"))).ConfigureAwait(false);
            LastResult = result;

            if (result.IsFailed)
            {
                var messages = result.ErrorMessages != null && result.ErrorMessages.Any()
                    ? string.Join("; ", result.ErrorMessages.Select(m => m.Text))
                    : "the tool reported no error text";
                throw new InvalidOperationException($"{toolName} failed: {messages}");
            }

            return new Dictionary<string, object>
            {
                ["toolbox"] = toolboxPath,
                ["tool"] = toolName,
                ["outputs"] = result.Values?.ToList(),
                ["return_value"] = result.ReturnValue,
                ["elapsed_seconds"] = Math.Round((DateTime.Now - started).TotalSeconds, 2),
                ["messages"] = result.Messages?.Select(m => m.Text).Take(50).ToList(),
            };
        }

        /// <summary>
        /// Which flags a run needs. GPExecuteToolFlags.Default already includes
        /// AddOutputsToMap -- "adds outputs to map and refreshes project items"
        /// -- so ORing AddOutputsToMap onto it does nothing, and add_to_map:false
        /// silently added the output anyway. Every intermediate result a
        /// workflow produced ended up in the table of contents because of it.
        /// </summary>
        private static GPExecuteToolFlags FlagsFor(bool addToMap)
        {
            return addToMap
                ? GPExecuteToolFlags.Default
                : GPExecuteToolFlags.RefreshProjectItems | GPExecuteToolFlags.AddToHistory;
        }

        private static IGPResult LastResult;

        /// <summary>
        /// Run a tool with named parameters, placed using the embedded order.
        /// Shared with the commands that are a single tool run under a
        /// friendlier name, so none of them hand-builds a positional array.
        /// </summary>
        public static async Task<IGPResult> RunNamedAsync(
            string toolName, IDictionary<string, object> named, bool addToMap)
        {
            var order = OrderFor(toolName)
                ?? throw new ArgumentException(
                    $"The parameter order for '{toolName}' is not known.");

            var unknown = named.Keys.Where(
                key => !order.Contains(key, StringComparer.OrdinalIgnoreCase)).ToList();
            if (unknown.Count > 0)
                throw new ArgumentException(
                    $"{toolName} has no parameter(s) named {string.Join(", ", unknown)}. "
                    + $"It takes: {string.Join(", ", order)}");

            var slots = new object[order.Length];
            var lastUsed = -1;
            for (var i = 0; i < order.Length; i++)
            {
                var match = named.Keys.FirstOrDefault(
                    key => string.Equals(key, order[i], StringComparison.OrdinalIgnoreCase));
                if (match == null || named[match] == null) continue;
                slots[i] = named[match];
                lastUsed = i;
            }

            var flags = FlagsFor(addToMap);

            var result = await Geoprocessing.ExecuteToolAsync(
                toolName,
                Geoprocessing.MakeValueArray(slots.Take(lastUsed + 1).ToArray()),
                null, null, null, flags).ConfigureAwait(false);
            LastResult = result;
            return result;
        }

        // --- introspection ---------------------------------------------------

        private static object ListTools(Params parameters)
        {
            var wildcard = (parameters.GetString("wildcard", "*") ?? "*").Trim('*');
            var toolbox = parameters.GetString("toolbox");
            var limit = parameters.GetInt("limit", 500);

            var names = ParameterOrder.Value.Keys
                .Where(name => name.Contains("."))          // the alias.Tool form only
                .Where(name => string.IsNullOrEmpty(wildcard)
                               || name.IndexOf(wildcard, StringComparison.OrdinalIgnoreCase) >= 0)
                .Where(name => string.IsNullOrWhiteSpace(toolbox)
                               || name.StartsWith(toolbox + ".", StringComparison.OrdinalIgnoreCase))
                .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
                .ToList();

            return new Dictionary<string, object>
            {
                ["pattern"] = parameters.GetString("wildcard", "*"),
                ["count"] = names.Count,
                ["tools"] = names.Take(limit).ToList(),
                ["truncated"] = names.Count > limit,
            };
        }

        private static object DescribeTool(Params parameters)
        {
            var toolName = parameters.Require("tool_name");
            var order = OrderFor(toolName);
            if (order == null)
                throw new ArgumentException(
                    $"Tool not found: {toolName}. Search with list_geoprocessing_tools.");

            return new Dictionary<string, object>
            {
                ["tool"] = toolName,
                ["parameters"] = order.Select((name, index) => new Dictionary<string, object>
                {
                    ["name"] = name,
                    ["position"] = index,
                }).ToList(),
                ["usage"] = $"{toolName}({string.Join(", ", order)})",
                ["note"] = "Names and order come from arcpy, captured when the add-in was "
                         + "built. Pass them as named parameters.",
            };
        }

        private static object ListToolboxes(Params parameters)
        {
            var aliases = ParameterOrder.Value.Keys
                .Where(name => name.Contains("."))
                .Select(name => name.Substring(0, name.IndexOf('.')))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(alias => alias, StringComparer.OrdinalIgnoreCase)
                .ToList();

            return new Dictionary<string, object>
            {
                ["toolbox_aliases"] = aliases,
                ["tool_count"] = ParameterOrder.Value.Keys.Count(n => n.Contains(".")),
            };
        }

        private static object CheckExtension(Params parameters)
        {
            var name = parameters.Require("extension");
            // Extension licensing is not exposed to add-ins the way arcpy exposes
            // it; the tools themselves fail with a clear message when unlicensed.
            return new Dictionary<string, object>
            {
                ["extension"] = name,
                ["status"] = "unknown",
                ["note"] = "ArcGIS Pro does not expose extension checkout to add-ins. "
                         + "Run the tool: it reports clearly if the licence is missing.",
            };
        }

        private static object GetMessages(Params parameters)
        {
            if (LastResult == null)
                return new Dictionary<string, object> { ["messages"] = new List<string>() };

            var severity = parameters.GetInt("severity");
            var messages = LastResult.Messages ?? new List<IGPMessage>();
            var filtered = severity >= 2
                ? LastResult.ErrorMessages?.Select(m => m.Text).ToList()
                : messages.Select(m => m.Text).ToList();

            return new Dictionary<string, object>
            {
                ["messages"] = filtered,
                ["failed"] = LastResult.IsFailed,
            };
        }
    }
}
