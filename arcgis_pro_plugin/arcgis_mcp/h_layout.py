# -*- coding: utf-8 -*-
"""Print layouts: create, populate with elements, and export."""

import base64
import os
import tempfile

import arcpy

from .common import (color_dict, extent_dict, find_element, find_layer,
                     find_layout, get_map, project, resolve_path)
from .registry import command

GROUP = "layout"


def _page_point(x, y):
    return arcpy.Point(float(x), float(y))


def _page_polygon(x, y, width, height):
    """Rectangle in page units, anchored at its lower-left corner."""
    x, y, width, height = float(x), float(y), float(width), float(height)
    array = arcpy.Array([
        arcpy.Point(x, y),
        arcpy.Point(x, y + height),
        arcpy.Point(x + width, y + height),
        arcpy.Point(x + width, y),
        arcpy.Point(x, y),
    ])
    return arcpy.Polygon(array)


def _cim(class_name):
    """ArcGIS Pro 3.x has no Layout.createTextElement/createPictureElement, so
    graphic elements are built as CIM objects and appended to the layout."""
    from arcpy.cim import CreateCIMObjectFromClassName
    return CreateCIMObjectFromClassName(class_name, "V3")


def _solid_fill(color):
    fill = _cim("CIMSolidFill")
    rgb = _cim("CIMRGBColor")
    rgb.values = color_dict(color)["RGB"]
    fill.color = rgb
    try:
        fill.enable = True
    except Exception:
        pass
    return fill


def _add_graphic(layout, element, name, params):
    """Append a CIMGraphicElement, then position it through the arcpy wrapper."""
    cim_layout = layout.getDefinition("V3")
    cim_layout.elements.append(element)
    layout.setDefinition(cim_layout)

    created = find_element(layout, name)
    for key, attr in (("x", "elementPositionX"), ("y", "elementPositionY"),
                      ("width", "elementWidth"), ("height", "elementHeight")):
        if params.get(key) is not None:
            try:
                setattr(created, attr, float(params[key]))
            except Exception:
                pass
    return created


def _element_dict(el):
    info = {"name": el.name, "type": type(el).__name__}
    for attr, key in (("elementPositionX", "x"), ("elementPositionY", "y"),
                      ("elementWidth", "width"), ("elementHeight", "height"),
                      ("visible", "visible"), ("text", "text")):
        try:
            info[key] = getattr(el, attr)
        except Exception:
            continue
    try:
        if hasattr(el, "map") and el.map is not None:
            info["map"] = el.map.name
            info["scale"] = el.camera.scale
    except Exception:
        pass
    return info


@command("list_layouts", GROUP)
def list_layouts(params):
    """List print layouts with page size and element counts."""
    proj = project()
    result = []
    for layout in proj.listLayouts():
        entry = {
            "name": layout.name,
            "page_width": layout.pageWidth,
            "page_height": layout.pageHeight,
            "page_units": layout.pageUnits,
            "element_count": len(layout.listElements()),
        }
        try:
            entry["has_map_series"] = layout.mapSeries is not None
        except Exception:
            pass
        result.append(entry)
    return result


@command("get_layout_info", GROUP)
def get_layout_info(params):
    """Inspect a layout: page setup and every element with position and size."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    data = {
        "name": layout.name,
        "page_width": layout.pageWidth,
        "page_height": layout.pageHeight,
        "page_units": layout.pageUnits,
        "elements": [_element_dict(el) for el in layout.listElements()],
    }
    try:
        series = layout.mapSeries
        if series is not None:
            data["map_series"] = {
                "enabled": series.enabled,
                "page_count": series.pageCount,
                "index_layer": series.indexLayer.name if series.indexLayer else None,
                "page_name_field": getattr(series.pageNameField, "name", None),
            }
    except Exception:
        pass
    return data


@command("create_layout", GROUP)
def create_layout(params):
    """Create a new layout page, optionally with a map frame filling it."""
    proj = project()
    width = float(params.get("page_width", 11))
    height = float(params.get("page_height", 8.5))
    units = params.get("page_units", "INCH")
    layout = proj.createLayout(width, height, units, params["name"])

    created = {"created_layout": layout.name, "page_width": width,
               "page_height": height, "page_units": units}
    if params.get("add_map_frame", True):
        try:
            m = get_map(proj, params.get("map_name"))
            margin = float(params.get("margin", 0.5))
            frame = layout.createMapFrame(
                _page_polygon(margin, margin,
                              width - 2 * margin, height - 2 * margin),
                m, params.get("map_frame_name", "Map Frame"),
            )
            frame.camera.setExtent(_map_extent(m))
            created["map_frame"] = frame.name
            created["map"] = m.name
        except Exception as exc:
            created["map_frame_warning"] = str(exc)
    return created


def _map_extent(m):
    extents = []
    for lyr in m.listLayers():
        if lyr.isGroupLayer or lyr.isBasemapLayer:
            continue
        try:
            extents.append(arcpy.Describe(lyr).extent)
        except Exception:
            continue
    if not extents:
        raise RuntimeError("Map '{}' has no layers to zoom to".format(m.name))
    total = extents[0]
    for ext in extents[1:]:
        total = total.union(ext)
    return total


@command("delete_layout", GROUP)
def delete_layout(params):
    """Delete a layout from the project."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    proj.deleteItem(layout)
    return {"deleted_layout": params["layout_name"]}


@command("add_map_frame", GROUP)
def add_map_frame(params):
    """Add a map frame to a layout at a page position (page units)."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    m = get_map(proj, params.get("map_name"))
    frame = layout.createMapFrame(
        _page_polygon(params.get("x", 0.5), params.get("y", 0.5),
                      params.get("width", 6), params.get("height", 5)),
        m, params.get("name", "Map Frame"),
    )
    try:
        frame.camera.setExtent(_map_extent(m))
    except Exception:
        pass
    return {"layout": layout.name, "map_frame": frame.name, "map": m.name}


@command("set_map_frame_extent", GROUP)
def set_map_frame_extent(params):
    """Point a layout's map frame at a layer, a bookmark, a scale or an extent."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    frame = find_element(layout, params.get("map_frame_name", "Map Frame"))
    applied = {}

    if params.get("layer_name"):
        lyr = find_layer(frame.map, params["layer_name"])
        extent = frame.getLayerExtent(lyr, bool(params.get("selection_only", False)),
                                      True)
        frame.camera.setExtent(extent)
        applied["zoomed_to_layer"] = lyr.name
    elif params.get("extent"):
        ext = params["extent"]
        frame.camera.setExtent(arcpy.Extent(ext["xmin"], ext["ymin"],
                                            ext["xmax"], ext["ymax"]))
        applied["extent"] = ext
    elif params.get("zoom_to_all"):
        frame.camera.setExtent(_map_extent(frame.map))
        applied["zoomed_to_all_layers"] = True

    if params.get("scale") is not None:
        frame.camera.scale = float(params["scale"])
        applied["scale"] = frame.camera.scale
    if params.get("rotation") is not None:
        frame.camera.heading = float(params["rotation"])
        applied["rotation"] = frame.camera.heading
    if not applied:
        raise ValueError("Provide layer_name, extent, zoom_to_all, scale or rotation")
    return {"layout": layout.name, "map_frame": frame.name, "applied": applied,
            "current_extent": extent_dict(frame.camera.getExtent())}


@command("add_layout_text", GROUP)
def add_layout_text(params):
    """Add a text element (title, subtitle, credits) to a layout."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    name = params.get("name") or "Text"

    element = _cim("CIMGraphicElement")
    element.name = name
    element.visible = True

    graphic = _cim("CIMTextGraphic")
    graphic.text = params["text"]
    graphic.shape = _page_point(params.get("x", 0.5), params.get("y", 8.0))

    symbol = _cim("CIMTextSymbol")
    symbol.height = float(params.get("font_size", 14))
    symbol.fontFamilyName = params.get("font", "Tahoma")
    style = []
    if params.get("bold"):
        style.append("Bold")
    if params.get("italic"):
        style.append("Italic")
    if style:
        symbol.fontStyleName = " ".join(style)
    if params.get("color"):
        symbol.symbol.symbolLayers = [_solid_fill(params["color"])]

    reference = _cim("CIMSymbolReference")
    reference.symbol = symbol
    graphic.symbol = reference
    element.graphic = graphic

    created = _add_graphic(layout, element, name, params)
    return {"layout": layout.name, "text_element": created.name,
            "text": params["text"],
            "position": [created.elementPositionX, created.elementPositionY]}


def _create_surround(layout, params, surround_type, default_name):
    frame_name = params.get("map_frame_name", "Map Frame")
    frame = find_element(layout, frame_name)
    geometry = _page_point(params.get("x", 0.5), params.get("y", 0.5))
    if params.get("width") and params.get("height"):
        geometry = _page_polygon(params.get("x", 0.5), params.get("y", 0.5),
                                 params["width"], params["height"])
    element = layout.createMapSurroundElement(
        geometry, surround_type, frame,
        params.get("style_item"), params.get("name", default_name),
    )
    return element


@command("add_layout_legend", GROUP)
def add_layout_legend(params):
    """Add a legend tied to a layout's map frame."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    legend = _create_surround(layout, params, "LEGEND", "Legend")
    if params.get("title") is not None:
        try:
            legend.title = params["title"]
        except Exception:
            pass
    if params.get("layers") is not None:
        try:
            wanted = set(params["layers"])
            for item in legend.items:
                item.visible = item.name in wanted
        except Exception:
            pass
    return {"layout": layout.name, "legend": legend.name}


@command("add_layout_scale_bar", GROUP)
def add_layout_scale_bar(params):
    """Add a scale bar tied to a layout's map frame."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    element = _create_surround(layout, params, "SCALE_BAR", "Scale Bar")
    return {"layout": layout.name, "scale_bar": element.name}


@command("add_layout_north_arrow", GROUP)
def add_layout_north_arrow(params):
    """Add a north arrow tied to a layout's map frame."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    element = _create_surround(layout, params, "NORTH_ARROW", "North Arrow")
    return {"layout": layout.name, "north_arrow": element.name}


@command("add_layout_picture", GROUP)
def add_layout_picture(params):
    """Place an image (logo, inset) on a layout."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    picture_path = resolve_path(params["picture_path"], proj)
    if not os.path.isfile(picture_path):
        raise ValueError("Image file not found: {}".format(picture_path))
    name = params.get("name") or "Picture"

    element = _cim("CIMGraphicElement")
    element.name = name
    element.visible = True

    graphic = _cim("CIMPictureGraphic")
    graphic.sourceURL = picture_path
    graphic.shape = _page_polygon(params.get("x", 0.5), params.get("y", 0.5),
                                  params.get("width", 1.5),
                                  params.get("height", 1.0))
    element.graphic = graphic

    created = _add_graphic(layout, element, name, params)
    return {"layout": layout.name, "picture": created.name,
            "source": picture_path}


@command("set_layout_element", GROUP)
def set_layout_element(params):
    """Move, resize, rename, hide or retext any layout element."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    element = find_element(layout, params["element_name"])
    applied = {}
    mapping = (("x", "elementPositionX"), ("y", "elementPositionY"),
               ("width", "elementWidth"), ("height", "elementHeight"))
    for key, attr in mapping:
        if params.get(key) is not None:
            setattr(element, attr, float(params[key]))
            applied[key] = getattr(element, attr)
    if params.get("text") is not None:
        element.text = params["text"]
        applied["text"] = element.text
    if params.get("visible") is not None:
        element.visible = bool(params["visible"])
        applied["visible"] = element.visible
    if params.get("new_name"):
        element.name = params["new_name"]
        applied["name"] = element.name
    return {"layout": layout.name, "element": element.name, "applied": applied}


@command("delete_layout_element", GROUP)
def delete_layout_element(params):
    """Remove an element from a layout."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    element = find_element(layout, params["element_name"])
    layout.deleteElement(element)
    return {"layout": layout.name, "deleted_element": params["element_name"]}


@command("export_layout", GROUP)
def export_layout(params):
    """Export a layout to PDF / PNG / JPEG / SVG / TIFF.

    PNG and JPEG exports come back inline so the assistant can inspect them.
    """
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    output_path = resolve_path(params["output_path"], proj)
    parent = os.path.dirname(output_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    dpi = int(params.get("dpi", 200))
    ext = os.path.splitext(output_path)[1].lower()

    if ext == ".pdf":
        layout.exportToPDF(output_path, resolution=dpi)
    elif ext == ".png":
        layout.exportToPNG(output_path, resolution=dpi)
    elif ext in (".jpg", ".jpeg"):
        layout.exportToJPEG(output_path, resolution=dpi)
    elif ext == ".svg":
        layout.exportToSVG(output_path)
    elif ext in (".tif", ".tiff"):
        layout.exportToTIFF(output_path, resolution=dpi)
    else:
        raise ValueError(
            "Unsupported export format '{}'. Use .pdf, .png, .jpg, .svg or .tif".format(ext)
        )

    result = {"layout": layout.name, "exported": output_path, "dpi": dpi}
    if params.get("return_image", True) and ext in (".png", ".jpg", ".jpeg"):
        with open(output_path, "rb") as handle:
            result["image_base64"] = base64.b64encode(handle.read()).decode("ascii")
        result["image_format"] = "png" if ext == ".png" else "jpeg"
    return result


@command("export_map_series", GROUP)
def export_map_series(params):
    """Export a layout's map series (map book) to a multi-page PDF."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    series = layout.mapSeries
    if series is None or not series.enabled:
        raise RuntimeError(
            "Layout '{}' has no enabled map series. Configure it in ArcGIS Pro "
            "(Layout > Map Series) first.".format(layout.name)
        )
    output_path = resolve_path(params["output_path"], proj)
    page_range = params.get("page_range")
    if page_range:
        series.exportToPDF(output_path, "CUSTOM", page_range,
                           resolution=int(params.get("dpi", 200)))
    else:
        series.exportToPDF(output_path, "ALL",
                           resolution=int(params.get("dpi", 200)))
    return {"layout": layout.name, "exported": output_path,
            "page_count": series.pageCount}


@command("preview_layout", GROUP)
def preview_layout(params):
    """Render a layout to a temporary PNG and return it inline for inspection."""
    proj = project()
    layout = find_layout(proj, params["layout_name"])
    handle, temp_path = tempfile.mkstemp(suffix=".png", prefix="arcgis_mcp_layout_")
    os.close(handle)
    try:
        layout.exportToPNG(temp_path, resolution=int(params.get("dpi", 100)))
        with open(temp_path, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("ascii")
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass
    return {"layout": layout.name, "image_base64": encoded, "image_format": "png"}
