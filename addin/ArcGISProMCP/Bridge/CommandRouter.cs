using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using System.Threading;
using ArcGIS.Desktop.Framework.Threading.Tasks;

namespace ArcGISProMCP.Bridge
{
    /// <summary>A command handler. Runs on the MCT unless registered otherwise.</summary>
    public delegate object CommandHandler(Params parameters);

    /// <summary>
    /// A handler that is already asynchronous, such as anything built on
    /// Geoprocessing.ExecuteToolAsync. These run off the MCT: the Pro API
    /// they call does its own marshalling, and awaiting inside QueuedTask
    /// would deadlock.
    /// </summary>
    public delegate Task<object> AsyncCommandHandler(Params parameters);

    /// <summary>
    /// Looks up a command and runs it where it is allowed to touch the project.
    ///
    /// ArcGIS Pro's object model may only be used on the Main CIM Thread, so
    /// everything is handed to QueuedTask.Run. Unlike the Python bridge this
    /// costs nothing in latency: Pro services the MCT queue continuously.
    ///
    /// Commands this add-in does not implement are forwarded to the Python
    /// bridge, which keeps arcpy -- and execute_arcpy_code in particular --
    /// available as an escape hatch.
    /// </summary>
    internal static class CommandRouter
    {
        private sealed class Registration
        {
            public string Name;
            public string Group;
            public string Summary;
            public CommandHandler Handler;
            public AsyncCommandHandler AsyncHandler;
            public bool RunOnMct;
        }

        private static readonly Dictionary<string, Registration> Commands =
            new Dictionary<string, Registration>(StringComparer.OrdinalIgnoreCase);

        public static int Count => Commands.Count;
        private static readonly SemaphoreSlim DispatchGate = new(1, 1);

        public static void Register(string name, string group, string summary,
                                    CommandHandler handler, bool runOnMct = true)
        {
            Commands[name] = new Registration
            {
                Name = name,
                Group = group,
                Summary = summary,
                Handler = handler,
                RunOnMct = runOnMct,
            };
        }

        public static void RegisterAsync(string name, string group, string summary,
                                         AsyncCommandHandler handler)
        {
            Commands[name] = new Registration
            {
                Name = name,
                Group = group,
                Summary = summary,
                AsyncHandler = handler,
                RunOnMct = false,
            };
        }

        public static bool Knows(string command)
        {
            return command != null && Commands.ContainsKey(command);
        }

        public static async Task<object> DispatchAsync(string command, Params parameters,
                                                       JsonElement rawParameters)
        {
            ToolPolicy.Demand(command, rawParameters);
            if (!Commands.TryGetValue(command, out var registration))
                throw new ArgumentException("Unknown command. Python fallback is disabled.");
            if (!await DispatchGate.WaitAsync(0).ConfigureAwait(false))
                throw new InvalidOperationException("Bridge busy. No operation was queued.");
            try
            {
                if (registration.AsyncHandler != null)
                    return await registration.AsyncHandler(parameters).ConfigureAwait(false);
                if (!registration.RunOnMct) return registration.Handler(parameters);
                return await QueuedTask.Run(() =>
                {
                    // The UI can revoke editing while a request waits for the MCT.
                    ToolPolicy.Demand(command, rawParameters);
                    return registration.Handler(parameters);
                }).ConfigureAwait(false);
            }
            finally { DispatchGate.Release(); }
        }

        /// <summary>Everything this bridge can do, grouped -- for get_capabilities.</summary>
        public static object Describe()
        {
            var groups = Commands.Values.Where(c => ToolPolicy.IsAdvertised(c.Name))
                .GroupBy(c => c.Group)
                .OrderBy(g => g.Key, StringComparer.Ordinal)
                .ToDictionary(
                    g => g.Key,
                    g => (object)g.OrderBy(c => c.Name, StringComparer.Ordinal)
                                  .Select(c => new Dictionary<string, object>
                                  {
                                      ["command"] = c.Name,
                                      ["summary"] = c.Summary,
                                      ["policy"] = ToolPolicy.Classification(c.Name),
                                  })
                                  .ToList());

            return new Dictionary<string, object>
            {
                ["implemented_by"] = "ArcGIS Pro add-in (C#)",
                ["command_count"] = Commands.Values.Count(c => ToolPolicy.IsAdvertised(c.Name)),
                ["editing_enabled"] = ToolPolicy.EditingEnabled,
                ["groups"] = groups,
                ["fallback"] = PythonFallback.Describe(),
            };
        }
    }
}
