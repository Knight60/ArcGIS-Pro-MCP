# -*- coding: utf-8 -*-
"""Layer management: add, remove, order, group, properties, joins."""

import os

import arcpy

from .common import (extent_dict, field_dict, find_layer, find_layer_or_table,
                     find_table, get_map, layer_dict, live_view,
                     looks_like_path, project, resolve_path,
                     spatial_reference_dict)
from .registry import command

GROUP = "layers"


@command("get_layers", GROUP)
def get_layers(params):
    """List layers (with group nesting and draw order) and standalone tables."""
    m = get_map(map_name=params.get("map_name"))
    include_basemap = bool(params.get("include_basemap", False))
    layers = []
    for i, lyr in enumerate(m.listLayers()):
        if lyr.isBasemapLayer and not include_basemap:
            continue
        layers.append(layer_dict(lyr, index=i))
    tables = []
    for tbl in m.listTables():
        entry = {"name": tbl.name}
        try:
            entry["data_source"] = tbl.dataSource
        except Exception:
            pass
        tables.append(entry)
    return {"map": m.name, "layer_count": len(layers),
            "layers": layers, "tables": tables}


@command("get_layer_info", GROUP)
def get_layer_info(params):
    """Full layer detail: source, CRS, extent, fields, feature count, symbology."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer_or_table(m, params["layer_name"])
    info = layer_dict(lyr) if hasattr(lyr, "isFeatureLayer") else {"name": lyr.name}
    try:
        desc = arcpy.Describe(lyr)
    except Exception as exc:
        info["describe_error"] = str(exc)
        return info
    info["data_type"] = desc.dataType
    try:
        info["spatial_reference"] = spatial_reference_dict(desc.spatialReference)
    except Exception:
        pass
    try:
        info["extent"] = extent_dict(desc.extent)
    except Exception:
        pass
    try:
        info["fields"] = [field_dict(f) for f in arcpy.ListFields(lyr)]
        info["oid_field"] = getattr(desc, "OIDFieldName", None)
    except Exception:
        pass
    try:
        info["feature_count"] = int(arcpy.management.GetCount(lyr)[0])
    except Exception:
        pass
    try:
        if getattr(lyr, "isFeatureLayer", False):
            info["renderer"] = type(lyr.symbology.renderer).__name__
    except Exception:
        pass
    try:
        if getattr(lyr, "supports", lambda x: False)("SHOWLABELS"):
            info["labels_visible"] = lyr.showLabels
    except Exception:
        pass
    return info


@command("add_layer", GROUP)
def add_layer(params):
    """Add data from a path or service URL (feature class, raster, .lyrx, table)."""
    proj = project()
    m = get_map(proj, params.get("map_name"))
    path = params["path"]
    group_name = params.get("group_layer")
    position = params.get("position", "AUTO_ARRANGE")

    if group_name:
        group = find_layer(m, group_name)
        if not group.isGroupLayer:
            raise ValueError("'{}' is not a group layer".format(group_name))
        layer_file = arcpy.mp.LayerFile(path) if str(path).lower().endswith(".lyrx") \
            else None
        if layer_file is not None:
            m.addLayerToGroup(group, layer_file, position)
            added = layer_file.listLayers()[0].name
        else:
            temp = m.addDataFromPath(path)
            m.addLayerToGroup(group, temp, position)
            m.removeLayer(temp)
            added = temp.name
        return {"added": added, "map": m.name, "group": group.name}

    result = m.addDataFromPath(path)
    return {"added": getattr(result, "name", str(result)), "map": m.name}


@command("add_web_layer", GROUP)
def add_web_layer(params):
    """Add a web service layer (Feature/Map/Image/WMS/WMTS/vector tile URL)."""
    m = get_map(map_name=params.get("map_name"))
    url = params["url"]
    result = m.addDataFromPath(url)
    return {"added": getattr(result, "name", str(result)), "url": url, "map": m.name}


@command("remove_layer", GROUP)
def remove_layer(params):
    """Remove a layer (or standalone table) from a map.

    Removes every layer with that name -- duplicates are easy to end up with,
    since ArcGIS Pro adds geoprocessing outputs to the map on its own.
    """
    m = get_map(map_name=params.get("map_name"))
    name = params["layer_name"]
    lowered = str(name).lower()
    removed = 0
    while True:
        matches = [l for l in m.listLayers()
                   if l.name.lower() == lowered or l.longName.lower() == lowered]
        if not matches:
            break
        m.removeLayer(matches[0])
        removed += 1
        if removed > 50:  # guard against a layer that refuses to go
            break
    if removed:
        return {"removed": name, "count": removed, "map": m.name}
    tbl = find_table(m, name)
    m.removeTable(tbl)
    return {"removed_table": name, "map": m.name}


@command("rename_layer", GROUP)
def rename_layer(params):
    """Rename a layer in the table of contents."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    old = lyr.name
    lyr.name = params["new_name"]
    return {"renamed_from": old, "renamed_to": lyr.name}


@command("duplicate_layer", GROUP)
def duplicate_layer(params):
    """Copy a layer within the map (same source, independent symbology)."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    copy = m.addDataFromPath(lyr.dataSource)
    if params.get("new_name"):
        copy.name = params["new_name"]
    return {"duplicated": lyr.name, "new_layer": copy.name}


@command("set_layer_visibility", GROUP)
def set_layer_visibility(params):
    """Show or hide one layer, a list of layers, or all layers."""
    m = get_map(map_name=params.get("map_name"))
    visible = bool(params["visible"])
    names = params.get("layer_names")
    if names is None:
        name = params.get("layer_name")
        names = [name] if name else None
    changed = []
    if not names:
        for lyr in m.listLayers():
            if lyr.isBasemapLayer:
                continue
            lyr.visible = visible
            changed.append(lyr.name)
    else:
        for name in names:
            lyr = find_layer(m, name)
            lyr.visible = visible
            changed.append(lyr.name)
    return {"visible": visible, "layers": changed}


@command("set_layer_transparency", GROUP)
def set_layer_transparency(params):
    """Set layer transparency (0 = opaque, 100 = invisible)."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    lyr.transparency = int(params["transparency"])
    return {"layer": lyr.name, "transparency": lyr.transparency}


@command("set_layer_scale_range", GROUP)
def set_layer_scale_range(params):
    """Set the scale range a layer draws at (0 or null = no limit)."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    result = {"layer": lyr.name}
    if "min_scale" in params:
        lyr.maxThreshold = float(params.get("min_scale") or 0)
        result["min_scale"] = lyr.maxThreshold
    if "max_scale" in params:
        lyr.minThreshold = float(params.get("max_scale") or 0)
        result["max_scale"] = lyr.minThreshold
    return result


@command("set_definition_query", GROUP)
def set_definition_query(params):
    """Set a layer's definition query (SQL where clause). Empty clears it."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer_or_table(m, params["layer_name"])
    lyr.definitionQuery = params.get("query") or ""
    return {"layer": lyr.name, "definition_query": lyr.definitionQuery}


@command("move_layer", GROUP)
def move_layer(params):
    """Move a layer above/below another layer, or into a group layer."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    position = params.get("position", "BEFORE")
    target_name = params.get("reference_layer") or params.get("group_layer")
    if not target_name:
        raise ValueError("Provide reference_layer or group_layer")
    target = find_layer(m, target_name)
    if params.get("group_layer") and target.isGroupLayer:
        m.addLayerToGroup(target, lyr, "AUTO_ARRANGE")
        m.removeLayer(lyr)
        return {"moved": lyr.name, "into_group": target.name}
    m.moveLayer(target, lyr, position)
    return {"moved": lyr.name, "relative_to": target.name, "position": position}


@command("create_group_layer", GROUP)
def create_group_layer(params):
    """Create an empty group layer, optionally moving layers into it."""
    m = get_map(map_name=params.get("map_name"))
    name = params["name"]
    try:
        group = m.createGroupLayer(name)
    except AttributeError:
        raise RuntimeError(
            "Map.createGroupLayer() requires ArcGIS Pro 3.0+. On older versions "
            "create the group manually, or use execute_arcpy_code with the CIM."
        )
    moved = []
    for layer_name in params.get("layer_names") or []:
        lyr = find_layer(m, layer_name)
        m.addLayerToGroup(group, lyr, "AUTO_ARRANGE")
        m.removeLayer(lyr)
        moved.append(layer_name)
    return {"created_group": group.name, "moved_in": moved}


@command("zoom_to_layer", GROUP)
def zoom_to_layer(params):
    """Zoom the map view to a layer's extent."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer(m, params["layer_name"])
    view = live_view(m)
    extent = arcpy.Describe(lyr).extent
    expand = float(params.get("expand_factor") or 0)
    if expand:
        dx = (extent.XMax - extent.XMin) * expand
        dy = (extent.YMax - extent.YMin) * expand
        extent = arcpy.Extent(extent.XMin - dx, extent.YMin - dy,
                              extent.XMax + dx, extent.YMax + dy,
                              spatial_reference=extent.spatialReference)
    view.camera.setExtent(extent)
    return {"zoomed_to": lyr.name, "extent": extent_dict(extent),
            "scale": view.camera.scale}


@command("set_basemap", GROUP)
def set_basemap(params):
    """Set the basemap: Topographic, Imagery, Streets, Light Gray Canvas, ..."""
    m = get_map(map_name=params.get("map_name"))
    m.addBasemap(params["basemap_name"])
    return {"map": m.name, "basemap": params["basemap_name"]}


@command("get_broken_layers", GROUP)
def get_broken_layers(params):
    """List layers whose data source is missing, across all maps."""
    proj = project()
    broken = []
    for m in proj.listMaps():
        for lyr in m.listLayers():
            if lyr.isBroken:
                entry = {"map": m.name, "layer": lyr.name}
                try:
                    entry["connection_properties"] = lyr.connectionProperties
                except Exception:
                    pass
                broken.append(entry)
    return {"broken_count": len(broken), "broken_layers": broken}


@command("repair_layer_source", GROUP)
def repair_layer_source(params):
    """Repoint a layer at a new workspace or dataset (fixes a broken layer).

    new_source may be a workspace (folder/.gdb) or a full dataset path.
    """
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer_or_table(m, params["layer_name"])
    new_path = resolve_path(params["new_source"])
    dataset = params.get("dataset_name")
    if os.path.isdir(new_path) or new_path.lower().endswith((".gdb", ".sde")):
        old_workspace = arcpy.Describe(lyr).path if not lyr.isBroken else None
        lyr.updateConnectionProperties(old_workspace or lyr.connectionProperties,
                                       new_path, validate=False)
    else:
        workspace = os.path.dirname(new_path)
        lyr.replaceDataSource(workspace, "NONE",
                              dataset or os.path.basename(new_path))
    return {"layer": lyr.name, "is_broken": lyr.isBroken, "new_source": new_path}


@command("add_join", GROUP)
def add_join(params):
    """Join a table to a layer on a common field (arcpy AddJoin)."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer_or_table(m, params["layer_name"])
    join_table = params["join_table"]
    join_target = join_table if looks_like_path(join_table) \
        else find_layer_or_table(m, join_table)
    arcpy.management.AddJoin(
        lyr, params["layer_field"], join_target, params["join_field"],
        params.get("keep_all", "KEEP_ALL"),
    )
    return {"layer": lyr.name, "joined": str(join_table),
            "fields": [f.name for f in arcpy.ListFields(lyr)]}


@command("remove_join", GROUP)
def remove_join(params):
    """Remove a join from a layer."""
    m = get_map(map_name=params.get("map_name"))
    lyr = find_layer_or_table(m, params["layer_name"])
    arcpy.management.RemoveJoin(lyr, params.get("join_name"))
    return {"layer": lyr.name, "join_removed": params.get("join_name") or "(last)"}
