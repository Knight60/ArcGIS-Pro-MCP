# -*- coding: utf-8 -*-
"""Raster inspection, symbology, map algebra and sampling."""

import arcpy

from .common import (add_layer_once, extent_dict, find_layer, get_map,
                     looks_like_path, project, resolve_path,
                     spatial_reference_dict)
from .registry import command

GROUP = "raster"


def _raster_source(m, name):
    if looks_like_path(name):
        return name
    lyr = find_layer(m, name)
    try:
        return lyr.dataSource
    except Exception:
        return lyr


@command("get_raster_info", GROUP)
def get_raster_info(params):
    """Raster detail: bands, size, cell size, pixel type, statistics, CRS."""
    m = get_map(map_name=params.get("map_name"))
    source = _raster_source(m, params["layer_name"])
    raster = arcpy.Raster(source)
    info = {
        "layer": params["layer_name"],
        "band_count": raster.bandCount,
        "width": raster.width,
        "height": raster.height,
        "cell_size_x": raster.meanCellWidth,
        "cell_size_y": raster.meanCellHeight,
        "pixel_type": raster.pixelType,
        "nodata_value": raster.noDataValue,
        "format": raster.format,
        "extent": extent_dict(raster.extent),
    }
    try:
        info["spatial_reference"] = spatial_reference_dict(raster.spatialReference)
    except Exception:
        pass
    for attr in ("minimum", "maximum", "mean", "standardDeviation"):
        try:
            info[attr] = getattr(raster, attr)
        except Exception:
            continue
    try:
        info["band_names"] = list(raster.bandNames)
    except Exception:
        pass
    return info


@command("set_raster_symbology", GROUP)
def set_raster_symbology(params):
    """Set a raster layer's colorizer.

    colorizer: stretch | classify | unique_values | rgb
    """
    proj = project()
    m = get_map(proj, params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    colorizer_map = {
        "stretch": "RasterStretchColorizer",
        "classify": "RasterClassifyColorizer",
        "unique_values": "RasterUniqueValueColorizer",
        "rgb": "RasterRGBColorizer",
    }
    kind = params.get("colorizer", "stretch")
    cim_name = colorizer_map.get(kind, kind)

    sym = lyr.symbology
    if not hasattr(sym, "updateColorizer"):
        raise RuntimeError("Layer '{}' is not a raster layer".format(lyr.name))
    sym.updateColorizer(cim_name)
    colorizer = sym.colorizer
    warnings = []

    if params.get("stretch_type") and hasattr(colorizer, "stretchType"):
        colorizer.stretchType = params["stretch_type"]
    if params.get("break_count") is not None and hasattr(colorizer, "breakCount"):
        colorizer.breakCount = int(params["break_count"])
    if params.get("classification_method") and hasattr(colorizer,
                                                       "classificationMethod"):
        colorizer.classificationMethod = params["classification_method"]
    if params.get("color_ramp"):
        ramps = proj.listColorRamps(params["color_ramp"]) or \
            proj.listColorRamps("*{}*".format(params["color_ramp"]))
        if ramps:
            colorizer.colorRamp = ramps[0]
        else:
            warnings.append("Color ramp '{}' not found".format(params["color_ramp"]))

    lyr.symbology = sym
    if params.get("transparency") is not None:
        lyr.transparency = int(params["transparency"])
    result = {"layer": lyr.name, "colorizer": cim_name}
    if warnings:
        result["warnings"] = warnings
    return result


@command("raster_calculator", GROUP)
def raster_calculator(params):
    """Map algebra. Bind rasters to short names, then write a Python expression.

    rasters: {"dem": "elevation_layer", "slp": "slope.tif"}
    expression: "(dem - 100) / slp"  (arcpy.sa functions such as Con, Abs,
    Slope, Log are available by name)
    """
    proj = project()
    try:
        m = get_map(proj, params.get("map_name"))
    except Exception:
        m = None
    status = arcpy.CheckOutExtension("Spatial")
    if status != "CheckedOut":
        raise RuntimeError(
            "Spatial Analyst is required for raster_calculator (status: {})".format(status)
        )
    try:
        from arcpy.sa import Raster as SaRaster
        import arcpy.sa as sa

        namespace = {name: getattr(sa, name) for name in dir(sa)
                     if not name.startswith("_")}
        for alias, source in (params.get("rasters") or {}).items():
            path = _raster_source(m, source) if m is not None else source
            namespace[alias] = SaRaster(path)
        result = eval(params["expression"], {"__builtins__": {}}, namespace)  # noqa: S307
        output_path = resolve_path(params["output_path"], proj)
        result.save(output_path)
    finally:
        arcpy.CheckInExtension("Spatial")

    added = None
    if params.get("add_to_map", True) and m is not None:
        added = add_layer_once(m, output_path)[0].name
    return {"output": output_path, "added_to_map": added,
            "expression": params["expression"]}


@command("sample_raster_values", GROUP)
def sample_raster_values(params):
    """Read raster cell values at map coordinates or at a point layer's features."""
    m = get_map(map_name=params.get("map_name"))
    source = _raster_source(m, params["layer_name"])
    results = []

    points = params.get("points")
    if points:
        for point in points:
            x, y = (point["x"], point["y"]) if isinstance(point, dict) \
                else (point[0], point[1])
            try:
                value = arcpy.management.GetCellValue(
                    source, "{} {}".format(x, y), params.get("band")
                ).getOutput(0)
            except Exception as exc:
                value = "Error: {}".format(exc)
            results.append({"x": x, "y": y, "value": value})
        return {"raster": params["layer_name"], "samples": results}

    point_layer = params.get("point_layer")
    if not point_layer:
        raise ValueError("Provide points (list of {x, y}) or point_layer")
    lyr = find_layer(m, point_layer)
    limit = int(params.get("limit", 100) or 100)
    with arcpy.da.SearchCursor(lyr, ["SHAPE@XY", "OID@"]) as cursor:
        for (x, y), oid in cursor:
            try:
                value = arcpy.management.GetCellValue(
                    source, "{} {}".format(x, y), params.get("band")
                ).getOutput(0)
            except Exception as exc:
                value = "Error: {}".format(exc)
            results.append({"oid": oid, "x": x, "y": y, "value": value})
            if len(results) >= limit:
                break
    return {"raster": params["layer_name"], "point_layer": lyr.name,
            "samples": results}


@command("zonal_statistics", GROUP)
def zonal_statistics(params):
    """Summarise raster values inside zone polygons; returns the statistics table."""
    proj = project()
    m = get_map(proj, params.get("map_name"))
    zone_layer = params["zone_layer"]
    zones = zone_layer if looks_like_path(zone_layer) else find_layer(m, zone_layer)
    raster = _raster_source(m, params["raster_layer"])
    out_table = resolve_path(
        params.get("output_table") or "in_memory/zonal_stats_result", proj)

    status = arcpy.CheckOutExtension("Spatial")
    if status != "CheckedOut":
        raise RuntimeError("Spatial Analyst is required (status: {})".format(status))
    try:
        arcpy.sa.ZonalStatisticsAsTable(
            zones, params["zone_field"], raster, out_table,
            params.get("ignore_nodata", "DATA"),
            params.get("statistics_type", "ALL"),
        )
    finally:
        arcpy.CheckInExtension("Spatial")

    fields = [f.name for f in arcpy.ListFields(out_table)
              if f.type not in ("Geometry", "Blob", "Raster")]
    rows = []
    with arcpy.da.SearchCursor(out_table, fields) as cursor:
        for row in cursor:
            rows.append(dict(zip(fields, row)))
    return {"zone_layer": str(zone_layer), "raster": params["raster_layer"],
            "output_table": out_table, "rows": rows}
