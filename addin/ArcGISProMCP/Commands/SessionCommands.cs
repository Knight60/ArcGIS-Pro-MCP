using System;
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
            var version = System.Reflection.Assembly
                .GetAssembly(typeof(Project))?.GetName().Version?.ToString();

            return new Dictionary<string, object>
            {
                ["product"] = "ArcGIS Pro",
                ["version"] = version,
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
    }
}
