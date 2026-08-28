using System;
using System.Collections.Generic;
using System.Linq;
using ArcGIS.Core.Data;
using ArcGIS.Core.Geometry;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Editing;
using ArcGIS.Desktop.Mapping;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>
    /// Changing data: rows and schema.
    ///
    /// Row edits go through EditOperation rather than a cursor, so they land
    /// in ArcGIS Pro's own edit session and can be undone from the ribbon like
    /// anything the user did by hand.
    /// </summary>
    internal static class EditCommands
    {
        private const string Group = "data";

        public static void Register()
        {
            CommandRouter.Register("insert_features", Group,
                "Insert rows into a layer or table.", InsertFeatures);
            CommandRouter.Register("update_features", Group,
                "Update rows matching a where clause.", UpdateFeatures);
            CommandRouter.Register("delete_features", Group,
                "Delete rows matching a where clause.", DeleteFeatures);
            CommandRouter.Register("list_fields", "schema",
                "List a layer's fields with type, alias and length.", ListFields);
            CommandRouter.Register("save_edits", Group,
                "Commit pending edits. ArcGIS Pro holds edits open so they can be "
                + "undone, which also keeps the data locked until they are saved.",
                SaveEdits);
            CommandRouter.Register("discard_edits", Group,
                "Throw away pending edits.", DiscardEdits);
        }

        private static BasicFeatureLayer Layer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            return MapHelpers.RequireFeatureLayer(map, parameters.Require("layer_name"));
        }

        private static Geometry GeometryFrom(Params feature, SpatialReference reference)
        {
            var raw = feature.Raw("geometry");
            if (raw.ValueKind == System.Text.Json.JsonValueKind.Undefined
                || raw.ValueKind == System.Text.Json.JsonValueKind.Null) return null;

            if (raw.ValueKind == System.Text.Json.JsonValueKind.String)
                return GeometryEngine.Instance.ImportFromWKT(0, raw.GetString(), reference);

            if (raw.ValueKind == System.Text.Json.JsonValueKind.Array)
            {
                var numbers = raw.EnumerateArray()
                    .Where(v => v.ValueKind == System.Text.Json.JsonValueKind.Number)
                    .Select(v => v.GetDouble()).ToArray();
                if (numbers.Length >= 2)
                    return MapPointBuilderEx.CreateMapPoint(numbers[0], numbers[1], reference);
            }
            throw new ArgumentException(
                "geometry must be WKT text or an [x, y] pair.");
        }

        private static Dictionary<string, object> AttributesFrom(Params feature)
        {
            var attributes = new Dictionary<string, object>();
            var raw = feature.Raw("attributes");
            if (raw.ValueKind != System.Text.Json.JsonValueKind.Object) return attributes;

            foreach (var property in raw.EnumerateObject())
            {
                switch (property.Value.ValueKind)
                {
                    case System.Text.Json.JsonValueKind.String:
                        attributes[property.Name] = property.Value.GetString(); break;
                    case System.Text.Json.JsonValueKind.Number:
                        attributes[property.Name] = property.Value.GetDouble(); break;
                    case System.Text.Json.JsonValueKind.True:
                        attributes[property.Name] = true; break;
                    case System.Text.Json.JsonValueKind.False:
                        attributes[property.Name] = false; break;
                    case System.Text.Json.JsonValueKind.Null:
                        attributes[property.Name] = null; break;
                    default:
                        attributes[property.Name] = property.Value.GetRawText(); break;
                }
            }
            return attributes;
        }

        private static object InsertFeatures(Params parameters)
        {
            var layer = Layer(parameters);
            var features = parameters.GetObjectList("features").ToList();
            if (features.Count == 0)
                throw new ArgumentException(
                    "features is required: a list of {attributes, geometry}.");

            var reference = layer.GetSpatialReference();
            var operation = new EditOperation { Name = $"MCP insert into {layer.Name}" };

            foreach (var feature in features)
            {
                var attributes = AttributesFrom(feature);
                var geometry = GeometryFrom(feature, reference);
                if (geometry != null) attributes["SHAPE"] = geometry;
                if (attributes.Count == 0)
                    throw new ArgumentException("Each feature needs attributes or geometry.");
                operation.Create(layer, attributes);
            }

            if (!operation.Execute())
                throw new InvalidOperationException(
                    $"The insert failed: {operation.ErrorMessage}");

            MaybeSave(parameters);
            return new Dictionary<string, object>
            {
                ["layer"] = layer.Name,
                ["inserted"] = features.Count,
                ["edits_saved"] = parameters.GetBool("save_edits"),
            };
        }

        /// <summary>ObjectIDs matching a where clause, so edits can be targeted.</summary>
        private static List<long> ObjectIds(BasicFeatureLayer layer, string where, int limit)
        {
            var filter = new QueryFilter();
            if (!string.IsNullOrWhiteSpace(where)) filter.WhereClause = where;

            var oids = new List<long>();
            using (var table = layer.GetTable())
            {
                filter.SubFields = table.GetDefinition().GetObjectIDField();
                using (var cursor = layer.Search(filter))
                {
                    while (cursor.MoveNext())
                    {
                        using (var row = cursor.Current) oids.Add(row.GetObjectID());
                        if (limit > 0 && oids.Count >= limit) break;
                    }
                }
            }
            return oids;
        }

        private static object UpdateFeatures(Params parameters)
        {
            var layer = Layer(parameters);
            var where = parameters.GetString("where");
            var attributes = AttributesFrom(new Params(parameters.Root));

            var updates = parameters.GetObject("attributes");
            if ((updates == null || updates.Count == 0) && !parameters.Has("geometry"))
                throw new ArgumentException("Provide attributes and/or geometry to update.");
            if (string.IsNullOrWhiteSpace(where) && !parameters.GetBool("allow_update_all"))
                throw new ArgumentException(
                    "Refusing to update every row: pass a where clause, or set "
                    + "allow_update_all=true to confirm.");

            var values = new Dictionary<string, object>();
            if (updates != null)
            {
                foreach (var pair in updates)
                {
                    values[pair.Key] = pair.Value.ValueKind switch
                    {
                        System.Text.Json.JsonValueKind.String => pair.Value.GetString(),
                        System.Text.Json.JsonValueKind.Number => (object)pair.Value.GetDouble(),
                        System.Text.Json.JsonValueKind.True => true,
                        System.Text.Json.JsonValueKind.False => false,
                        System.Text.Json.JsonValueKind.Null => null,
                        _ => pair.Value.GetRawText(),
                    };
                }
            }
            if (parameters.Has("geometry"))
                values["SHAPE"] = GeometryFrom(parameters, layer.GetSpatialReference());

            var oids = ObjectIds(layer, where, parameters.GetInt("limit"));
            if (oids.Count == 0)
                return new Dictionary<string, object>
                {
                    ["layer"] = layer.Name, ["updated"] = 0, ["where"] = where,
                };

            var operation = new EditOperation { Name = $"MCP update {layer.Name}" };
            foreach (var oid in oids) operation.Modify(layer, oid, values);
            if (!operation.Execute())
                throw new InvalidOperationException(
                    $"The update failed: {operation.ErrorMessage}");

            MaybeSave(parameters);
            return new Dictionary<string, object>
            {
                ["layer"] = layer.Name,
                ["updated"] = oids.Count,
                ["where"] = where,
                ["edits_saved"] = parameters.GetBool("save_edits"),
            };
        }

        private static object DeleteFeatures(Params parameters)
        {
            var layer = Layer(parameters);
            var where = parameters.GetString("where");
            if (string.IsNullOrWhiteSpace(where) && !parameters.GetBool("allow_delete_all"))
                throw new ArgumentException(
                    "Refusing to delete every row: pass a where clause, or set "
                    + "allow_delete_all=true to confirm.");

            var oids = ObjectIds(layer, where, 0);
            if (oids.Count == 0)
                return new Dictionary<string, object>
                {
                    ["layer"] = layer.Name, ["deleted"] = 0, ["where"] = where,
                };

            var operation = new EditOperation { Name = $"MCP delete from {layer.Name}" };
            operation.Delete(layer, oids);
            if (!operation.Execute())
                throw new InvalidOperationException(
                    $"The delete failed: {operation.ErrorMessage}");

            MaybeSave(parameters);
            return new Dictionary<string, object>
            {
                ["layer"] = layer.Name,
                ["deleted"] = oids.Count,
                ["where"] = where,
                ["edits_saved"] = parameters.GetBool("save_edits"),
            };
        }

        /// <summary>
        /// Pro keeps edits pending so the user can undo them, but a dataset
        /// with pending edits is locked -- deleting or overwriting it fails
        /// until they are saved or discarded.
        /// </summary>
        private static object SaveEdits(Params parameters)
        {
            var project = MapHelpers.RequireProject();
            var had = project.HasEdits;
            if (had) project.SaveEditsAsync().Wait();
            return new Dictionary<string, object>
            {
                ["saved"] = had,
                ["message"] = had ? "Pending edits committed."
                                  : "There were no pending edits.",
            };
        }

        private static object DiscardEdits(Params parameters)
        {
            var project = MapHelpers.RequireProject();
            var had = project.HasEdits;
            if (had) project.DiscardEditsAsync().Wait();
            return new Dictionary<string, object>
            {
                ["discarded"] = had,
                ["message"] = had ? "Pending edits discarded."
                                  : "There were no pending edits.",
            };
        }

        /// <summary>Commit straight away when the caller asked for it.</summary>
        private static void MaybeSave(Params parameters)
        {
            if (!parameters.GetBool("save_edits")) return;
            var project = Project.Current;
            if (project != null && project.HasEdits) project.SaveEditsAsync().Wait();
        }

        private static object ListFields(Params parameters)
        {
            using var source = DataSource.Resolve(parameters);
            var wildcard = parameters.GetString("wildcard")?.Trim('*');
            var fields = source.Definition.GetFields()
                .Where(field => string.IsNullOrEmpty(wildcard)
                                || field.Name.IndexOf(
                                    wildcard, StringComparison.OrdinalIgnoreCase) >= 0)
                .Select(MapHelpers.Describe).ToList();

            return new Dictionary<string, object>
            {
                ["layer"] = source.Name,
                ["fields"] = fields,
            };
        }
    }
}
