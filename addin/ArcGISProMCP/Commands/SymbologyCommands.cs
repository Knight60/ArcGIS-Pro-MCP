using System;
using System.Collections.Generic;
using System.Linq;
using ArcGIS.Core.CIM;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Mapping;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>Renderers, colour ramps and labels.</summary>
    internal static class SymbologyCommands
    {
        private const string Group = "symbology";

        public static void Register()
        {
            CommandRouter.Register("set_layer_renderer", Group,
                "Change a layer's symbology: single symbol, unique values, or "
                + "graduated colours.", SetRenderer);

            CommandRouter.Register("get_layer_symbology", Group,
                "Inspect a layer's renderer, class breaks and label settings.",
                GetSymbology);

            CommandRouter.Register("list_color_ramps", Group,
                "List the colour ramps available in the project.", ListColorRamps);

            CommandRouter.Register("set_layer_labeling", Group,
                "Turn labels on or off and set the expression and font.", SetLabeling);
        }

        // --- helpers ---------------------------------------------------------

        private static CIMColor ToColor(int[] rgba)
        {
            // Alpha arrives 0-100 to match the Python side; the CIM wants 0-255.
            return ColorFactory.Instance.CreateRGBColor(
                rgba[0], rgba[1], rgba[2], rgba.Length > 3 ? rgba[3] : 100);
        }

        private static CIMSymbolReference PolygonSymbol(int[] fill, int[] outline,
                                                        double? outlineWidth)
        {
            var stroke = SymbolFactory.Instance.ConstructStroke(
                outline != null ? ToColor(outline) : ColorFactory.Instance.GreyRGB,
                outlineWidth ?? 0.5, SimpleLineStyle.Solid);
            var symbol = SymbolFactory.Instance.ConstructPolygonSymbol(
                fill != null ? ToColor(fill) : ColorFactory.Instance.GreyRGB,
                SimpleFillStyle.Solid, stroke);
            return symbol.MakeSymbolReference();
        }

        private static CIMSymbolReference SymbolFor(BasicFeatureLayer layer,
                                                    int[] fill, int[] outline,
                                                    double? outlineWidth, double? size)
        {
            var color = fill != null ? ToColor(fill) : ColorFactory.Instance.GreyRGB;
            switch (layer.ShapeType)
            {
                case esriGeometryType.esriGeometryPoint:
                case esriGeometryType.esriGeometryMultipoint:
                    return SymbolFactory.Instance
                        .ConstructPointSymbol(color, size ?? 8, SimpleMarkerStyle.Circle)
                        .MakeSymbolReference();
                case esriGeometryType.esriGeometryPolyline:
                    return SymbolFactory.Instance
                        .ConstructLineSymbol(color, outlineWidth ?? size ?? 1)
                        .MakeSymbolReference();
                default:
                    return PolygonSymbol(fill, outline, outlineWidth);
            }
        }

        private static ClassificationMethod ParseClassification(string name)
        {
            switch ((name ?? "NaturalBreaks").ToUpperInvariant())
            {
                case "EQUALINTERVAL": return ClassificationMethod.EqualInterval;
                case "QUANTILE": return ClassificationMethod.Quantile;
                case "STANDARDDEVIATION": return ClassificationMethod.StandardDeviation;
                case "DEFINEDINTERVAL": return ClassificationMethod.DefinedInterval;
                default: return ClassificationMethod.NaturalBreaks;
            }
        }

        private static CIMColorRamp FindColorRamp(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return null;
            foreach (var style in Project.Current.GetItems<StyleProjectItem>())
            {
                var matches = style.SearchColorRamps(name);
                if (matches != null && matches.Count > 0) return matches[0].ColorRamp;
            }
            return null;
        }

        // --- commands --------------------------------------------------------

        private static object SetRenderer(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.RequireFeatureLayer(map, parameters.Require("layer_name"))
                        as FeatureLayer;
            if (layer == null)
                throw new ArgumentException("That layer does not take a feature renderer.");

            var kind = (parameters.GetString("renderer_type", "simple") ?? "simple")
                       .ToLowerInvariant();
            var warnings = new List<string>();
            var result = new Dictionary<string, object>
            {
                ["layer"] = layer.Name,
                ["renderer"] = kind,
            };

            if (kind == "simple")
            {
                var renderer = new CIMSimpleRenderer
                {
                    Symbol = SymbolFor(layer,
                                       parameters.GetColor("color"),
                                       parameters.GetColor("outline_color"),
                                       parameters.GetOptionalDouble("outline_width"),
                                       parameters.GetOptionalDouble("symbol_size")),
                    Label = parameters.GetString("label"),
                };
                layer.SetRenderer(renderer);
            }
            else if (kind == "unique_values")
            {
                var fields = parameters.GetStringList("fields")
                             ?? new List<string> { parameters.Require("field") };
                var definition = new UniqueValueRendererDefinition(fields)
                {
                    ColorRamp = FindColorRamp(parameters.GetString("color_ramp")),
                };
                var renderer = layer.CreateRenderer(definition);
                ApplyValueColors(renderer as CIMUniqueValueRenderer,
                                 parameters, warnings);
                layer.SetRenderer(renderer);
                result["value_count"] = (renderer as CIMUniqueValueRenderer)?.Groups?
                    .Sum(g => g.Classes?.Length ?? 0);
            }
            else if (kind == "graduated_colors" || kind == "graduated_symbols")
            {
                var field = parameters.Require("field");
                var ramp = FindColorRamp(parameters.GetString("color_ramp"));
                if (ramp == null && parameters.Has("color_ramp"))
                    warnings.Add($"Colour ramp '{parameters.GetString("color_ramp")}' "
                               + "was not found; the default was used.");

                var definition = new GraduatedColorsRendererDefinition
                {
                    ClassificationField = field,
                    ClassificationMethod = ParseClassification(
                        parameters.GetString("classification_method")),
                    BreakCount = parameters.GetInt("break_count", 5),
                    ColorRamp = ramp,
                };
                var renderer = layer.CreateRenderer(definition);
                ApplyClassColors(renderer as CIMClassBreaksRenderer, parameters, warnings);
                layer.SetRenderer(renderer);

                if (renderer is CIMClassBreaksRenderer breaks)
                {
                    result["class_breaks"] = breaks.Breaks?.Select(b =>
                        new Dictionary<string, object>
                        {
                            ["upper_bound"] = b.UpperBound,
                            ["label"] = b.Label,
                        }).ToList();
                }
            }
            else
            {
                throw new ArgumentException(
                    $"Unknown renderer_type '{kind}'. Use simple, unique_values, "
                    + "graduated_colors or graduated_symbols.");
            }

            if (parameters.Has("transparency"))
                layer.SetTransparency(parameters.GetDouble("transparency"));

            if (warnings.Count > 0) result["warnings"] = warnings;
            return result;
        }

        /// <summary>
        /// Explicit colours per class, e.g. a pastel ramp the built-in styles
        /// do not offer.
        /// </summary>
        private static void ApplyClassColors(CIMClassBreaksRenderer renderer,
                                             Params parameters, List<string> warnings)
        {
            var raw = parameters.Raw("class_colors");
            if (renderer?.Breaks == null
                || raw.ValueKind != System.Text.Json.JsonValueKind.Array) return;

            var colors = raw.EnumerateArray()
                .Select(item => item.EnumerateArray().Select(v => v.GetInt32()).ToArray())
                .ToList();
            if (colors.Count == 0) return;

            for (var i = 0; i < renderer.Breaks.Length; i++)
            {
                var rgba = colors[Math.Min(i, colors.Count - 1)];
                if (rgba.Length < 3) continue;
                if (rgba.Length == 3) rgba = new[] { rgba[0], rgba[1], rgba[2], 100 };
                renderer.Breaks[i].Symbol = PolygonSymbol(
                    rgba, parameters.GetColor("outline_color"),
                    parameters.GetOptionalDouble("outline_width"));
            }
            if (colors.Count < renderer.Breaks.Length)
                warnings.Add($"{colors.Count} colours for {renderer.Breaks.Length} "
                           + "classes; the last colour was repeated.");
        }

        private static void ApplyValueColors(CIMUniqueValueRenderer renderer,
                                             Params parameters, List<string> warnings)
        {
            var colors = parameters.GetObject("value_colors");
            if (renderer?.Groups == null || colors == null) return;

            foreach (var group in renderer.Groups)
            {
                foreach (var valueClass in group.Classes ?? Array.Empty<CIMUniqueValue>()
                             .Select(_ => (CIMUniqueValueClass)null).ToArray())
                {
                    if (valueClass?.Values == null) continue;
                    var key = valueClass.Values.FirstOrDefault()?.FieldValues?.FirstOrDefault();
                    if (key == null || !colors.TryGetValue(key, out var element)) continue;
                    var rgba = element.EnumerateArray().Select(v => v.GetInt32()).ToArray();
                    if (rgba.Length < 3) continue;
                    if (rgba.Length == 3) rgba = new[] { rgba[0], rgba[1], rgba[2], 100 };
                    valueClass.Symbol = PolygonSymbol(rgba, null, null);
                }
            }
        }

        private static object GetSymbology(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.RequireFeatureLayer(map, parameters.Require("layer_name"))
                        as FeatureLayer;
            if (layer == null) throw new ArgumentException("Not a feature layer.");

            var info = new Dictionary<string, object> { ["layer"] = layer.Name };
            var renderer = layer.GetRenderer();
            info["renderer"] = renderer?.GetType().Name;

            if (renderer is CIMClassBreaksRenderer breaks)
            {
                info["classification_field"] = breaks.Field;
                info["class_breaks"] = breaks.Breaks?.Select(b =>
                    new Dictionary<string, object>
                    {
                        ["upper_bound"] = b.UpperBound,
                        ["label"] = b.Label,
                    }).ToList();
            }
            else if (renderer is CIMUniqueValueRenderer unique)
            {
                info["fields"] = unique.Fields;
                info["unique_values"] = unique.Groups?
                    .SelectMany(g => g.Classes ?? new CIMUniqueValueClass[0])
                    .Select(c => new Dictionary<string, object>
                    {
                        ["label"] = c.Label,
                        ["values"] = c.Values?.SelectMany(v => v.FieldValues ?? new string[0])
                                              .ToList(),
                    }).Take(200).ToList();
            }

            var definition = layer.GetDefinition() as CIMFeatureLayer;
            info["labels_visible"] = definition?.LabelVisibility;
            info["label_classes"] = definition?.LabelClasses?.Select(labelClass =>
                new Dictionary<string, object>
                {
                    ["name"] = labelClass.Name,
                    ["expression"] = labelClass.Expression,
                    ["engine"] = labelClass.ExpressionEngine.ToString(),
                    ["visible"] = labelClass.Visibility,
                }).ToList();

            return info;
        }

        private static object ListColorRamps(Params parameters)
        {
            var query = parameters.GetString("wildcard", "*")?.Trim('*') ?? string.Empty;
            var limit = parameters.GetInt("limit", 500);
            var names = new List<string>();

            foreach (var style in Project.Current.GetItems<StyleProjectItem>())
            {
                var matches = style.SearchColorRamps(query);
                if (matches == null) continue;
                names.AddRange(matches.Select(item => item.Name));
            }

            var ordered = names.Distinct(StringComparer.Ordinal)
                               .OrderBy(name => name, StringComparer.Ordinal).ToList();
            return new Dictionary<string, object>
            {
                ["count"] = ordered.Count,
                ["color_ramps"] = ordered.Take(limit).ToList(),
                ["truncated"] = ordered.Count > limit,
            };
        }

        private static object SetLabeling(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var layer = MapHelpers.RequireFeatureLayer(map, parameters.Require("layer_name"))
                        as FeatureLayer;
            if (layer == null) throw new ArgumentException("Not a feature layer.");

            var enabled = parameters.GetBool("enabled", true);
            var definition = layer.GetDefinition() as CIMFeatureLayer;
            if (definition == null) throw new InvalidOperationException("No layer definition.");

            definition.LabelVisibility = enabled;

            var labelClass = definition.LabelClasses?.FirstOrDefault();
            var result = new Dictionary<string, object>
            {
                ["layer"] = layer.Name,
                ["labels_visible"] = enabled,
            };

            if (enabled && labelClass != null)
            {
                if (parameters.Has("expression"))
                {
                    labelClass.Expression = parameters.GetString("expression");
                    labelClass.ExpressionEngine =
                        (parameters.GetString("expression_engine", "Arcade") ?? "Arcade")
                            .Equals("Arcade", StringComparison.OrdinalIgnoreCase)
                        ? LabelExpressionEngine.Arcade
                        : LabelExpressionEngine.VBScript;
                    result["expression"] = labelClass.Expression;
                }
                if (parameters.Has("where"))
                    labelClass.WhereClause = parameters.GetString("where");
                labelClass.Visibility = true;

                var textSymbol = labelClass.TextSymbol?.Symbol as CIMTextSymbol;
                if (textSymbol != null)
                {
                    if (parameters.Has("font_size"))
                        textSymbol.Height = parameters.GetDouble("font_size");
                    if (parameters.Has("font_family"))
                        textSymbol.FontFamilyName = parameters.GetString("font_family");
                    if (parameters.GetBool("bold")) textSymbol.FontStyleName = "Bold";
                    if (parameters.Has("font_color"))
                        textSymbol.SetColor(ToColor(parameters.GetColor("font_color")));
                    if (parameters.Has("halo_size"))
                        textSymbol.HaloSize = parameters.GetDouble("halo_size");
                    result["font_applied"] = true;
                }
            }

            layer.SetDefinition(definition);
            return result;
        }
    }
}
