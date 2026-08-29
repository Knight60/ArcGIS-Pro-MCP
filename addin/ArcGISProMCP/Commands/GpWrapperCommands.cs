using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using ArcGIS.Desktop.Core;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>
    /// Commands that are one geoprocessing tool under a friendlier name.
    ///
    /// Each one says which tool parameter each value belongs to; the ordering
    /// comes from the embedded parameter table. Hand-built positional arrays
    /// were tried first and quietly put select_by_location's invert flag in
    /// the output-layer slot, which is exactly the mistake this avoids.
    /// </summary>
    internal static class GpWrapperCommands
    {
        public static void Register()
        {
            Wrap("add_field", "schema", "Add a field to a layer or table.",
                "management.AddField", p => new Dictionary<string, object>
                {
                    ["in_table"] = Target(p),
                    ["field_name"] = p.Require("field_name"),
                    ["field_type"] = p.GetString("field_type", "TEXT"),
                    ["field_precision"] = p.GetString("field_precision"),
                    ["field_scale"] = p.GetString("field_scale"),
                    ["field_length"] = p.GetString("field_length"),
                    ["field_alias"] = p.GetString("field_alias"),
                    ["field_is_nullable"] = p.GetString("nullable", "NULLABLE"),
                    ["field_domain"] = p.GetString("field_domain"),
                });

            Wrap("delete_field", "schema", "Delete one or more fields.",
                "management.DeleteField", p => new Dictionary<string, object>
                {
                    ["in_table"] = Target(p),
                    ["drop_field"] = string.Join(";", p.GetStringList("field_names")
                        ?? new List<string> { p.Require("field_name") }),
                });

            Wrap("alter_field", "schema", "Rename a field or change its alias or length.",
                "management.AlterField", p => new Dictionary<string, object>
                {
                    ["in_table"] = Target(p),
                    ["field"] = p.Require("field_name"),
                    ["new_field_name"] = p.GetString("new_name"),
                    ["new_field_alias"] = p.GetString("new_alias"),
                    ["field_length"] = p.GetString("field_length"),
                });

            Wrap("calculate_field", "data", "Calculate field values across a layer.",
                "management.CalculateField", p => new Dictionary<string, object>
                {
                    ["in_table"] = Target(p),
                    ["field"] = p.Require("field_name"),
                    ["expression"] = p.Require("expression"),
                    ["expression_type"] = p.GetString("expression_type", "PYTHON3"),
                    ["code_block"] = p.GetString("code_block"),
                });

            Wrap("create_feature_class", "schema",
                "Create an empty feature class in a geodatabase or folder.",
                "management.CreateFeatureclass", p => new Dictionary<string, object>
                {
                    ["out_path"] = p.GetString("out_path")
                                   ?? Project.Current?.DefaultGeodatabasePath,
                    ["out_name"] = p.Require("name"),
                    ["geometry_type"] = p.GetString("geometry_type", "POLYGON"),
                    ["template"] = p.GetString("template"),
                    ["has_m"] = p.GetString("has_m", "DISABLED"),
                    ["has_z"] = p.GetString("has_z", "DISABLED"),
                    ["spatial_reference"] = p.Has("epsg") ? p.GetInt("epsg").ToString() : null,
                }, addToMapByDefault: true);

            Wrap("create_table", "schema", "Create an empty standalone table.",
                "management.CreateTable", p => new Dictionary<string, object>
                {
                    ["out_path"] = p.GetString("out_path")
                                   ?? Project.Current?.DefaultGeodatabasePath,
                    ["out_name"] = p.Require("name"),
                    ["template"] = p.GetString("template"),
                }, addToMapByDefault: true);

            Wrap("create_file_geodatabase", "schema", "Create a file geodatabase.",
                "management.CreateFileGDB", p => new Dictionary<string, object>
                {
                    ["out_folder_path"] = p.GetString("folder")
                                          ?? Project.Current?.HomeFolderPath,
                    ["out_name"] = p.Require("name"),
                });

            Wrap("delete_dataset", "schema",
                "Delete a dataset from disk or a geodatabase. This cannot be undone.",
                "management.Delete", p => new Dictionary<string, object>
                {
                    ["in_data"] = p.Require("path"),
                });

            Wrap("truncate_table", "schema", "Delete every row, keeping the schema.",
                "management.TruncateTable", p => new Dictionary<string, object>
                {
                    ["in_table"] = Target(p),
                });

            Wrap("export_features", "schema",
                "Export a layer, honouring its selection and definition query.",
                "conversion.ExportFeatures", p => new Dictionary<string, object>
                {
                    ["in_features"] = Target(p),
                    ["out_features"] = p.Require("out_path"),
                    ["where_clause"] = p.GetString("where"),
                }, addToMapByDefault: true);

            Wrap("select_by_location", "selection",
                "Select features by spatial relationship to another layer.",
                "management.SelectLayerByLocation", p => new Dictionary<string, object>
                {
                    ["in_layer"] = Target(p),
                    ["overlap_type"] = p.GetString("relationship", "INTERSECT"),
                    ["select_features"] = p.Require("select_features"),
                    ["search_distance"] = p.GetString("search_distance"),
                    ["selection_type"] = p.GetString("method", "NEW_SELECTION"),
                    ["invert_spatial_relationship"] = p.GetString("invert", "NOT_INVERT"),
                });

            Wrap("add_join", "layers", "Join a table to a layer on a common field.",
                "management.AddJoin", p => new Dictionary<string, object>
                {
                    ["in_layer_or_view"] = Target(p),
                    ["in_field"] = p.Require("layer_field"),
                    ["join_table"] = p.Require("join_table"),
                    ["join_field"] = p.Require("join_field"),
                    ["join_type"] = p.GetString("keep_all", "KEEP_ALL"),
                });

            Wrap("remove_join", "layers", "Remove a join from a layer.",
                "management.RemoveJoin", p => new Dictionary<string, object>
                {
                    ["in_layer_or_view"] = Target(p),
                    ["join_name"] = p.GetString("join_name"),
                });

            Wrap("zonal_statistics", "raster",
                "Summarise raster values inside zone polygons.",
                "sa.ZonalStatisticsAsTable", p => new Dictionary<string, object>
                {
                    ["in_zone_data"] = p.Require("zone_layer"),
                    ["zone_field"] = p.Require("zone_field"),
                    ["in_value_raster"] = p.Require("raster_layer"),
                    ["out_table"] = p.GetString("output_table")
                        ?? Path.Combine(Project.Current?.DefaultGeodatabasePath ?? "",
                                        "zonal_stats"),
                    ["ignore_nodata"] = p.GetString("ignore_nodata", "DATA"),
                    ["statistics_type"] = p.GetString("statistics_type", "ALL"),
                });

            Wrap("sample_raster_values", "raster",
                "Read raster values at a point layer's features.",
                "sa.Sample", p => new Dictionary<string, object>
                {
                    ["in_rasters"] = Target(p),
                    ["in_location_data"] = p.Require("point_layer"),
                    ["out_table"] = p.GetString("output_table")
                        ?? Path.Combine(Project.Current?.DefaultGeodatabasePath ?? "",
                                        "raster_samples"),
                });

            Wrap("apply_symbology_from_layer", "symbology",
                "Copy symbology from a .lyrx file or another layer.",
                "management.ApplySymbologyFromLayer", p => new Dictionary<string, object>
                {
                    ["in_layer"] = Target(p),
                    ["in_symbology_layer"] = p.Require("symbology_source"),
                    ["update_symbology"] = p.GetString("update_symbology", "DEFAULT"),
                });

            Wrap("save_layer_file", "symbology",
                "Save a layer with its symbology to a .lyrx file.",
                "management.SaveToLayerFile", p => new Dictionary<string, object>
                {
                    ["in_layer"] = Target(p),
                    ["out_layer"] = p.Require("output_path"),
                    ["is_relative_path"] = p.GetString("relative_paths", "ABSOLUTE"),
                });

            RegisterAddFields();
        }

        /// <summary>
        /// AddFields takes one value table, where every field is a row of
        /// space-separated values -- and a column out of place there would put
        /// a length where an alias belongs, silently. So this calls AddField
        /// once per field, by name. Slower for a long list, and worth it.
        /// </summary>
        private static void RegisterAddFields()
        {
            CommandRouter.RegisterAsync("add_fields", "schema",
                "Add several fields in one call.", async parameters =>
                {
                    var target = Target(parameters);
                    var added = new List<string>();

                    foreach (var field in parameters.GetObjectList("fields"))
                    {
                        var name = field.Require("name");
                        var result = await GeoprocessingCommands.RunNamedAsync(
                            "management.AddField",
                            new Dictionary<string, object>
                            {
                                ["in_table"] = target,
                                ["field_name"] = name,
                                ["field_type"] = field.GetString("type", "TEXT"),
                                ["field_precision"] = field.GetString("precision"),
                                ["field_scale"] = field.GetString("scale"),
                                ["field_length"] = field.GetString("length"),
                                ["field_alias"] = field.GetString("alias"),
                                ["field_is_nullable"] = field.GetString("nullable", "NULLABLE"),
                                ["field_domain"] = field.GetString("domain"),
                            },
                            addToMap: false).ConfigureAwait(false);

                        if (result.IsFailed)
                        {
                            var messages = result.ErrorMessages != null
                                           && result.ErrorMessages.Any()
                                ? string.Join("; ", result.ErrorMessages.Select(m => m.Text))
                                : "the tool reported no error text";
                            // Half the fields may already exist by now, so say
                            // which -- a blind retry would fail on those.
                            throw new InvalidOperationException(
                                $"add_fields stopped at '{name}': {messages}. Fields "
                                + "added before it: "
                                + (added.Count == 0 ? "(none)" : string.Join(", ", added)));
                        }
                        added.Add(name);
                    }

                    if (added.Count == 0)
                        throw new ArgumentException(
                            "fields must be a list, e.g. "
                            + "[{\"name\": \"AREA_HA\", \"type\": \"DOUBLE\"}]");

                    return new Dictionary<string, object>
                    {
                        ["table"] = target,
                        ["added"] = added,
                        ["count"] = added.Count,
                    };
                });
        }

        /// <summary>The layer name or dataset path a command acts on.</summary>
        private static string Target(Params parameters) => parameters.Require("layer_name");

        private static void Wrap(string command, string group, string summary,
                                 string toolName,
                                 Func<Params, Dictionary<string, object>> buildValues,
                                 bool addToMapByDefault = false)
        {
            CommandRouter.RegisterAsync(command, group, summary, async parameters =>
            {
                var named = buildValues(parameters);
                var addToMap = parameters.Has("add_to_map")
                    ? parameters.GetBool("add_to_map")
                    : addToMapByDefault;

                var started = DateTime.Now;
                var result = await GeoprocessingCommands
                    .RunNamedAsync(toolName, named, addToMap).ConfigureAwait(false);

                if (result.IsFailed)
                {
                    var messages = result.ErrorMessages != null && result.ErrorMessages.Any()
                        ? string.Join("; ", result.ErrorMessages.Select(m => m.Text))
                        : "the tool reported no error text";
                    throw new InvalidOperationException($"{command} failed: {messages}");
                }

                return new Dictionary<string, object>
                {
                    ["command"] = command,
                    ["tool"] = toolName,
                    ["outputs"] = result.Values?.ToList(),
                    ["elapsed_seconds"] = Math.Round((DateTime.Now - started).TotalSeconds, 2),
                    ["messages"] = result.Messages?.Select(m => m.Text).Take(20).ToList(),
                };
            });
        }
    }
}
