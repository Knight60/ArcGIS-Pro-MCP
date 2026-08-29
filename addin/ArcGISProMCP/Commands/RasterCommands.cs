using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using ArcGIS.Core.CIM;
using ArcGIS.Core.Data;
using ArcGIS.Core.Data.Raster;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>Reading, symbolising and calculating with rasters.</summary>
    internal static class RasterCommands
    {
        private const string Group = "raster";

        public static void Register()
        {
            CommandRouter.RegisterAsync("get_raster_info", Group,
                "Raster detail: bands, size, cell size, pixel type, statistics and CRS.",
                GetRasterInfoAsync);

            CommandRouter.Register("set_raster_symbology", Group,
                "Set a raster layer's colorizer and colour ramp.", SetSymbology);

            CommandRouter.RegisterAsync("raster_calculator", Group,
                "Map algebra over named rasters. Needs Spatial Analyst.",
                RasterCalculatorAsync);
        }

        // --- info -------------------------------------------------------------

        /// <summary>
        /// Structure comes from the .NET raster API. Statistics do not: it
        /// exposes no equivalent of arcpy's raster.minimum, so those come from
        /// GetRasterProperties, which is also why this command is async.
        /// </summary>
        private static async Task<object> GetRasterInfoAsync(Params parameters)
        {
            var name = parameters.Require("layer_name");

            var info = await QueuedTask.Run(() =>
            {
                var (raster, source, disposable) = OpenRaster(parameters, name);
                try
                {
                    var bandCount = raster.GetBandCount();
                    var result = new Dictionary<string, object>
                    {
                        ["layer"] = name,
                        ["source"] = source,
                        ["band_count"] = bandCount,
                        ["width"] = raster.GetWidth(),
                        ["height"] = raster.GetHeight(),
                        ["pixel_type"] = raster.GetPixelType().ToString(),
                        ["nodata_value"] = raster.GetNoDataValue(),
                    };

                    var cell = raster.GetMeanCellSize();
                    result["cell_size_x"] = cell.Item1;
                    result["cell_size_y"] = cell.Item2;

                    var extent = raster.GetExtent();
                    if (extent != null) result["extent"] = MapHelpers.Describe(extent);

                    var reference = raster.GetSpatialReference();
                    if (reference != null)
                        result["spatial_reference"] = MapHelpers.Describe(reference);

                    var bands = new List<string>();
                    for (var i = 0; i < bandCount; i++)
                    {
                        using var band = raster.GetBand(i);
                        bands.Add(band.GetName());
                    }
                    result["band_names"] = bands;
                    return result;
                }
                finally
                {
                    disposable?.Dispose();
                }
            }).ConfigureAwait(false);

            var statistics = await ReadStatisticsAsync(
                (string)info["source"] ?? name).ConfigureAwait(false);
            foreach (var pair in statistics) info[pair.Key] = pair.Value;
            return info;
        }

        /// <summary>
        /// Band 1's statistics, or a note saying why there are none. A raster
        /// whose statistics have never been built reports the failure rather
        /// than a plausible zero.
        /// </summary>
        private static async Task<Dictionary<string, object>> ReadStatisticsAsync(string source)
        {
            var wanted = new Dictionary<string, string>
            {
                ["minimum"] = "MINIMUM",
                ["maximum"] = "MAXIMUM",
                ["mean"] = "MEAN",
                ["standard_deviation"] = "STD",
            };

            var statistics = new Dictionary<string, object>();
            foreach (var pair in wanted)
            {
                try
                {
                    var result = await GeoprocessingCommands.RunNamedAsync(
                        "management.GetRasterProperties",
                        new Dictionary<string, object>
                        {
                            ["in_raster"] = source,
                            ["property_type"] = pair.Value,
                            ["band_index"] = "Band_1",
                        },
                        addToMap: false).ConfigureAwait(false);

                    if (result.IsFailed) continue;
                    if (double.TryParse(result.ReturnValue, out var value))
                        statistics[pair.Key] = value;
                }
                catch (Exception)
                {
                    // One missing property should not cost the caller the rest
                    // of the report.
                }
            }

            if (statistics.Count == 0)
                statistics["statistics"] =
                    "not available -- run the Calculate Statistics tool on this raster";
            return statistics;
        }

        /// <summary>
        /// Rasters arrive either as a layer in the map or as a path, the same
        /// as everywhere else. The third value is what to dispose, which is
        /// nothing when the raster came from a layer.
        /// </summary>
        private static (Raster, string, IDisposable) OpenRaster(Params parameters, string name)
        {
            Map map = null;
            try { map = MapHelpers.ResolveMap(parameters); } catch (Exception) { }

            var layer = map?.GetLayersAsFlattenedList().OfType<BasicRasterLayer>()
                .FirstOrDefault(l => string.Equals(l.Name, name,
                                                   StringComparison.OrdinalIgnoreCase));
            if (layer != null)
            {
                var raster = layer.GetRaster();
                return (raster, layer.GetPath()?.LocalPath ?? name, raster);
            }

            var normalised = name.Replace('/', '\\');
            var folder = Path.GetDirectoryName(normalised);
            if (string.IsNullOrEmpty(folder) || !Directory.Exists(folder))
                throw new ArgumentException(
                    $"No raster layer called '{name}', and it is not a raster path either.");

            var datastore = folder.EndsWith(".gdb", StringComparison.OrdinalIgnoreCase)
                ? (Datastore)new Geodatabase(new FileGeodatabaseConnectionPath(new Uri(folder)))
                : new FileSystemDatastore(new FileSystemConnectionPath(
                    new Uri(folder), FileSystemDatastoreType.Raster));

            var dataset = Path.GetFileName(normalised);
            var rasterDataset = datastore is Geodatabase geodatabase
                ? geodatabase.OpenDataset<RasterDataset>(dataset)
                : ((FileSystemDatastore)datastore).OpenDataset<RasterDataset>(dataset);

            return (rasterDataset.CreateFullRaster(), normalised, datastore);
        }

        // --- symbology --------------------------------------------------------

        private static object SetSymbology(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var name = parameters.Require("layer_name");

            var layer = map.GetLayersAsFlattenedList().OfType<BasicRasterLayer>()
                .FirstOrDefault(l => string.Equals(l.Name, name,
                                                   StringComparison.OrdinalIgnoreCase))
                ?? throw new ArgumentException($"No raster layer called '{name}'.");

            var kind = (parameters.GetString("colorizer", "stretch") ?? "stretch")
                .ToLowerInvariant().Replace("_", "");
            var ramp = SymbologyCommands.FindColorRamp(parameters.GetString("color_ramp"));
            var applied = new Dictionary<string, object> { ["layer"] = layer.Name };

            if (parameters.Has("colorizer") || parameters.Has("color_ramp")
                || parameters.Has("stretch_type") || parameters.Has("break_count"))
            {
                RasterColorizerDefinition definition;
                switch (kind)
                {
                    case "classify":
                        definition = new ClassifyColorizerDefinition(
                            null,
                            parameters.GetInt("break_count", 5),
                            SymbologyCommands.ParseClassification(
                                parameters.GetString("classification_method")),
                            ramp);
                        break;
                    case "uniquevalues":
                        definition = new UniqueValueColorizerDefinition(null, ramp);
                        break;
                    case "rgb":
                        definition = new RGBColorizerDefinition(
                            0, 1, 2, ParseStretch(parameters.GetString("stretch_type")),
                            2.0, 2.0, 2.0);
                        break;
                    default:
                        definition = new StretchColorizerDefinition(
                            0, ParseStretch(parameters.GetString("stretch_type")), 1.0, ramp);
                        break;
                }

                if (!layer.CanCreateColorizer(definition))
                    throw new InvalidOperationException(
                        $"A {kind} colorizer does not suit '{layer.Name}'. An RGB "
                        + "colorizer needs three bands; unique values needs an "
                        + "integer raster with an attribute table.");

                layer.SetColorizer(layer.CreateColorizer(definition));
                applied["colorizer"] = kind;
                if (ramp != null) applied["color_ramp"] = parameters.GetString("color_ramp");
            }

            if (parameters.Has("transparency"))
            {
                layer.SetTransparency(parameters.GetDouble("transparency"));
                applied["transparency"] = layer.Transparency;
            }

            if (applied.Count == 1)
                throw new ArgumentException(
                    "Provide colorizer, color_ramp, stretch_type, break_count "
                    + "and/or transparency.");
            return applied;
        }

        private static RasterStretchType ParseStretch(string name)
        {
            switch ((name ?? "MinimumMaximum").Replace(" ", "").ToUpperInvariant())
            {
                case "STANDARDDEVIATION":
                case "STANDARDDEVIATIONS": return RasterStretchType.StandardDeviations;
                case "PERCENTCLIP":
                case "PERCENTMINIMUMMAXIMUM": return RasterStretchType.PercentMinimumMaximum;
                case "HISTOGRAMEQUALIZE": return RasterStretchType.HistogramEqualize;
                case "NONE": return RasterStretchType.None;
                case "ESRI": return RasterStretchType.ESRI;
                default: return RasterStretchType.MinimumMaximum;
            }
        }

        // --- map algebra ------------------------------------------------------

        /// <summary>
        /// The tool takes one expression string, so the aliases are substituted
        /// into it first. Longest alias wins, so "dem" inside "dem_fill" is not
        /// replaced out from under the caller.
        /// </summary>
        private static async Task<object> RasterCalculatorAsync(Params parameters)
        {
            var rasters = parameters.GetObject("rasters")
                ?? throw new ArgumentException(
                    "rasters must map each alias to a layer name or raster path.");
            var expression = parameters.Require("expression");
            var output = parameters.Require("output_path");

            var resolved = expression;
            foreach (var alias in rasters.Keys.OrderByDescending(k => k.Length))
            {
                var source = rasters[alias].ToString();
                resolved = Regex.Replace(resolved, $@"\b{Regex.Escape(alias)}\b",
                                         "\"" + source + "\"");
            }

            var started = DateTime.Now;
            var result = await GeoprocessingCommands.RunNamedAsync(
                "sa.RasterCalculator",
                new Dictionary<string, object>
                {
                    ["expression"] = resolved,
                    ["output_raster"] = output,
                },
                parameters.GetBool("add_to_map", true)).ConfigureAwait(false);

            if (result.IsFailed)
            {
                var messages = result.ErrorMessages != null && result.ErrorMessages.Any()
                    ? string.Join("; ", result.ErrorMessages.Select(m => m.Text))
                    : "the tool reported no error text";
                throw new InvalidOperationException(
                    $"raster_calculator failed: {messages}. The expression sent was: "
                    + resolved);
            }

            return new Dictionary<string, object>
            {
                ["output"] = output,
                ["expression"] = resolved,
                ["elapsed_seconds"] = Math.Round((DateTime.Now - started).TotalSeconds, 2),
                ["messages"] = result.Messages?.Select(m => m.Text).Take(20).ToList(),
            };
        }
    }
}
