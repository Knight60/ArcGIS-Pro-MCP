using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using ArcGIS.Core.CIM;
using ArcGIS.Core.Geometry;
using ArcGIS.Desktop.Core;
using ArcGIS.Desktop.Layouts;
using ArcGIS.Desktop.Mapping;
using ArcGISProMCP.Bridge;

namespace ArcGISProMCP.Commands
{
    /// <summary>Print layouts: build them, arrange them, export them.</summary>
    internal static class LayoutCommands
    {
        private const string Group = "layout";

        public static void Register()
        {
            CommandRouter.Register("list_layouts", Group,
                "List the print layouts with page size and element counts.", ListLayouts);
            CommandRouter.Register("get_layout_info", Group,
                "Page setup and every element with position and size.", GetLayoutInfo);
            CommandRouter.Register("create_layout", Group,
                "Create a layout page, by default with a map frame filling it.",
                CreateLayout);
            CommandRouter.Register("delete_layout", Group,
                "Delete a layout from the project.", DeleteLayout);
            CommandRouter.Register("add_map_frame", Group,
                "Add a map frame at a page position.", AddMapFrame);
            CommandRouter.Register("set_map_frame_extent", Group,
                "Point a map frame at a layer, an extent or a scale.", SetMapFrameExtent);
            CommandRouter.Register("add_layout_text", Group,
                "Add a text element such as a title.", AddText);
            CommandRouter.Register("add_layout_legend", Group,
                "Add a legend tied to a map frame.", AddLegend);
            CommandRouter.Register("add_layout_scale_bar", Group,
                "Add a scale bar tied to a map frame.", AddScaleBar);
            CommandRouter.Register("add_layout_north_arrow", Group,
                "Add a north arrow tied to a map frame.", AddNorthArrow);
            CommandRouter.Register("add_layout_picture", Group,
                "Place an image such as a logo on a layout.", AddPicture);
            CommandRouter.Register("set_layout_element", Group,
                "Move, resize, rename, hide or retext an element.", SetElement);
            CommandRouter.Register("delete_layout_element", Group,
                "Remove an element from a layout.", DeleteElement);
            CommandRouter.Register("export_layout", Group,
                "Export a layout to PDF / PNG / JPEG / TIFF.", ExportLayout);
            CommandRouter.Register("preview_layout", Group,
                "Render a layout to a temporary image and return it inline.",
                PreviewLayout);
        }

        // --- lookups ---------------------------------------------------------

        private static Layout FindLayout(Params parameters)
        {
            var name = parameters.Require("layout_name");
            var items = Project.Current.GetItems<LayoutProjectItem>().ToList();
            var match = items.FirstOrDefault(
                item => string.Equals(item.Name, name, StringComparison.OrdinalIgnoreCase));
            if (match == null)
                throw new ArgumentException(
                    $"Layout not found: {name}. Available: "
                    + (items.Count == 0 ? "(none)" : string.Join(", ", items.Select(i => i.Name))));
            return match.GetLayout();
        }

        private static Element FindElement(Layout layout, string name)
        {
            var element = layout.FindElement(name);
            if (element == null)
                throw new ArgumentException(
                    $"Element not found in layout '{layout.Name}': {name}. Elements: "
                    + string.Join(", ", layout.GetElements().Select(e => e.Name)));
            return element;
        }

        private static MapFrame FindMapFrame(Layout layout, Params parameters)
        {
            var name = parameters.GetString("map_frame_name");
            if (!string.IsNullOrWhiteSpace(name))
            {
                if (FindElement(layout, name) is MapFrame named) return named;
                throw new ArgumentException($"'{name}' is not a map frame.");
            }
            var frame = layout.GetElements().OfType<MapFrame>().FirstOrDefault();
            if (frame == null)
                throw new InvalidOperationException(
                    $"Layout '{layout.Name}' has no map frame. Add one with add_map_frame.");
            return frame;
        }

        /// <summary>A rectangle in page units, anchored at its lower-left corner.</summary>
        private static Envelope PageBox(Params parameters, double defaultWidth,
                                        double defaultHeight)
        {
            var x = parameters.GetDouble("x", 0.5);
            var y = parameters.GetDouble("y", 0.5);
            var width = parameters.GetDouble("width", defaultWidth);
            var height = parameters.GetDouble("height", defaultHeight);
            return EnvelopeBuilderEx.CreateEnvelope(x, y, x + width, y + height);
        }

        private static Dictionary<string, object> Describe(Element element)
        {
            var info = new Dictionary<string, object>
            {
                ["name"] = element.Name,
                ["type"] = element.GetType().Name,
                ["visible"] = element.IsVisible,
            };
            try
            {
                info["x"] = element.GetX();
                info["y"] = element.GetY();
                info["width"] = element.GetWidth();
                info["height"] = element.GetHeight();
            }
            catch { /* some elements have no box */ }

            if (element is MapFrame frame)
            {
                info["map"] = frame.Map?.Name;
                info["scale"] = frame.Camera?.Scale;
            }
            return info;
        }

        // --- commands --------------------------------------------------------

        private static object ListLayouts(Params parameters)
        {
            return Project.Current.GetItems<LayoutProjectItem>().Select(item =>
            {
                var layout = item.GetLayout();
                return new Dictionary<string, object>
                {
                    ["name"] = layout.Name,
                    ["page_width"] = layout.GetPage()?.Width,
                    ["page_height"] = layout.GetPage()?.Height,
                    ["page_units"] = layout.GetPage()?.Units.ToString(),
                    ["element_count"] = layout.GetElements().Count,
                };
            }).ToList();
        }

        private static object GetLayoutInfo(Params parameters)
        {
            var layout = FindLayout(parameters);
            var page = layout.GetPage();
            return new Dictionary<string, object>
            {
                ["name"] = layout.Name,
                ["page_width"] = page?.Width,
                ["page_height"] = page?.Height,
                ["page_units"] = page?.Units.ToString(),
                ["elements"] = layout.GetElementsAsFlattenedList().Select(Describe).ToList(),
            };
        }

        private static LinearUnit ParseUnits(string name)
        {
            switch ((name ?? "INCH").ToUpperInvariant())
            {
                case "CENTIMETER":
                case "CENTIMETERS": return LinearUnit.Centimeters;
                case "MILLIMETER":
                case "MILLIMETERS": return LinearUnit.Millimeters;
                case "POINT":
                case "POINTS": return LinearUnit.Points;
                default: return LinearUnit.Inches;
            }
        }

        private static object CreateLayout(Params parameters)
        {
            var name = parameters.Require("name");
            var width = parameters.GetDouble("page_width", 11);
            var height = parameters.GetDouble("page_height", 8.5);
            var units = ParseUnits(parameters.GetString("page_units"));

            var layout = LayoutFactory.Instance.CreateLayout(width, height, units, true, 1);
            layout.SetName(name);

            var created = new Dictionary<string, object>
            {
                ["created_layout"] = name,
                ["page_width"] = width,
                ["page_height"] = height,
                ["page_units"] = units.Name,
            };

            if (parameters.GetBool("add_map_frame", true))
            {
                try
                {
                    var map = MapHelpers.ResolveMap(parameters);
                    var margin = parameters.GetDouble("margin", 0.5);
                    var box = EnvelopeBuilderEx.CreateEnvelope(
                        margin, margin, width - margin, height - margin);
                    var frameName = parameters.GetString("map_frame_name", "Map Frame");
                    var frame = ElementFactory.Instance.CreateMapFrameElement(
                        layout, box, map, frameName);
                    frame.SetCamera(map.GetDefaultExtent());
                    created["map_frame"] = frame.Name;
                    created["map"] = map.Name;
                }
                catch (Exception exception)
                {
                    created["map_frame_warning"] = exception.Message;
                }
            }

            return created;
        }

        private static object DeleteLayout(Params parameters)
        {
            var name = parameters.Require("layout_name");
            var item = Project.Current.GetItems<LayoutProjectItem>().FirstOrDefault(
                i => string.Equals(i.Name, name, StringComparison.OrdinalIgnoreCase));
            if (item == null) throw new ArgumentException($"Layout not found: {name}");
            Project.Current.RemoveItem(item);
            return new Dictionary<string, object> { ["deleted_layout"] = name };
        }

        private static object AddMapFrame(Params parameters)
        {
            var layout = FindLayout(parameters);
            var map = MapHelpers.ResolveMap(parameters);
            var frame = ElementFactory.Instance.CreateMapFrameElement(
                layout, PageBox(parameters, 6, 5), map,
                parameters.GetString("name", "Map Frame"));
            try { frame.SetCamera(map.GetDefaultExtent()); } catch { /* empty map */ }

            return new Dictionary<string, object>
            {
                ["layout"] = layout.Name,
                ["map_frame"] = frame.Name,
                ["map"] = map.Name,
            };
        }

        private static object SetMapFrameExtent(Params parameters)
        {
            var layout = FindLayout(parameters);
            var frame = FindMapFrame(layout, parameters);
            var applied = new Dictionary<string, object>();

            var layerName = parameters.GetString("layer_name");
            if (!string.IsNullOrWhiteSpace(layerName))
            {
                var layer = MapHelpers.RequireFeatureLayer(frame.Map, layerName);
                frame.SetCamera(layer, parameters.GetBool("selection_only"));
                applied["zoomed_to_layer"] = layer.Name;
            }
            else if (parameters.Has("extent"))
            {
                var extent = parameters.GetObject("extent");
                var envelope = EnvelopeBuilderEx.CreateEnvelope(
                    extent["xmin"].GetDouble(), extent["ymin"].GetDouble(),
                    extent["xmax"].GetDouble(), extent["ymax"].GetDouble(),
                    frame.Map?.SpatialReference);
                frame.SetCamera(envelope);
                applied["extent"] = MapHelpers.Describe(envelope);
            }
            else if (parameters.GetBool("zoom_to_all"))
            {
                frame.SetCamera(frame.Map.GetDefaultExtent());
                applied["zoomed_to_all_layers"] = true;
            }

            if (parameters.Has("scale"))
            {
                var camera = frame.Camera;
                camera.Scale = parameters.GetDouble("scale");
                frame.SetCamera(camera);
                applied["scale"] = camera.Scale;
            }
            if (applied.Count == 0)
                throw new ArgumentException(
                    "Provide layer_name, extent, zoom_to_all or scale.");

            return new Dictionary<string, object>
            {
                ["layout"] = layout.Name,
                ["map_frame"] = frame.Name,
                ["applied"] = applied,
            };
        }

        private static object AddText(Params parameters)
        {
            var layout = FindLayout(parameters);
            var text = parameters.Require("text");
            var name = parameters.GetString("name", "Text");

            var color = parameters.GetColor("color");
            var symbol = SymbolFactory.Instance.ConstructTextSymbol(
                color != null
                    ? ColorFactory.Instance.CreateRGBColor(color[0], color[1], color[2])
                    : ColorFactory.Instance.BlackRGB,
                parameters.GetDouble("font_size", 14),
                parameters.GetString("font", "Tahoma"),
                parameters.GetBool("bold") ? "Bold" : "Regular");

            var point = MapPointBuilderEx.CreateMapPoint(
                parameters.GetDouble("x", 0.5), parameters.GetDouble("y", 8.0));
            var element = ElementFactory.Instance.CreateTextGraphicElement(
                layout, TextType.PointText, point, symbol, text, name);

            return new Dictionary<string, object>
            {
                ["layout"] = layout.Name,
                ["text_element"] = element.Name,
                ["text"] = text,
                ["position"] = new[] { element.GetX(), element.GetY() },
            };
        }

        /// <summary>MapSurroundInfo is abstract; each surround has its own subclass.</summary>
        private static object AddSurround(Params parameters, MapSurroundInfo info,
                                          string defaultName, string resultKey)
        {
            var layout = FindLayout(parameters);
            var frame = FindMapFrame(layout, parameters);
            info.MapFrameName = frame.Name;

            var element = ElementFactory.Instance.CreateMapSurroundElement(
                layout, PageBox(parameters, 2.5, 1.5), info,
                parameters.GetString("name", defaultName));

            return new Dictionary<string, object>
            {
                ["layout"] = layout.Name,
                [resultKey] = element.Name,
                ["map_frame"] = frame.Name,
            };
        }

        private static object AddLegend(Params parameters)
        {
            var layout = FindLayout(parameters);
            var frame = FindMapFrame(layout, parameters);
            var info = new LegendInfo { MapFrameName = frame.Name };

            var element = ElementFactory.Instance.CreateMapSurroundElement(
                layout, PageBox(parameters, 2.5, 2.0), info,
                parameters.GetString("name", "Legend"));

            return new Dictionary<string, object>
            {
                ["layout"] = layout.Name,
                ["legend"] = element.Name,
                ["map_frame"] = frame.Name,
            };
        }

        private static object AddScaleBar(Params parameters) =>
            AddSurround(parameters, new ScaleBarInfo(), "Scale Bar", "scale_bar");

        private static object AddNorthArrow(Params parameters) =>
            AddSurround(parameters, new NorthArrowInfo(), "North Arrow", "north_arrow");

        private static object AddPicture(Params parameters)
        {
            var layout = FindLayout(parameters);
            var path = parameters.Require("picture_path");
            if (!File.Exists(path))
                throw new ArgumentException($"Image file not found: {path}");

            var element = ElementFactory.Instance.CreatePictureGraphicElement(
                layout, PageBox(parameters, 1.5, 1.0), path,
                parameters.GetString("name", "Picture"));

            return new Dictionary<string, object>
            {
                ["layout"] = layout.Name,
                ["picture"] = element.Name,
                ["source"] = path,
            };
        }

        private static object SetElement(Params parameters)
        {
            var layout = FindLayout(parameters);
            var element = FindElement(layout, parameters.Require("element_name"));
            var applied = new Dictionary<string, object>();

            if (parameters.Has("x")) { element.SetX(parameters.GetDouble("x")); applied["x"] = element.GetX(); }
            if (parameters.Has("y")) { element.SetY(parameters.GetDouble("y")); applied["y"] = element.GetY(); }
            if (parameters.Has("width")) { element.SetWidth(parameters.GetDouble("width")); applied["width"] = element.GetWidth(); }
            if (parameters.Has("height")) { element.SetHeight(parameters.GetDouble("height")); applied["height"] = element.GetHeight(); }
            if (parameters.Has("visible"))
            {
                element.SetVisible(parameters.GetBool("visible"));
                applied["visible"] = element.IsVisible;
            }
            if (parameters.Has("new_name"))
            {
                element.SetName(parameters.GetString("new_name"));
                applied["name"] = element.Name;
            }
            if (parameters.Has("text") && element is GraphicElement graphic
                && graphic.GetGraphic() is CIMTextGraphic textGraphic)
            {
                textGraphic.Text = parameters.GetString("text");
                graphic.SetGraphic(textGraphic);
                applied["text"] = textGraphic.Text;
            }

            return new Dictionary<string, object>
            {
                ["layout"] = layout.Name,
                ["element"] = element.Name,
                ["applied"] = applied,
            };
        }

        private static object DeleteElement(Params parameters)
        {
            var layout = FindLayout(parameters);
            var name = parameters.Require("element_name");
            layout.DeleteElement(FindElement(layout, name));
            return new Dictionary<string, object>
            {
                ["layout"] = layout.Name,
                ["deleted_element"] = name,
            };
        }

        private static ExportFormat FormatFor(string path, int dpi)
        {
            switch (Path.GetExtension(path).ToLowerInvariant())
            {
                case ".pdf": return new PDFFormat { OutputFileName = path, Resolution = dpi };
                case ".png": return new PNGFormat { OutputFileName = path, Resolution = dpi };
                case ".jpg":
                case ".jpeg": return new JPEGFormat { OutputFileName = path, Resolution = dpi };
                case ".tif":
                case ".tiff": return new TIFFFormat { OutputFileName = path, Resolution = dpi };
                default:
                    throw new ArgumentException(
                        $"Unsupported export format '{Path.GetExtension(path)}'. "
                        + "Use .pdf, .png, .jpg or .tif.");
            }
        }

        private static object ExportLayout(Params parameters)
        {
            var layout = FindLayout(parameters);
            var path = parameters.Require("output_path");
            if (!Path.IsPathRooted(path))
                path = Path.Combine(Project.Current.HomeFolderPath, path);

            var directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);

            var dpi = parameters.GetInt("dpi", 200);
            var format = FormatFor(path, dpi);
            if (!format.ValidateOutputFilePath())
                throw new InvalidOperationException($"ArcGIS Pro will not write to {path}");
            layout.Export(format);

            var result = new Dictionary<string, object>
            {
                ["layout"] = layout.Name,
                ["exported"] = path,
                ["dpi"] = dpi,
            };
            var extension = Path.GetExtension(path).ToLowerInvariant();
            if (parameters.GetBool("return_image", true)
                && (extension == ".png" || extension == ".jpg" || extension == ".jpeg")
                && File.Exists(path))
            {
                result["image_base64"] = Convert.ToBase64String(File.ReadAllBytes(path));
                result["image_format"] = extension == ".png" ? "png" : "jpeg";
            }
            return result;
        }

        private static object PreviewLayout(Params parameters)
        {
            var layout = FindLayout(parameters);
            var path = Path.Combine(Path.GetTempPath(), $"arcgis_mcp_layout_{Guid.NewGuid():N}.png");
            var format = new PNGFormat
            {
                OutputFileName = path,
                Resolution = parameters.GetInt("dpi", 100),
            };
            layout.Export(format);
            try
            {
                return new Dictionary<string, object>
                {
                    ["layout"] = layout.Name,
                    ["image_base64"] = Convert.ToBase64String(File.ReadAllBytes(path)),
                    ["image_format"] = "png",
                };
            }
            finally
            {
                try { File.Delete(path); } catch { /* a temp file */ }
            }
        }
    }
}
