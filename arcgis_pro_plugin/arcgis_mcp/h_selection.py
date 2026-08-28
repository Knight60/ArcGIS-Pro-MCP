# -*- coding: utf-8 -*-
"""Selection by attribute and by location."""

import arcpy

from .common import (extent_dict, find_layer, find_layer_or_table, get_map,
                     live_view, looks_like_path, resolve_target, target_name,
                     truncate_list)
from .registry import command

GROUP = "selection"


def _selection_count(target):
    try:
        return int(arcpy.management.GetCount(target)[0])
    except Exception:
        return None


@command("select_features", GROUP)
def select_features(params):
    """Select features by SQL where clause.

    method: NEW_SELECTION | ADD_TO_SELECTION | REMOVE_FROM_SELECTION |
    SUBSET_SELECTION | SWITCH_SELECTION | CLEAR_SELECTION
    """
    target, _m = resolve_target(params)
    method = params.get("method", "NEW_SELECTION")
    arcpy.management.SelectLayerByAttribute(
        target, method, params.get("where") or "",
        params.get("invert", "NON_INVERT"),
    )
    return {"layer": target_name(target), "method": method,
            "where": params.get("where"),
            "selected_count": _selection_count(target)}


@command("select_by_location", GROUP)
def select_by_location(params):
    """Select features by spatial relationship to another layer.

    relationship: INTERSECT | WITHIN_A_DISTANCE | CONTAINS | WITHIN |
    COMPLETELY_WITHIN | CROSSED_BY_THE_OUTLINE_OF | HAVE_THEIR_CENTER_IN | ...
    """
    m = get_map(map_name=params.get("map_name"))
    layer_name = params["layer_name"]
    target = layer_name if looks_like_path(layer_name) \
        else find_layer_or_table(m, layer_name)
    select_from = params["select_features"]
    source = select_from if looks_like_path(select_from) \
        else find_layer(m, select_from)
    arcpy.management.SelectLayerByLocation(
        target,
        params.get("relationship", "INTERSECT"),
        source,
        params.get("search_distance"),
        params.get("method", "NEW_SELECTION"),
        params.get("invert", "NOT_INVERT"),
    )
    return {
        "layer": target_name(target),
        "relationship": params.get("relationship", "INTERSECT"),
        "select_features": str(select_from),
        "selected_count": _selection_count(target),
    }


@command("get_selection", GROUP)
def get_selection(params):
    """Report what is selected: counts per layer, and optionally the OIDs/rows."""
    m = get_map(map_name=params.get("map_name"))
    layer_name = params.get("layer_name")
    layers = [find_layer(m, layer_name)] if layer_name else \
        [l for l in m.listLayers() if l.isFeatureLayer]
    limit = int(params.get("limit", 100) or 100)
    include_rows = bool(params.get("include_attributes", False))

    result = []
    for lyr in layers:
        try:
            oids = lyr.getSelectionSet()
        except Exception:
            oids = None
        if not oids:
            continue
        entry = {"layer": lyr.name, "selected_count": len(oids)}
        ids, truncated = truncate_list(sorted(oids), limit)
        entry["oids"] = ids
        entry["truncated"] = truncated
        if include_rows:
            fields = [f.name for f in arcpy.ListFields(lyr)
                      if f.type not in ("Geometry", "Blob", "Raster")]
            rows = []
            with arcpy.da.SearchCursor(lyr, fields) as cursor:
                for row in cursor:
                    rows.append(dict(zip(fields, row)))
                    if len(rows) >= limit:
                        break
            entry["features"] = rows
        result.append(entry)
    return {"map": m.name, "selections": result,
            "total_selected": sum(e["selected_count"] for e in result)}


@command("set_selection", GROUP)
def set_selection(params):
    """Select specific features by their ObjectIDs."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    oids = params.get("oids") or []
    lyr.setSelectionSet(oids, params.get("method", "NEW"))
    return {"layer": lyr.name, "selected_count": len(lyr.getSelectionSet() or [])}


@command("clear_selection", GROUP)
def clear_selection(params):
    """Clear the selection on one layer, or on every layer in the map."""
    m = get_map(map_name=params.get("map_name"))
    layer_name = params.get("layer_name")
    if layer_name:
        lyr = find_layer_or_table(m, layer_name)
        arcpy.management.SelectLayerByAttribute(lyr, "CLEAR_SELECTION")
        return {"cleared": lyr.name}
    m.clearSelection()
    return {"cleared": "all layers in map '{}'".format(m.name)}


@command("zoom_to_selection", GROUP)
def zoom_to_selection(params):
    """Zoom the map view to the currently selected features."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    view = live_view(m)
    oids = lyr.getSelectionSet()
    if not oids:
        raise ValueError("Layer '{}' has no selected features".format(lyr.name))
    extent = None
    with arcpy.da.SearchCursor(lyr, ["SHAPE@"]) as cursor:
        for row in cursor:
            if row[0] is None:
                continue
            extent = row[0].extent if extent is None else extent.union(row[0].extent)
    if extent is None:
        raise ValueError("Selected features have no geometry")
    view.camera.setExtent(extent)
    return {"layer": lyr.name, "selected_count": len(oids),
            "extent": extent_dict(extent)}
