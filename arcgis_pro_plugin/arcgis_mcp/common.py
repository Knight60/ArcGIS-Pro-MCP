# -*- coding: utf-8 -*-
"""Shared helpers for the ArcGIS Pro MCP bridge handlers."""

import os

import arcpy

MAX_FEATURES = 5000
MAX_LIST_ITEMS = 500


# --- project / map / layer lookup -------------------------------------------

def project():
    return arcpy.mp.ArcGISProject("CURRENT")


def get_map(proj=None, map_name=None):
    proj = proj or project()
    if map_name:
        maps = proj.listMaps(map_name)
        if not maps:
            available = [m.name for m in proj.listMaps()]
            raise ValueError(
                "Map not found: {}. Available maps: {}".format(
                    map_name, ", ".join(available) or "(none)")
            )
        return maps[0]
    try:
        active = proj.activeMap
    except Exception:
        active = None
    if active is not None:
        return active
    maps = proj.listMaps()
    if not maps:
        raise ValueError("Project has no maps. Use create_map first.")
    return maps[0]


def find_layer(map_obj, layer_name, required=True):
    """Find a layer by name, long name, or (last resort) case-insensitive match."""
    layers = map_obj.listLayers()
    for lyr in layers:
        if lyr.name == layer_name or lyr.longName == layer_name:
            return lyr
    lowered = str(layer_name).lower()
    for lyr in layers:
        if lyr.name.lower() == lowered or lyr.longName.lower() == lowered:
            return lyr
    if not required:
        return None
    raise ValueError(
        "Layer not found in map '{}': {}. Layers present: {}".format(
            map_obj.name, layer_name,
            ", ".join(l.name for l in layers) or "(none)")
    )


def find_table(map_obj, table_name, required=True):
    for tbl in map_obj.listTables():
        if tbl.name == table_name:
            return tbl
    if not required:
        return None
    raise ValueError(
        "Standalone table not found in map '{}': {}".format(map_obj.name, table_name)
    )


def find_layer_or_table(map_obj, name):
    """Layers and standalone tables are interchangeable for most data commands."""
    found = find_layer(map_obj, name, required=False)
    if found is not None:
        return found
    found = find_table(map_obj, name, required=False)
    if found is not None:
        return found
    raise ValueError(
        "No layer or table named '{}' in map '{}'. Layers: {} | Tables: {}".format(
            name, map_obj.name,
            ", ".join(l.name for l in map_obj.listLayers()) or "(none)",
            ", ".join(t.name for t in map_obj.listTables()) or "(none)")
    )


def looks_like_path(value):
    text = str(value)
    return os.path.isabs(text) or text.lower().startswith(("http://", "https://"))


def resolve_target(params, key="layer_name"):
    """Resolve a data target that may be a layer name in a map or a full path.

    Returns (target, map_obj_or_None). Passing a path lets every data command
    work on datasets that are not in any map.
    """
    name = params.get(key)
    if not name:
        raise ValueError("Missing required parameter: {}".format(key))
    if looks_like_path(name):
        return name, None
    m = get_map(map_name=params.get("map_name"))
    return find_layer_or_table(m, name), m


def target_name(target):
    return getattr(target, "name", str(target))


def layer_for_source(map_obj, path):
    """The layer already showing this dataset, if there is one."""
    target = os.path.normcase(os.path.normpath(str(path)))
    for lyr in map_obj.listLayers():
        try:
            if not lyr.supports("DATASOURCE"):
                continue
            if os.path.normcase(os.path.normpath(lyr.dataSource)) == target:
                return lyr
        except Exception:
            continue
    return None


def add_layer_once(map_obj, path):
    """Add a dataset to a map unless it is already there.

    ArcGIS Pro adds geoprocessing outputs to the active map by itself
    (arcpy.env.addOutputsToMap), so adding them again leaves two identical
    layers. Returns (layer, added).
    """
    existing = layer_for_source(map_obj, path)
    if existing is not None:
        return existing, False
    return map_obj.addDataFromPath(path), True


def live_view(map_obj, required=True):
    """The map view the user is actually looking at.

    Map.defaultView hands back a detached view: exports render from it, but
    camera changes never reach the UI and its scale reads 0.0. The project's
    activeView is the live one -- verified on ArcGIS Pro 3.5.2. Fall back to
    defaultView so exports still work when a layout tab is active.
    """
    try:
        view = project().activeView
    except Exception:
        view = None
    if view is not None and getattr(view, "map", None) is not None \
            and getattr(view, "camera", None) is not None \
            and view.map.name == map_obj.name:
        return view
    view = map_obj.defaultView
    if view is None and required:
        raise RuntimeError(
            "Map '{}' has no open view in ArcGIS Pro. Open the map's tab (or "
            "call activate_map) and try again.".format(map_obj.name)
        )
    return view


def find_layout(proj, layout_name):
    layouts = proj.listLayouts(layout_name)
    if not layouts:
        raise ValueError(
            "Layout not found: {}. Available: {}".format(
                layout_name, ", ".join(l.name for l in proj.listLayouts()) or "(none)")
        )
    return layouts[0]


def find_element(layout, element_name):
    for el in layout.listElements():
        if el.name == element_name:
            return el
    raise ValueError(
        "Element not found in layout '{}': {}. Elements: {}".format(
            layout.name, element_name,
            ", ".join(e.name for e in layout.listElements()) or "(none)")
    )


# --- path handling -----------------------------------------------------------

def resolve_path(path, proj=None):
    """Relative output paths land in the project home folder."""
    if not path:
        return path
    if os.path.isabs(path):
        return path
    proj = proj or project()
    return os.path.join(proj.homeFolder, path)


def ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    return path


# --- serialisation -----------------------------------------------------------

def extent_dict(extent):
    if extent is None:
        return None
    d = {
        "xmin": extent.XMin, "ymin": extent.YMin,
        "xmax": extent.XMax, "ymax": extent.YMax,
    }
    try:
        if extent.spatialReference:
            d["spatial_reference"] = extent.spatialReference.name
            d["wkid"] = extent.spatialReference.factoryCode
    except Exception:
        pass
    return d


def field_dict(field):
    return {
        "name": field.name,
        "alias": field.aliasName,
        "type": field.type,
        "length": field.length,
        "nullable": field.isNullable,
        "editable": field.editable,
        "domain": field.domain or None,
    }


def spatial_reference_dict(sr):
    if sr is None:
        return None
    try:
        return {
            "name": sr.name,
            "wkid": sr.factoryCode,
            "type": sr.type,
            "linear_unit": getattr(sr, "linearUnitName", None),
        }
    except Exception:
        return {"name": str(sr)}


def layer_dict(lyr, index=None):
    info = {
        "name": lyr.name,
        "long_name": lyr.longName,
        "visible": lyr.visible,
        "is_group": lyr.isGroupLayer,
        "is_feature_layer": lyr.isFeatureLayer,
        "is_raster_layer": lyr.isRasterLayer,
        "is_basemap": lyr.isBasemapLayer,
        "is_web_layer": lyr.isWebLayer,
        "is_broken": lyr.isBroken,
    }
    if index is not None:
        info["index"] = index
    try:
        if lyr.supports("DATASOURCE"):
            info["data_source"] = lyr.dataSource
    except Exception:
        pass
    try:
        if lyr.supports("DEFINITIONQUERY") and lyr.definitionQuery:
            info["definition_query"] = lyr.definitionQuery
    except Exception:
        pass
    try:
        if lyr.supports("TRANSPARENCY") and lyr.transparency:
            info["transparency"] = lyr.transparency
    except Exception:
        pass
    if lyr.isFeatureLayer:
        try:
            info["geometry_type"] = arcpy.Describe(lyr).shapeType
        except Exception:
            pass
    return info


def data_fields(dataset, include_geometry=False):
    """Fields safe to put in a cursor (geometry/blob/raster excluded by default)."""
    skip = {"Geometry", "Blob", "Raster"}
    if include_geometry:
        skip.discard("Geometry")
    return [f for f in arcpy.ListFields(dataset) if f.type not in skip]


def oid_field(dataset):
    try:
        return arcpy.Describe(dataset).OIDFieldName
    except Exception:
        return "OBJECTID"


def spatial_reference_from(value):
    """Accept an EPSG/WKID int, a WKT string, or a well-known name."""
    if value in (None, ""):
        return None
    if isinstance(value, arcpy.SpatialReference):
        return value
    try:
        return arcpy.SpatialReference(int(value))
    except (TypeError, ValueError):
        pass
    return arcpy.SpatialReference(str(value))


def color_dict(color, default_alpha=100):
    """Accept [r, g, b], [r, g, b, a] or a {"RGB": [...]} dict."""
    if color is None:
        return None
    if isinstance(color, dict):
        return color
    rgba = [int(c) for c in color]
    while len(rgba) < 4:
        rgba.append(default_alpha)
    return {"RGB": rgba[:4]}


def truncate_list(items, limit=MAX_LIST_ITEMS):
    items = list(items)
    if len(items) <= limit:
        return items, False
    return items[:limit], True


def gp_messages(result):
    try:
        return result.getMessages()
    except Exception:
        return None
