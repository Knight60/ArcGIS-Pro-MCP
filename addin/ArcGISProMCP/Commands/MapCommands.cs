using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using ArcGIS.Desktop.Framework;
using ArcGIS.Core.CIM;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Mapping;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>Project and map housekeeping, bookmarks, and GP environments.</summary>
    internal static class MapCommands
    {
        private const string Group = "project";

        /// <summary>
        /// Geoprocessing environments. ArcGIS Pro has no ambient arcpy.env for
        /// an add-in, so these are held here and passed to each tool run.
        /// </summary>
        public static readonly Dictionary<string, object> Environment =
            new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);

        public static void Register()
        {
            // Saving is a UI-thread operation, not an MCT one, so it is
            // registered async and dispatched explicitly.
            CommandRouter.RegisterAsync("save_project", Group,
                "Save the project, or save a copy elsewhere.", SaveProjectAsync);
            CommandRouter.Register("create_map", Group,
                "Create a new map or scene.", CreateMap);
            CommandRouter.Register("remove_map", Group,
                "Delete a map from the project.", RemoveMap);
            CommandRouter.Register("activate_map", Group,
                "Open a map's view in the ArcGIS Pro UI.", ActivateMap);
            CommandRouter.Register("set_map_properties", Group,
                "Rename a map.", SetMapProperties);
            CommandRouter.Register("get_environment", Group,
                "Read the geoprocessing environment used for tool runs.",
                _ => new Dictionary<string, object>(Environment), runOnMct: false);
            CommandRouter.Register("set_environment", Group,
                "Set geoprocessing environment values applied to later tool runs.",
                SetEnvironment, runOnMct: false);

            CommandRouter.Register("list_bookmarks", "view",
                "List the spatial bookmarks on a map.", ListBookmarks);
            CommandRouter.Register("create_bookmark", "view",
                "Save the current view as a named bookmark.", CreateBookmark);
            CommandRouter.Register("apply_bookmark", "view",
                "Zoom the map view to a bookmark.", ApplyBookmark);
            CommandRouter.Register("delete_bookmark", "view",
                "Delete a bookmark from a map.", DeleteBookmark);
        }

        // --- project ---------------------------------------------------------

        /// <summary>
        /// Runs work on ArcGIS Pro's UI thread. Project.SaveAsync and friends
        /// touch UI-owned objects and throw "a different thread owns it" when
        /// called from the MCT, where the other commands run.
        /// </summary>
        private static Task OnUiThread(Func<Task> work)
        {
            var dispatcher = FrameworkApplication.Current?.Dispatcher;
            if (dispatcher == null || dispatcher.CheckAccess()) return work();
            return dispatcher.Invoke(work);
        }

        internal static Task SaveEditsOnUiThread() =>
            OnUiThread(() => Project.Current.SaveEditsAsync());

        internal static Task DiscardEditsOnUiThread() =>
            OnUiThread(() => Project.Current.DiscardEditsAsync());

        private static async Task<object> SaveProjectAsync(Params parameters)
        {
            var project = Project.Current
                ?? throw new InvalidOperationException("No project is open.");
            var saveAs = parameters.GetString("save_as_path");

            if (!string.IsNullOrWhiteSpace(saveAs))
            {
                // SaveAsAsync leaves the original open, matching save_as_path.
                await OnUiThread(() => project.SaveAsAsync(saveAs)).ConfigureAwait(false);
                return new Dictionary<string, object>
                {
                    ["saved_copy"] = saveAs,
                    ["original"] = project.URI,
                };
            }

            await OnUiThread(() => project.SaveAsync()).ConfigureAwait(false);
            return new Dictionary<string, object> { ["saved"] = project.URI };
        }

        private static object CreateMap(Params parameters)
        {
            var name = parameters.Require("name");
            var type = (parameters.GetString("map_type", "MAP") ?? "MAP").ToUpperInvariant();
            var map = MapFactory.Instance.CreateMap(
                name,
                type == "SCENE" ? MapType.Scene : MapType.Map,
                MapViewingMode.Map,
                ParseBasemap(parameters.GetString("basemap")));

            return new Dictionary<string, object>
            {
                ["created"] = map.Name,
                ["map_type"] = map.MapType.ToString(),
            };
        }

        /// <summary>Pro takes a Basemap value, not the layer name arcpy accepts.</summary>
        private static Basemap ParseBasemap(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return Basemap.ProjectDefault;
            switch (name.Replace(" ", string.Empty).ToUpperInvariant())
            {
                // Names follow what ArcGIS Pro shows in its basemap gallery.
                case "IMAGERY": return Basemap.Satellite;
                case "IMAGERYHYBRID": return Basemap.Hybrid;
                case "STREETS": return Basemap.Streets;
                case "NAVIGATION": return Basemap.NavigationVector;
                case "LIGHTGRAYCANVAS": return Basemap.Gray;
                case "DARKGRAYCANVAS": return Basemap.DarkGray;
                case "TERRAIN": return Basemap.Terrain;
                case "OCEANS": return Basemap.Oceans;
                case "OPENSTREETMAP": return Basemap.OpenStreetMap;
                case "NATIONALGEOGRAPHIC": return Basemap.NationalGeographic;
                case "NONE": return Basemap.None;
                default: return Basemap.Topographic;
            }
        }

        private static MapProjectItem FindMapItem(string name)
        {
            var item = Project.Current.GetItems<MapProjectItem>().FirstOrDefault(
                i => string.Equals(i.Name, name, StringComparison.OrdinalIgnoreCase));
            if (item == null) throw new ArgumentException($"Map not found: {name}");
            return item;
        }

        private static object RemoveMap(Params parameters)
        {
            var name = parameters.Require("map_name");
            Project.Current.RemoveItem(FindMapItem(name));
            return new Dictionary<string, object> { ["removed"] = name };
        }

        private static object ActivateMap(Params parameters)
        {
            var name = parameters.Require("map_name");
            var map = FindMapItem(name).GetMap();
            ProApp.Panes.CreateMapPaneAsync(map).Wait();
            return new Dictionary<string, object> { ["activated"] = map.Name };
        }

        private static object SetMapProperties(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var changed = new Dictionary<string, object>();
            if (parameters.Has("new_name"))
            {
                map.SetName(parameters.GetString("new_name"));
                changed["name"] = map.Name;
            }
            if (parameters.Has("epsg"))
            {
                changed["epsg_warning"] =
                    "Changing a map's coordinate system is not exposed to add-ins; "
                    + "use run_geoprocessing_tool or change it in the UI.";
            }
            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["changed"] = changed,
            };
        }

        private static object SetEnvironment(Params parameters)
        {
            var settings = parameters.GetObject("settings")
                ?? throw new ArgumentException("settings is required.");
            var applied = new Dictionary<string, object>();

            foreach (var pair in settings)
            {
                if (pair.Value.ValueKind == System.Text.Json.JsonValueKind.Null)
                {
                    Environment.Remove(pair.Key);
                    applied[pair.Key] = null;
                    continue;
                }
                object value = pair.Value.ValueKind switch
                {
                    System.Text.Json.JsonValueKind.String => pair.Value.GetString(),
                    System.Text.Json.JsonValueKind.Number => pair.Value.GetDouble(),
                    System.Text.Json.JsonValueKind.True => true,
                    System.Text.Json.JsonValueKind.False => false,
                    _ => pair.Value.GetRawText(),
                };
                Environment[pair.Key] = value;
                applied[pair.Key] = value;
            }

            return new Dictionary<string, object>
            {
                ["applied"] = applied,
                ["note"] = "These are passed to each geoprocessing run; ArcGIS Pro has "
                         + "no ambient environment for add-ins.",
            };
        }

        // --- bookmarks -------------------------------------------------------

        private static Bookmark FindBookmark(Map map, string name)
        {
            var bookmark = map.GetBookmarks().FirstOrDefault(
                b => string.Equals(b.Name, name, StringComparison.OrdinalIgnoreCase));
            if (bookmark == null)
                throw new ArgumentException(
                    $"Bookmark not found on map '{map.Name}': {name}. Available: "
                    + string.Join(", ", map.GetBookmarks().Select(b => b.Name)));
            return bookmark;
        }

        private static object ListBookmarks(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["bookmarks"] = map.GetBookmarks().Select(bookmark =>
                    new Dictionary<string, object> { ["name"] = bookmark.Name }).ToList(),
            };
        }

        private static object CreateBookmark(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var view = MapHelpers.RequireActiveView(map);
            var name = parameters.Require("name");
            var description = parameters.GetString("description");

            var bookmark = string.IsNullOrWhiteSpace(description)
                ? map.AddBookmark(view, name)
                : map.AddBookmark(view, name, description);

            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["created_bookmark"] = bookmark.Name,
                ["bookmarks"] = map.GetBookmarks().Select(b => b.Name).ToList(),
            };
        }

        private static object ApplyBookmark(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var view = MapHelpers.RequireActiveView(map);
            var bookmark = FindBookmark(map, parameters.Require("bookmark_name"));
            view.ZoomTo(bookmark);
            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["applied_bookmark"] = bookmark.Name,
                ["scale"] = view.Camera?.Scale,
            };
        }

        private static object DeleteBookmark(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var name = parameters.Require("bookmark_name");
            map.RemoveBookmark(FindBookmark(map, name));
            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["deleted_bookmark"] = name,
            };
        }
    }
}
