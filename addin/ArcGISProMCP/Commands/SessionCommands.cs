using System;
using System.Threading.Tasks;
using System.Threading;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Layouts;
using ArcGIS.Desktop.Mapping;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>Session, project and map-level commands.</summary>
    internal static class SessionCommands
    {
        private const string Group = "project";

        public static void Register()
        {
            CommandRouter.RegisterAsync("run_batch", Group,
                "Run several commands in one round trip.", RunBatchAsync);

            // Answered without touching the object model, so it stays
            // responsive even when ArcGIS Pro is busy.
            CommandRouter.Register("ping", Group,
                "Check that the bridge is reachable.", Ping, runOnMct: false);

            CommandRouter.Register("get_capabilities", Group,
                "List every command this bridge supports.",
                _ => CommandRouter.Describe(), runOnMct: false);

            CommandRouter.Register("diagnose", Group,
                "Self-check: ArcGIS Pro version, project, active map and view.", Diagnose);

            CommandRouter.Register("get_arcgis_info", Group,
                "ArcGIS Pro version and the current project.", GetArcGisInfo);

            CommandRouter.Register("get_project_info", Group,
                "Project paths, default geodatabase, maps and layouts.", GetProjectInfo);

            CommandRouter.Register("list_maps", Group,
                "List all maps with coordinate system and layer counts.", ListMaps);

            CommandRouter.Register("get_map_extent", Group,
                "The combined extent of a map's layers.", GetMapExtent);
        }

        private static object Ping(Params parameters)
        {
            var server = MCPModule.Current?.Server;
            return new Dictionary<string, object>
            {
                ["pong"] = true,
                ["implementation"] = "addin",
                ["pid"] = Process.GetCurrentProcess().Id,
                ["port"] = server?.Port,
                ["command_count"] = CommandRouter.Count,
                // Deliberately not read here: Project.Current needs the MCT.
                ["project_path"] = null,
            };
        }

        private static object GetArcGisInfo(Params parameters)
        {
            var project = Project.Current;

            // The SDK assembly version is 13.x while the product is 3.x, so
            // read the version off ArcGISPro.exe -- that is the number people
            // mean when they say which ArcGIS Pro they are on.
            string version = null, assemblyVersion = null;
            try
            {
                version = System.Diagnostics.Process.GetCurrentProcess()
                    .MainModule?.FileVersionInfo?.ProductVersion;
            }
            catch { /* fall back to the assembly version below */ }
            try
            {
                assemblyVersion = System.Reflection.Assembly
                    .GetAssembly(typeof(Project))?.GetName().Version?.ToString();
            }
            catch { }

            return new Dictionary<string, object>
            {
                ["product"] = "ArcGIS Pro",
                ["version"] = version ?? assemblyVersion,
                ["sdk_assembly_version"] = assemblyVersion,
                ["project_path"] = project?.URI,
                ["project_name"] = project?.Name,
                ["default_geodatabase"] = project?.DefaultGeodatabasePath,
                ["home_folder"] = project?.HomeFolderPath,
                ["implementation"] = "addin",
            };
        }

        private static object GetProjectInfo(Params parameters)
        {
            var project = MapHelpers.RequireProject();
            var maps = project.GetItems<MapProjectItem>().Select(item =>
            {
                var map = item.GetMap();
                return new Dictionary<string, object>
                {
                    ["name"] = map.Name,
                    ["map_type"] = map.MapType.ToString(),
                    ["layer_count"] = map.GetLayersAsFlattenedList().Count,
                    ["table_count"] = map.GetStandaloneTablesAsFlattenedList().Count,
                    ["spatial_reference"] = map.SpatialReference?.Name,
                };
            }).ToList();

            return new Dictionary<string, object>
            {
                ["path"] = project.URI,
                ["name"] = project.Name,
                ["home_folder"] = project.HomeFolderPath,
                ["default_geodatabase"] = project.DefaultGeodatabasePath,
                ["default_toolbox"] = project.DefaultToolboxPath,
                ["maps"] = maps,
                ["layouts"] = project.GetItems<LayoutProjectItem>()
                                     .Select(item => item.Name).ToList(),
                ["active_map"] = MapView.Active?.Map?.Name,
            };
        }

        private static object ListMaps(Params parameters)
        {
            return MapHelpers.RequireProject().GetItems<MapProjectItem>().Select(item =>
            {
                var map = item.GetMap();
                return new Dictionary<string, object>
                {
                    ["name"] = map.Name,
                    ["map_type"] = map.MapType.ToString(),
                    ["spatial_reference"] = MapHelpers.Describe(map.SpatialReference),
                    ["layer_count"] = map.GetLayersAsFlattenedList().Count,
                    ["table_count"] = map.GetStandaloneTablesAsFlattenedList().Count,
                    ["bookmark_count"] = map.GetBookmarks().Count,
                };
            }).ToList();
        }

        private static object GetMapExtent(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            ArcGIS.Core.Geometry.Envelope combined = null;

            foreach (var layer in map.GetLayersAsFlattenedList().OfType<BasicFeatureLayer>())
            {
                try
                {
                    var extent = layer.QueryExtent();
                    if (extent == null || extent.IsEmpty) continue;
                    combined = combined == null
                        ? extent
                        : combined.Union(extent);
                }
                catch
                {
                    // A broken or empty layer should not sink the whole answer.
                }
            }

            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["extent"] = MapHelpers.Describe(combined),
            };
        }

        private static object Diagnose(Params parameters)
        {
            var checks = new List<Dictionary<string, object>>();
            var ok = true;

            void Check(string name, Func<object> probe)
            {
                var entry = new Dictionary<string, object> { ["check"] = name };
                try
                {
                    entry["result"] = probe();
                    entry["status"] = "ok";
                }
                catch (Exception exception)
                {
                    entry["status"] = "failed";
                    entry["error"] = $"{exception.GetType().Name}: {exception.Message}";
                    ok = false;
                }
                checks.Add(entry);
            }

            Check("addin", () => new Dictionary<string, object>
            {
                ["implementation"] = "C# add-in -- commands run on the MCT, no Python "
                                   + "dispatcher needed",
                ["commands"] = CommandRouter.Count,
                ["port"] = MCPModule.Current?.Server?.Port,
            });

            Check("project", () =>
            {
                var project = MapHelpers.RequireProject();
                return new Dictionary<string, object>
                {
                    ["path"] = project.URI,
                    ["default_gdb"] = project.DefaultGeodatabasePath,
                    ["map_count"] = project.GetItems<MapProjectItem>().Count(),
                };
            });

            Check("active_map", () =>
            {
                var map = MapHelpers.ResolveMap(parameters);
                return new Dictionary<string, object>
                {
                    ["map"] = map.Name,
                    ["layers"] = map.GetLayersAsFlattenedList().Count,
                };
            });

            Check("map_view", () =>
            {
                var view = MapView.Active;
                if (view == null)
                    throw new InvalidOperationException(
                        "No active map view -- camera and export commands need one.");
                return new Dictionary<string, object> { ["scale"] = view.Camera?.Scale };
            });

            Check("python_fallback", () => PythonFallback.Describe());

            return new Dictionary<string, object>
            {
                ["checks"] = checks,
                ["ok"] = ok,
                ["command_count"] = CommandRouter.Count,
            };
        }

        /// <summary>
        /// Runs a list of commands in order. Each step is dispatched exactly as
        /// if it had arrived on its own, so a step this add-in does not
        /// implement still reaches the Python bridge.
        ///
        /// The saving is the round trip, not the dispatch: a command costs
        /// milliseconds here, and the socket round trip costs more than that.
        /// </summary>
        private static async Task<object> RunBatchAsync(Params parameters)
        {
            if (Interlocked.Exchange(ref _inBatch, 1) == 1)
                throw new InvalidOperationException(
                    "run_batch cannot contain another run_batch.");

            try
            {
                var continueOnError = parameters.GetBool("continue_on_error");
                var results = new List<Dictionary<string, object>>();
                var failed = 0;
                var step = 0;

                foreach (var item in parameters.GetObjectList("commands"))
                {
                    step++;
                    var command = item.Require("command");
                    var stepParameters = item.Raw("params");

                    var entry = new Dictionary<string, object>
                    {
                        ["step"] = step,
                        ["command"] = command,
                    };

                    try
                    {
                        entry["data"] = await CommandRouter.DispatchAsync(
                            command, new Params(stepParameters), stepParameters)
                            .ConfigureAwait(false);
                        entry["success"] = true;
                    }
                    catch (Exception exception)
                    {
                        failed++;
                        entry["success"] = false;
                        entry["error"] = Unwrap(exception).Message;
                        results.Add(entry);

                        if (!continueOnError)
                            return new Dictionary<string, object>
                            {
                                ["results"] = results,
                                ["completed"] = results.Count,
                                ["failed"] = failed,
                                ["stopped_at"] = step,
                                ["message"] = $"Step {step} ({command}) failed and the "
                                              + "batch stopped. Pass continue_on_error "
                                              + "to run the rest anyway.",
                            };
                        continue;
                    }

                    results.Add(entry);
                }

                return new Dictionary<string, object>
                {
                    ["results"] = results,
                    ["completed"] = results.Count,
                    ["failed"] = failed,
                };
            }
            finally
            {
                Interlocked.Exchange(ref _inBatch, 0);
            }
        }

        private static int _inBatch;

        /// <summary>
        /// An awaited handler surfaces as an AggregateException whose message
        /// says nothing useful; the caller wants the message underneath.
        /// </summary>
        private static Exception Unwrap(Exception exception)
        {
            while (exception is AggregateException aggregate
                   && aggregate.InnerExceptions.Count == 1)
                exception = aggregate.InnerExceptions[0];
            return exception;
        }
    }
}
