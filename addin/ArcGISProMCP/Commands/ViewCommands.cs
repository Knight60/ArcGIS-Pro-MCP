using System;
using System.Collections.Generic;
using System.IO;
using ArcGIS.Core.Geometry;
using ArcGIS.Desktop.Mapping;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>Camera control and rendering the map so the assistant can see it.</summary>
    internal static class ViewCommands
    {
        private const string Group = "view";

        public static void Register()
        {
            CommandRouter.Register("get_map_view", Group,
                "Current camera: centre, scale, rotation and visible extent.", GetMapView);

            CommandRouter.Register("set_map_view", Group,
                "Move the view: set an extent, centre, scale and/or rotation.", SetMapView);

            CommandRouter.Register("export_map_view", Group,
                "Render the map view to PNG and return it inline.", ExportMapView);
        }

        private static object GetMapView(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var view = MapHelpers.RequireActiveView(map);
            var camera = view.Camera;

            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["x"] = camera?.X,
                ["y"] = camera?.Y,
                ["scale"] = camera?.Scale,
                ["heading"] = camera?.Heading,
                ["pitch"] = camera?.Pitch,
                ["extent"] = MapHelpers.Describe(view.Extent),
            };
        }

        private static object SetMapView(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var view = MapHelpers.RequireActiveView(map);
            var applied = new Dictionary<string, object>();

            var extent = parameters.GetObject("extent");
            if (extent != null
                && extent.TryGetValue("xmin", out var xmin)
                && extent.TryGetValue("ymin", out var ymin)
                && extent.TryGetValue("xmax", out var xmax)
                && extent.TryGetValue("ymax", out var ymax))
            {
                var envelope = EnvelopeBuilderEx.CreateEnvelope(
                    xmin.GetDouble(), ymin.GetDouble(), xmax.GetDouble(), ymax.GetDouble(),
                    map.SpatialReference);
                view.ZoomTo(envelope);
                applied["extent"] = MapHelpers.Describe(envelope);
            }

            var camera = view.Camera;
            var moved = false;
            if (parameters.Has("x") && parameters.Has("y"))
            {
                camera.X = parameters.GetDouble("x");
                camera.Y = parameters.GetDouble("y");
                applied["center"] = new[] { camera.X, camera.Y };
                moved = true;
            }
            if (parameters.Has("scale"))
            {
                camera.Scale = parameters.GetDouble("scale");
                applied["scale"] = camera.Scale;
                moved = true;
            }
            if (parameters.Has("rotation"))
            {
                camera.Heading = parameters.GetDouble("rotation");
                applied["rotation"] = camera.Heading;
                moved = true;
            }
            if (moved) view.ZoomTo(camera);

            if (applied.Count == 0)
                throw new ArgumentException("Provide extent, x/y, scale and/or rotation.");

            return new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["applied"] = applied,
            };
        }

        private static object ExportMapView(Params parameters)
        {
            var map = MapHelpers.ResolveMap(parameters);
            var view = MapHelpers.RequireActiveView(map);

            var width = Math.Max(1, parameters.GetInt("width", 1200));
            var height = Math.Max(1, parameters.GetInt("height", 800));
            var dpi = Math.Max(1, parameters.GetInt("dpi", 96));

            var zoomTo = parameters.GetString("zoom_to_layer");
            if (!string.IsNullOrWhiteSpace(zoomTo))
            {
                var layer = MapHelpers.RequireFeatureLayer(map, zoomTo);
                var extent = layer.QueryExtent();
                if (extent != null && !extent.IsEmpty) view.ZoomTo(extent);
            }

            var requested = parameters.GetString("output_path");
            var temporary = string.IsNullOrWhiteSpace(requested);
            var outputPath = temporary
                ? Path.Combine(Path.GetTempPath(), $"arcgis_mcp_{Guid.NewGuid():N}.png")
                : requested;

            var directory = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);

            var format = new PNGFormat
            {
                Resolution = dpi,
                Height = height,
                Width = width,
                OutputFileName = outputPath,
            };

            if (!view.CanExport(format))
                throw new InvalidOperationException(
                    "ArcGIS Pro cannot export this view right now -- it may still be drawing.");
            view.Export(format);

            var result = new Dictionary<string, object>
            {
                ["map"] = map.Name,
                ["width"] = width,
                ["height"] = height,
                ["scale"] = view.Camera?.Scale,
            };
            if (!temporary) result["exported"] = outputPath;

            if (parameters.GetBool("return_image", true) && File.Exists(outputPath))
            {
                result["image_base64"] = Convert.ToBase64String(File.ReadAllBytes(outputPath));
                result["image_format"] = "png";
            }

            if (temporary)
            {
                try { File.Delete(outputPath); } catch { /* a temp file, never mind */ }
            }

            return result;
        }
    }
}
