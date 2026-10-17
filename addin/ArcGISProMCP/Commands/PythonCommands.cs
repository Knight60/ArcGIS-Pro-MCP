using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using ArcGIS.Desktop.Core.Geoprocessing;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>
    /// execute_arcpy_code, run inside ArcGIS Pro without the Python bridge.
    ///
    /// A compiled add-in cannot run code composed at call time, so this used
    /// to be forwarded to the Python bridge -- which nobody could start from
    /// the ribbon, and which reaches the open project only through a
    /// dispatcher on Pro's Python thread, at up to ~28 s a call.
    ///
    /// The ModelBuilder tool Calculate Value (management.CalculateValue) runs
    /// a Python code block inside Pro, and run from here it executes on the
    /// Main CIM Thread, where arcpy.mp.ArcGISProject("CURRENT") resolves.
    /// Measured on ArcGIS Pro 3.7.1: 17 s for the first call while Pro
    /// initialises Python, then about 0.05 s. The code block below reproduces
    /// what the Python bridge's handler did: a namespace kept between calls,
    /// print() and stderr captured, the value of a final expression returned.
    ///
    /// Esri documents Calculate Value as available from ModelBuilder only.
    /// Running it through the SDK works on 3.7.1 but is not a documented use,
    /// so if it ever fails the command falls back to the Python bridge rather
    /// than leaving the third layer with nowhere to go. See docs/addin.md.
    /// </summary>
    internal static class PythonCommands
    {
        private const string Group = "utility";

        // Runs in Pro's own Python. The user's code arrives in a file, so its
        // size and quoting never meet the tool's expression parameter.
        private const string Runner = """
import ast, contextlib, io, json, sys, time, traceback, types

def _arcgis_mcp_run(path, reset):
    import arcpy
    module = sys.modules.get("_arcgis_mcp_session")
    if module is None or reset:
        module = types.ModuleType("_arcgis_mcp_session")
        sys.modules["_arcgis_mcp_session"] = module
    namespace = module.__dict__
    namespace.setdefault("arcpy", arcpy)
    namespace.setdefault("project", lambda: arcpy.mp.ArcGISProject("CURRENT"))
    with open(path, encoding="utf-8") as handle:
        code = handle.read()

    buffer = io.StringIO()
    started = time.time()
    result = {}
    value = None
    try:
        tree = ast.parse(code, mode="exec")
        body = list(tree.body)
        tail = None
        if body and isinstance(body[-1], ast.Expr):
            tail = ast.Expression(body.pop().value)
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            if body:
                exec(compile(ast.Module(body, type_ignores=[]), "<mcp>", "exec"), namespace)
            if tail is not None:
                value = eval(compile(tail, "<mcp>", "eval"), namespace)
    except BaseException:
        result["error"] = traceback.format_exc(limit=8)

    output = buffer.getvalue()
    result["elapsed_seconds"] = round(time.time() - started, 3)
    if output:
        result["output"] = output[:200000]
    if value is not None:
        result["value"] = repr(value)[:20000]
    if "error" not in result and not output and value is None:
        result["output"] = "(no output -- print() or end with an expression to return a value)"
    result["variables"] = sorted(
        k for k, v in namespace.items()
        if not k.startswith("_") and not callable(v)
        and not isinstance(v, types.ModuleType) and k != "arcpy")[:100]
    return json.dumps(result, default=str)
""";

        public static void Register()
        {
            CommandRouter.RegisterAsync("execute_arcpy_code", Group,
                "Run Python inside ArcGIS Pro, with the open project available.",
                ExecuteAsync);
        }

        private static readonly string CodeFolder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ArcGIS-MCP", "code");

        private static async Task<object> ExecuteAsync(Params parameters)
        {
            var code = parameters.Require("code");
            var reset = parameters.GetBool("reset_namespace");

            Directory.CreateDirectory(CodeFolder);
            var path = Path.Combine(CodeFolder, $"{Guid.NewGuid():N}.py");
            File.WriteAllText(path, code, new UTF8Encoding(false));
            try
            {
                var expression = $"_arcgis_mcp_run(r\"{path}\", {(reset ? "True" : "False")})";
                var result = await Geoprocessing.ExecuteToolAsync(
                    "management.CalculateValue",
                    Geoprocessing.MakeValueArray(expression, Runner, "String"),
                    null, null, null,
                    GPExecuteToolFlags.RefreshProjectItems).ConfigureAwait(false);

                if (result.IsFailed)
                {
                    // The runner catches everything the user's code raises, so a
                    // failure here means Calculate Value itself did not run.
                    var why = result.ErrorMessages != null && result.ErrorMessages.Any()
                        ? string.Join("; ", result.ErrorMessages.Select(m => Clean(m.Text)))
                        : "no error text";
                    MCPModule.Log($"execute_arcpy_code: Calculate Value failed ({why}); trying the Python bridge");
                    return await PythonFallback.SendAsync("execute_arcpy_code", parameters.Root)
                        .ConfigureAwait(false);
                }

                using (var document = JsonDocument.Parse(result.ReturnValue ?? "{}"))
                {
                    var data = JsonSerializer.Deserialize<Dictionary<string, object>>(
                        document.RootElement.GetRawText(), Protocol.SerializerOptions);
                    if (data.TryGetValue("error", out var error) && error != null)
                    {
                        var output = data.TryGetValue("output", out var o) ? o?.ToString() : null;
                        throw new InvalidOperationException(
                            "The code raised an error:\n" + error
                            + (string.IsNullOrEmpty(output) ? "" : "\nOutput before the error:\n" + output));
                    }
                    return data;
                }
            }
            finally
            {
                try { File.Delete(path); } catch { /* a leftover temp file is harmless */ }
            }
        }

        // Pro prefixes each traceback line of a tool error with a byte-order mark.
        private static string Clean(string text) => text?.Replace("﻿", "");
    }
}
