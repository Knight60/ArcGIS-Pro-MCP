using System;
using System.Collections.Generic;
using System.Linq;
using ArcGIS.Core.Data;
using System.IO;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Mapping;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>Adding, removing and configuring layers.</summary>
    internal static class LayerCommands
    {
        private const string Group = "layers";

        public static void Register()
        {
            CommandRouter.Register("get_layers", Group,
                "List the layers and standalone tables in a map.", GetLayers);

            CommandRouter.Register("get_layer_info", Group,
                "Full detail for one layer: source, CRS, extent, fields, feature count.",
                GetLayerInfo);

            CommandRouter.Register("add_layer", Group,
                "Add data to a map from a path or service URL.", AddLayer);

            CommandRouter.Register("remove_layer", Group,
                "Remove a layer from a map.", RemoveLayer);

            CommandRouter.Register("rename_layer", Group,
                "Rename a layer in the table of contents.", RenameLayer);

            CommandRouter.Register("set_layer_visibility", Group,
                "Show or hide one layer, several layers, or all of them.", SetVisibility);

            CommandRouter.Register("set_layer_transparency", Group,
                "Set layer transparency (0 opaque, 100 invisible).", SetTransparency);

            CommandRouter.Register("set_definition_query", Group,
                "Set a layer's definition query. Empty clears it.", SetDefinitionQuery);

            CommandRouter.Register("zoom_to_layer", Group,
                "Zoom the map view to a layer's extent.", ZoomToLayer);

            CommandRouter.Register("get_broken_layers", Group,
                "List layers and tables whose data source is missing.", GetBrokenLayers);

            CommandRouter.Register("add_web_layer", Group,
                "Add a web service layer by URL.", AddWebLayer);

            CommandRouter.Register("create_group_layer", Group,
                "Create a group layer, optionally moving layers into it.",
                CreateGroupLayer);

            CommandRouter.Register("duplicate_layer", Group,
                "Copy a layer within the map so it can be symbolised differently.",
                DuplicateLayer);

            CommandRouter.Register("move_layer", Group,
                "Reorder a layer, or move it into a group layer.", MoveLayer);

            CommandRouter.Register("set_basemap", Group,
                "Set the map's basemap.", SetBasemap);

            CommandRouter.Register("set_layer_scale_range", Group,
                "Limit the scale range a layer draws at.", SetScaleRange);

            CommandRouter.Register("repair_layer_source", Group,
                "Repoint a layer at a new workspace or dataset.", RepairSource);
        }

        /// <summary>
        /// Anything pointing at data that is no longer there -- a moved file,
        /// or an in-memory dataset after a restart.
        /// </summary>
        private static object GetBrokenLayers(Params parameters)
        {
            var broken = new List<Dictionary<string, object>>();

            foreach (var item in MapHelpers.RequireProject().GetItems<MapProjectItem>())
            {
                var map = item.GetMap();
                // Asking a layer for its status can itself throw while the map
                // is still settling, so each one is checked on its own.
                foreach (var layer in map.GetLayersAsFlattenedList())
                {
                    try
                    {
                        if (layer.ConnectionStatus == ConnectionStatus.Connected) continue;
                        broken.Add(new Dictionary<string, object>
                        {
                            ["map"] = map.Name,
                            ["layer"] = layer.Name,
                            ["kind"] = "layer",
                            ["status"] = layer.ConnectionStatus.ToString(),
                        });
                    }
                    catch (Exception exception)
                    {
                        broken.Add(new Dictionary<string, object>
                        {
                            ["map"] = map.Name,
                            ["layer"] = SafeName(layer),
                            ["kind"] = "layer",
                            ["status"] = $"could not be checked: {exception.Message}",
                        });
                    }
                }
                foreach (var table in map.GetStandaloneTablesAsFlattenedList())
                {
                    try
                    {
                        if (table.ConnectionStatus == ConnectionStatus.Connected) continue;
                        broken.Add(new Dictionary<string, object>
                        {
                            ["map"] = map.Name,
                            ["layer"] = table.Name,
                            ["kind"] = "table",
                            ["status"] = table.ConnectionStatus.ToString(),
                        });
                    }
                    catch (Exception exception)
                    {
                        broken.Add(new Dictionary<string, object>
                        {
                            ["map"] = map.Name,
                            ["layer"] = SafeName(table),
                            ["kind"] = "table",
                            ["status"] = $"could not be checked: {exception.Message}",
                        });
                    }
                }
            }

            return new Dictionary<string, object>
            {
                ["broken_count"] = broken.Count,
                ["broken_layers"] = broken,
            };
        }

        private static string SafeName(MapMember member)
        {
            try { return member.Name; } catch { return "(unnamed)"; }
        }

        private static object GetLayers(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var includeBasemap = parameters.GetBool("include_basemap");

            var layers = new List<Dictionary<string, object>>();
            var all = map.GetLayersAsFlattenedList();
            for (var index = 0; index < all.Count; index++)
            {
                var layer = all[index];
                var described = MapHelpers.Describe(layer, index);
                if (!includeBasemap && (bool)described["is_basemap"]) continue;
                layers.Add(described);
            }

            var tables = map.GetStandaloneTablesAsFlattenedList()
                .Select(table => new Dictionary<string, object> { ["name"] = table.Name })
                .ToList();

            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["layer_count"] = layers.Count,
                ["layers"] = layers,
                ["tables"] = tables,
            };
        }

        private static object GetLayerInfo(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.FindLayer(map, parameters.Require("layer_name"));
            var info = MapHelpers.Describe(layer);

            if (layer is BasicFeatureLayer featureLayer)
            {
                try
                {
                    info["extent"] = MapHelpers.Describe(featureLayer.QueryExtent());
                }
                catch (Exception exception)
                {
                    info["extent_error"] = exception.Message;
                }

                try
                {
                    using (var table = featureLayer.GetTable())
                    {
                        var definition = table.GetDefinition();
                        info["fields"] = definition.GetFields()
                            .Select(MapHelpers.Describe).ToList();
                        info["oid_field"] = definition.GetObjectIDField();
                        info["feature_count"] = table.GetCount();
                    }
                }
                catch (Exception exception)
                {
                    info["table_error"] = exception.Message;
                }
            }

            try
            {
                info["spatial_reference"] = MapHelpers.Describe(map.SpatialReference);
            }
            catch { /* not fatal */ }

            return info;
        }

        private static object AddLayer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var path = parameters.Require("path");

            var uri = Uri.TryCreate(path, UriKind.Absolute, out var parsed)
                ? parsed
                : new Uri(path, UriKind.RelativeOrAbsolute);

            var layer = LayerFactory.Instance.CreateLayer(uri, map);
            if (layer == null)
                throw new InvalidOperationException($"ArcGIS Pro could not add: {path}");

            return new Dictionary<string, object>
            {
                ["added"] = layer.Name,
                ["map"] = map.Name,
                ["source"] = path,
            };
        }

        private static object RemoveLayer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var name = parameters.Require("layer_name");

            // Remove every layer with that name: duplicates are easy to end up
            // with, since geoprocessing adds its outputs to the map as well.
            var matches = map.GetLayersAsFlattenedList()
                .Where(l => string.Equals(l.Name, name, StringComparison.OrdinalIgnoreCase))
                .ToList();

            if (matches.Count > 0)
            {
                foreach (var layer in matches) map.RemoveLayer(layer);
                return new Dictionary<string, object>
                {
                    ["removed"] = name,
                    ["count"] = matches.Count,
                    ["map"] = map.Name,
                };
            }

            // Standalone tables live beside the layers, not among them.
            var tables = map.GetStandaloneTablesAsFlattenedList()
                .Where(t => string.Equals(t.Name, name, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (tables.Count > 0)
            {
                map.RemoveStandaloneTables(tables);
                return new Dictionary<string, object>
                {
                    ["removed_table"] = name,
                    ["count"] = tables.Count,
                    ["map"] = map.Name,
                };
            }

            throw new ArgumentException(
                $"No layer or table called '{name}' in map '{map.Name}'.");
        }

        private static object RenameLayer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.FindLayer(map, parameters.Require("layer_name"));
            var previous = layer.Name;
            layer.SetName(parameters.Require("new_name"));
            return new Dictionary<string, object>
            {
                ["renamed_from"] = previous,
                ["renamed_to"] = layer.Name,
            };
        }

        private static object SetVisibility(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var visible = parameters.GetBool("visible", true);

            var names = parameters.GetStringList("layer_names");
            if (names == null && parameters.Has("layer_name"))
                names = new List<string> { parameters.GetString("layer_name") };

            var changed = new List<string>();
            if (names == null)
            {
                foreach (var layer in map.GetLayersAsFlattenedList())
                {
                    if (layer is TiledServiceLayer || layer is VectorTileLayer) continue;
                    layer.SetVisibility(visible);
                    changed.Add(layer.Name);
                }
            }
            else
            {
                foreach (var name in names)
                {
                    var layer = MapHelpers.FindLayer(map, name);
                    layer.SetVisibility(visible);
                    changed.Add(layer.Name);
                }
            }

            return new Dictionary<string, object>
            {
                ["visible"] = visible,
                ["layers"] = changed,
            };
        }

        private static object SetTransparency(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.FindLayer(map, parameters.Require("layer_name"));
            var transparency = Math.Max(0, Math.Min(100, parameters.GetDouble("transparency")));
            layer.SetTransparency(transparency);
            return new Dictionary<string, object>
            {
                ["layer"] = layer.Name,
                ["transparency"] = transparency,
            };
        }

        private static object SetDefinitionQuery(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.RequireFeatureLayer(map, parameters.Require("layer_name"));
            var query = parameters.GetString("query", string.Empty) ?? string.Empty;
            layer.SetDefinitionQuery(query);
            return new Dictionary<string, object>
            {
                ["layer"] = layer.Name,
                ["definition_query"] = string.IsNullOrEmpty(query) ? null : query,
            };
        }

        private static object ZoomToLayer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.RequireFeatureLayer(map, parameters.Require("layer_name"));
            var view = MapHelpers.RequireActiveView(map);

            var extent = layer.QueryExtent();
            if (extent == null || extent.IsEmpty)
                throw new InvalidOperationException($"Layer '{layer.Name}' has no extent to zoom to.");

            var expand = parameters.GetDouble("expand_factor");
            if (Math.Abs(expand) > double.Epsilon)
                extent = extent.Expand(1 + expand, 1 + expand, true);

            view.ZoomTo(extent);

            return new Dictionary<string, object>
            {
                ["zoomed_to"] = layer.Name,
                ["extent"] = MapHelpers.Describe(extent),
                ["scale"] = view.Camera?.Scale,
            };
        }

        // --- web layers -------------------------------------------------------

        private static object AddWebLayer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var url = parameters.Require("url");

            if (!Uri.TryCreate(url, UriKind.Absolute, out var uri))
                throw new ArgumentException($"'{url}' is not a URL.");

            // One service URL can bring in several layers -- a map service
            // publishes one per sublayer -- so report what actually arrived
            // rather than treating CreateLayer's return value as the whole story.
            var before = map.Layers.Count;
            var layer = LayerFactory.Instance.CreateLayer(uri, map);
            if (layer == null)
                throw new InvalidOperationException(
                    $"ArcGIS Pro could not add {url}. Check that the service is "
                    + "reachable, and that you are signed in if it is secured.");

            return new Dictionary<string, object>
            {
                ["added"] = layer.Name,
                ["layers_added"] = map.Layers.Count - before,
                ["type"] = layer.GetType().Name,
                ["map"] = map.Name,
                ["url"] = url,
            };
        }

        // --- arranging --------------------------------------------------------

        private static object CreateGroupLayer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var name = parameters.Require("name");

            var group = LayerFactory.Instance.CreateGroupLayer(map, 0, name);
            var moved = new List<string>();

            foreach (var member in parameters.GetStringList("layer_names")
                                   ?? new List<string>())
            {
                var layer = MapHelpers.FindLayer(map, member);
                map.MoveLayer(layer, group, moved.Count);
                moved.Add(layer.Name);
            }

            return new Dictionary<string, object>
            {
                ["created"] = group.Name,
                ["moved_in"] = moved,
                ["map"] = map.Name,
            };
        }

        private static object DuplicateLayer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.FindLayer(map, parameters.Require("layer_name"));

            if (!LayerFactory.Instance.CanCopyLayer(layer))
                throw new InvalidOperationException(
                    $"'{layer.Name}' cannot be copied within the map.");

            // The copy goes directly above the original, which is where anyone
            // duplicating a layer in order to restyle it expects to find it.
            var container = layer.Parent as ILayerContainerEdit ?? map;
            var index = container.Layers.IndexOf(layer);
            var copy = LayerFactory.Instance.CopyLayer(layer, container, index);

            var newName = parameters.GetString("new_name");
            if (!string.IsNullOrWhiteSpace(newName)) copy.SetName(newName);

            return new Dictionary<string, object>
            {
                ["duplicated"] = layer.Name,
                ["new_layer"] = copy.Name,
                ["map"] = map.Name,
            };
        }

        private static object MoveLayer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.FindLayer(map, parameters.Require("layer_name"));
            var groupName = parameters.GetString("group_layer");
            var referenceName = parameters.GetString("reference_layer");
            var position = (parameters.GetString("position", "BEFORE") ?? "BEFORE")
                .ToUpperInvariant();

            if (!string.IsNullOrWhiteSpace(groupName))
            {
                var group = MapHelpers.FindLayer(map, groupName) as GroupLayer
                    ?? throw new ArgumentException($"'{groupName}' is not a group layer.");
                map.MoveLayer(layer, group, 0);
                return new Dictionary<string, object>
                {
                    ["moved"] = layer.Name,
                    ["into_group"] = group.Name,
                    ["map"] = map.Name,
                };
            }

            if (string.IsNullOrWhiteSpace(referenceName))
                throw new ArgumentException(
                    "Give either reference_layer (with position) or group_layer.");

            var reference = MapHelpers.FindLayer(map, referenceName);
            var container = reference.Parent as ILayerContainerEdit ?? map;
            var index = container.Layers.IndexOf(reference);
            if (index < 0)
                throw new InvalidOperationException(
                    $"'{reference.Name}' and '{layer.Name}' are not in the same container.");

            // BEFORE means above in the table of contents, which is the lower
            // index: the list is drawn top first.
            if (position == "AFTER") index++;
            map.MoveLayer(layer, index);

            return new Dictionary<string, object>
            {
                ["moved"] = layer.Name,
                ["position"] = position,
                ["reference_layer"] = reference.Name,
                ["index"] = index,
                ["map"] = map.Name,
            };
        }

        // --- appearance -------------------------------------------------------

        /// <summary>
        /// The names ArcGIS Pro shows in the Basemap gallery, which are not
        /// always what the enum calls them: the gallery's "Imagery" is
        /// Basemap.Satellite.
        /// </summary>
        private static readonly Dictionary<string, Basemap> Basemaps =
            new Dictionary<string, Basemap>(StringComparer.OrdinalIgnoreCase)
            {
                ["topographic"] = Basemap.Topographic,
                ["imagery"] = Basemap.Satellite,
                ["imagery hybrid"] = Basemap.Hybrid,
                ["streets"] = Basemap.Streets,
                ["navigation"] = Basemap.NavigationVector,
                ["light gray canvas"] = Basemap.Gray,
                ["dark gray canvas"] = Basemap.DarkGray,
                ["terrain"] = Basemap.Terrain,
                ["oceans"] = Basemap.Oceans,
                ["openstreetmap"] = Basemap.OpenStreetMap,
                ["national geographic style"] = Basemap.NationalGeographic,
                ["none"] = Basemap.None,
            };

        private static object SetBasemap(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var name = parameters.Require("basemap_name");

            if (!Basemaps.TryGetValue(name.Trim(), out var basemap)
                && !Enum.TryParse(name.Replace(" ", ""), true, out basemap))
                throw new ArgumentException(
                    $"Unknown basemap '{name}'. Try one of: "
                    + string.Join(", ", Basemaps.Keys));

            map.SetBasemapLayers(basemap);

            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["basemap"] = basemap.ToString(),
            };
        }

        private static object SetScaleRange(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.FindLayer(map, parameters.Require("layer_name"));
            var applied = new Dictionary<string, object>();

            // 0 means "no limit" in the Pro UI, and SetMinScale(0) says the same
            // thing to the API, so the value goes straight through.
            if (parameters.Has("min_scale"))
            {
                layer.SetMinScale(parameters.GetDouble("min_scale"));
                applied["min_scale"] = layer.MinScale;
            }
            if (parameters.Has("max_scale"))
            {
                layer.SetMaxScale(parameters.GetDouble("max_scale"));
                applied["max_scale"] = layer.MaxScale;
            }

            if (applied.Count == 0)
                throw new ArgumentException("Provide min_scale and/or max_scale.");

            applied["layer"] = layer.Name;
            return applied;
        }

        // --- repairing --------------------------------------------------------

        private static object RepairSource(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var name = parameters.Require("layer_name");
            var dataset = parameters.GetString("dataset_name");

            var layer = map.GetLayersAsFlattenedList()
                .FirstOrDefault(l => string.Equals(l.Name, name,
                                                   StringComparison.OrdinalIgnoreCase));
            var table = layer != null ? null : map.GetStandaloneTablesAsFlattenedList()
                .FirstOrDefault(t => string.Equals(t.Name, name,
                                                   StringComparison.OrdinalIgnoreCase));
            if (layer == null && table == null)
                throw new ArgumentException($"No layer or table called '{name}'.");

            var wasBroken = layer != null
                ? layer.ConnectionStatus != ConnectionStatus.Connected
                : table.ConnectionStatus != ConnectionStatus.Connected;

            var workspace = SplitSource(parameters.Require("new_source"), ref dataset);
            var datasetName = string.IsNullOrWhiteSpace(dataset) ? name : dataset;

            using (var datastore = OpenDatastore(workspace))
            {
                if (layer is FeatureLayer featureLayer)
                {
                    using var featureClass = OpenDataset<FeatureClass>(datastore, datasetName);
                    featureLayer.ReplaceDataSource(featureClass);
                }
                else if (table != null)
                {
                    using var replacement = OpenDataset<Table>(datastore, datasetName);
                    table.ReplaceDataSource(replacement);
                }
                else
                {
                    throw new InvalidOperationException(
                        $"'{name}' is a {layer.GetType().Name}, which this command cannot "
                        + "repoint. Use execute_arcpy_code for that layer type.");
                }
            }

            return new Dictionary<string, object>
            {
                ["repaired"] = name,
                ["was_broken"] = wasBroken,
                ["connected"] = layer != null
                    ? layer.ConnectionStatus == ConnectionStatus.Connected
                    : table.ConnectionStatus == ConnectionStatus.Connected,
                ["workspace"] = workspace,
                ["dataset"] = datasetName,
                ["map"] = map.Name,
            };
        }

        /// <summary>
        /// new_source may be a workspace or a full dataset path. Split the
        /// latter, so callers can pass whichever they have to hand.
        /// </summary>
        private static string SplitSource(string source, ref string dataset)
        {
            var normalised = source.Replace('/', '\\').TrimEnd('\\');
            if (Directory.Exists(normalised)) return normalised;

            var parent = Path.GetDirectoryName(normalised);
            if (!string.IsNullOrEmpty(parent) && Directory.Exists(parent))
            {
                if (string.IsNullOrWhiteSpace(dataset))
                {
                    dataset = normalised.EndsWith(".shp", StringComparison.OrdinalIgnoreCase)
                        ? Path.GetFileNameWithoutExtension(normalised)
                        : Path.GetFileName(normalised);
                }
                return parent;
            }

            throw new ArgumentException(
                $"'{source}' is not a folder, geodatabase or dataset path.");
        }

        private static Datastore OpenDatastore(string workspace)
        {
            if (workspace.EndsWith(".gdb", StringComparison.OrdinalIgnoreCase))
                return new Geodatabase(new FileGeodatabaseConnectionPath(new Uri(workspace)));
            if (workspace.EndsWith(".sde", StringComparison.OrdinalIgnoreCase))
                return new Geodatabase(new DatabaseConnectionFile(new Uri(workspace)));
            return new FileSystemDatastore(new FileSystemConnectionPath(
                new Uri(workspace), FileSystemDatastoreType.Shapefile));
        }

        private static T OpenDataset<T>(Datastore datastore, string name) where T : Dataset
        {
            return datastore is Geodatabase geodatabase
                ? geodatabase.OpenDataset<T>(name)
                : ((FileSystemDatastore)datastore).OpenDataset<T>(name);
        }
    }
}
