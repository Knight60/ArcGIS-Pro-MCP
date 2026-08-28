# -*- coding: utf-8 -*-
"""Symbology, labelling and layer files."""

import arcpy

from .common import (MAX_LIST_ITEMS, color_dict, find_layer, get_map, project,
                     resolve_path, truncate_list)
from .registry import command

GROUP = "symbology"

RENDERER_ALIASES = {
    "simple": "SimpleRenderer",
    "unique_values": "UniqueValueRenderer",
    "graduated_colors": "GraduatedColorsRenderer",
    "graduated_symbols": "GraduatedSymbolsRenderer",
    "unclassed_colors": "UnclassedColorsRenderer",
    "proportional_symbols": "ProportionalRenderer",
    "dot_density": "DotDensityRenderer",
}


def _apply_color_ramp(renderer, proj, ramp_name):
    if not ramp_name:
        return None
    ramps = proj.listColorRamps(ramp_name)
    if not ramps:
        ramps = proj.listColorRamps("*{}*".format(ramp_name))
    if not ramps:
        return "Color ramp '{}' not found; keeping the default".format(ramp_name)
    renderer.colorRamp = ramps[0]
    return None


def _style_symbol(symbol, params):
    if params.get("color"):
        symbol.color = color_dict(params["color"])
    if params.get("outline_color"):
        symbol.outlineColor = color_dict(params["outline_color"])
    if params.get("outline_width") is not None:
        try:
            symbol.outlineWidth = float(params["outline_width"])
        except Exception:
            pass
    if params.get("symbol_size") is not None:
        try:
            symbol.size = float(params["symbol_size"])
        except Exception:
            pass


@command("set_layer_renderer", GROUP)
def set_layer_renderer(params):
    """Change a layer's symbology.

    renderer_type: simple | unique_values | graduated_colors |
    graduated_symbols | unclassed_colors
    """
    proj = project()
    m = get_map(proj, params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    renderer_type = params.get("renderer_type", "simple")
    cim_name = RENDERER_ALIASES.get(renderer_type, renderer_type)

    sym = lyr.symbology
    if not hasattr(sym, "updateRenderer"):
        raise RuntimeError(
            "Layer '{}' does not support feature renderers (use "
            "set_raster_symbology for rasters)".format(lyr.name)
        )
    sym.updateRenderer(cim_name)
    renderer = sym.renderer
    warnings = []

    if cim_name == "SimpleRenderer":
        _style_symbol(renderer.symbol, params)
        if params.get("label"):
            renderer.label = params["label"]

    elif cim_name == "UniqueValueRenderer":
        fields = params.get("fields") or ([params["field"]] if params.get("field")
                                          else None)
        if not fields:
            raise ValueError("unique_values needs field (or fields)")
        renderer.fields = list(fields)
        warn = _apply_color_ramp(renderer, proj, params.get("color_ramp"))
        if warn:
            warnings.append(warn)
        value_colors = params.get("value_colors") or {}
        if value_colors:
            for group in renderer.groups:
                for item in group.items:
                    key = ", ".join(item.values[0]) if item.values else item.label
                    if key in value_colors:
                        item.symbol.color = color_dict(value_colors[key])
                        item.symbol = item.symbol

    elif cim_name in ("GraduatedColorsRenderer", "GraduatedSymbolsRenderer"):
        if not params.get("field"):
            raise ValueError("{} needs field".format(renderer_type))
        renderer.classificationField = params["field"]
        if params.get("classification_method"):
            renderer.classificationMethod = params["classification_method"]
        renderer.breakCount = int(params.get("break_count", 5))
        warn = _apply_color_ramp(renderer, proj, params.get("color_ramp"))
        if warn:
            warnings.append(warn)
        if cim_name == "GraduatedSymbolsRenderer":
            if params.get("min_symbol_size") is not None:
                renderer.minimumSymbolSize = float(params["min_symbol_size"])
            if params.get("max_symbol_size") is not None:
                renderer.maximumSymbolSize = float(params["max_symbol_size"])

    elif cim_name == "UnclassedColorsRenderer":
        if not params.get("field"):
            raise ValueError("unclassed_colors needs field")
        renderer.field = params["field"]
        warn = _apply_color_ramp(renderer, proj, params.get("color_ramp"))
        if warn:
            warnings.append(warn)
    else:
        warnings.append(
            "Renderer '{}' applied with defaults; use execute_arcpy_code with the "
            "CIM for finer control".format(cim_name)
        )

    lyr.symbology = sym

    class_colors = params.get("class_colors")
    if class_colors and cim_name in ("GraduatedColorsRenderer",
                                     "GraduatedSymbolsRenderer"):
        # Committed first, then repainted: the class breaks only exist once
        # the renderer has been applied.
        sym = lyr.symbology
        breaks = sym.renderer.classBreaks
        for index, brk in enumerate(breaks):
            color = class_colors[min(index, len(class_colors) - 1)]
            brk.symbol.color = color_dict(color)
            if params.get("outline_color"):
                brk.symbol.outlineColor = color_dict(params["outline_color"])
            if params.get("outline_width") is not None:
                brk.symbol.outlineWidth = float(params["outline_width"])
            brk.symbol = brk.symbol  # some arcpy builds need the write-back
        lyr.symbology = sym
        if len(class_colors) < len(breaks):
            warnings.append(
                "{} colours for {} classes; the last colour was repeated.".format(
                    len(class_colors), len(breaks)))

    if params.get("transparency") is not None:
        lyr.transparency = int(params["transparency"])

    result = {"layer": lyr.name, "renderer": cim_name}
    if warnings:
        result["warnings"] = warnings
    try:
        if cim_name in ("GraduatedColorsRenderer", "GraduatedSymbolsRenderer"):
            result["class_breaks"] = [
                {"upper_bound": cb.upperBound, "label": cb.label}
                for cb in lyr.symbology.renderer.classBreaks
            ]
        elif cim_name == "UniqueValueRenderer":
            result["value_count"] = sum(len(g.items) for g in lyr.symbology.renderer.groups)
    except Exception:
        pass
    return result


@command("list_color_ramps", GROUP)
def list_color_ramps(params):
    """List color ramps available in the project, e.g. wildcard "*Viridis*"."""
    proj = project()
    wildcard = params.get("wildcard", "*")
    names = sorted({r.name for r in proj.listColorRamps(wildcard)})
    items, truncated = truncate_list(names, int(params.get("limit", MAX_LIST_ITEMS)))
    return {"count": len(names), "color_ramps": items, "truncated": truncated}


@command("apply_symbology_from_layer", GROUP)
def apply_symbology_from_layer(params):
    """Copy symbology from a .lyrx file or another layer onto a layer."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    source = params["symbology_source"]
    if not str(source).lower().endswith(".lyrx"):
        source = find_layer(m, source)
    else:
        source = resolve_path(source)
    arcpy.management.ApplySymbologyFromLayer(
        lyr, source,
        update_symbology=params.get("update_symbology", "MAINTAIN"),
    )
    return {"layer": lyr.name, "symbology_from": str(params["symbology_source"])}


@command("save_layer_file", GROUP)
def save_layer_file(params):
    """Save a layer (with its symbology) to a .lyrx file for reuse."""
    proj = project()
    m = get_map(proj, params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    out_path = resolve_path(params["output_path"], proj)
    if not out_path.lower().endswith(".lyrx"):
        out_path += ".lyrx"
    arcpy.management.SaveToLayerFile(lyr, out_path,
                                     params.get("relative_paths", "ABSOLUTE"))
    return {"layer": lyr.name, "saved": out_path}


@command("set_layer_labeling", GROUP)
def set_layer_labeling(params):
    """Turn labels on/off and set the label expression, font and placement.

    expression is Arcade by default, e.g. "$feature.NAME".
    """
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    if not lyr.supports("SHOWLABELS"):
        raise RuntimeError("Layer '{}' does not support labels".format(lyr.name))

    enabled = params.get("enabled", True)
    lyr.showLabels = bool(enabled)
    result = {"layer": lyr.name, "labels_visible": lyr.showLabels}
    if not enabled:
        return result

    classes = lyr.listLabelClasses()
    if not classes:
        return result
    label_class = classes[0]
    if params.get("expression"):
        label_class.expression = params["expression"]
        label_class.expressionEngine = params.get("expression_engine", "Arcade")
    if params.get("where"):
        label_class.SQLQuery = params["where"]
    label_class.visible = True
    result["expression"] = label_class.expression

    font_params = ("font_size", "font_family", "font_color", "halo_color",
                   "halo_size", "bold", "italic")
    if any(params.get(p) is not None for p in font_params):
        try:
            cim = lyr.getDefinition("V3")
            for lc in cim.labelClasses:
                symbol = lc.textSymbol.symbol
                if params.get("font_size") is not None:
                    symbol.height = float(params["font_size"])
                if params.get("font_family"):
                    symbol.fontFamilyName = params["font_family"]
                if params.get("bold"):
                    symbol.fontStyleName = "Bold"
                if params.get("italic"):
                    symbol.fontStyleName = "Italic"
                if params.get("font_color"):
                    rgb = color_dict(params["font_color"])["RGB"]
                    symbol.symbol.symbolLayers[0].color.values = rgb
                if params.get("halo_size") is not None:
                    symbol.haloSize = float(params["halo_size"])
            lyr.setDefinition(cim)
            result["font_applied"] = True
        except Exception as exc:
            result["font_warning"] = "Could not apply font settings: {}".format(exc)
    return result


@command("get_layer_symbology", GROUP)
def get_layer_symbology(params):
    """Inspect a layer's current renderer and label settings."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    data = {"layer": lyr.name}
    try:
        renderer = lyr.symbology.renderer
        data["renderer"] = type(renderer).__name__
        for attr in ("classificationField", "classificationMethod", "breakCount",
                     "field", "fields"):
            if hasattr(renderer, attr):
                data[attr] = getattr(renderer, attr)
        if hasattr(renderer, "classBreaks"):
            data["class_breaks"] = [
                {"upper_bound": cb.upperBound, "label": cb.label}
                for cb in renderer.classBreaks
            ]
        if hasattr(renderer, "groups"):
            data["unique_values"] = [
                {"label": item.label, "values": item.values}
                for group in renderer.groups for item in group.items
            ][:MAX_LIST_ITEMS]
    except Exception as exc:
        data["renderer_error"] = str(exc)
    try:
        data["labels_visible"] = lyr.showLabels
        data["label_classes"] = [
            {"name": lc.name, "expression": lc.expression, "visible": lc.visible}
            for lc in lyr.listLabelClasses()
        ]
    except Exception:
        pass
    return data
