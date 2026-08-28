using System;
using System.Collections.Generic;
using System.Linq;
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

            if (matches.Count == 0)
                throw new ArgumentException($"Layer not found in map '{map.Name}': {name}");

            foreach (var layer in matches) map.RemoveLayer(layer);

            return new Dictionary<string, object>
            {
                ["removed"] = name,
                ["count"] = matches.Count,
                ["map"] = map.Name,
            };
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
    }
}
