# -*- coding: utf-8 -*-
"""Session, project, map and environment commands."""

import os

import arcpy

from .common import (extent_dict, get_map, project, resolve_path,
                     spatial_reference_dict, spatial_reference_from)
from .registry import HANDLERS, command, describe_commands

GROUP = "project"


@command("ping", GROUP)
def ping(params):
    """Check that the bridge is alive and which project it is attached to."""
    proj = None
    try:
        proj = project().filePath
    except Exception:
        pass
    from . import pump
    return {"pong": True, "project_path": proj, "pid": os.getpid(),
            "main_thread_pump_running": pump.is_running(),
            "command_count": len(HANDLERS)}


@command("get_capabilities", GROUP)
def get_capabilities(params):
    """List every command this bridge supports, grouped by area."""
    groups = describe_commands()
    total = sum(len(v) for v in groups.values())
    return {"command_count": total, "groups": groups}


@command("get_arcgis_info", GROUP)
def get_arcgis_info(params):
    """ArcGIS Pro version, license level, extensions and current project."""
    install = arcpy.GetInstallInfo()
    info = {
        "product": install.get("ProductName"),
        "version": install.get("Version"),
        "build": install.get("BuildNumber"),
        "install_dir": install.get("InstallDir"),
        "license": arcpy.ProductInfo(),
    }
    try:
        proj = project()
        info["project_path"] = proj.filePath
        info["default_geodatabase"] = proj.defaultGeodatabase
    except Exception as exc:
        info["project_error"] = str(exc)
    extensions = {}
    for ext in ("Spatial", "3D", "Network", "GeoStats", "ImageAnalyst",
                "DataInteroperability", "Datareviewer", "Workflow"):
        try:
            extensions[ext] = arcpy.CheckExtension(ext)
        except Exception:
            extensions[ext] = "Unavailable"
    info["extensions"] = extensions
    return info


@command("get_project_info", GROUP)
def get_project_info(params):
    """Project paths, default geodatabase/toolbox, maps, layouts and folders."""
    proj = project()
    maps = []
    for m in proj.listMaps():
        maps.append({
            "name": m.name,
            "map_type": getattr(m, "mapType", None),
            "layer_count": len(m.listLayers()),
            "table_count": len(m.listTables()),
            "spatial_reference": m.spatialReference.name if m.spatialReference else None,
        })
    data = {
        "path": proj.filePath,
        "home_folder": proj.homeFolder,
        "default_geodatabase": proj.defaultGeodatabase,
        "default_toolbox": proj.defaultToolbox,
        "maps": maps,
        "layouts": [l.name for l in proj.listLayouts()],
    }
    try:
        data["folders"] = [f.connectionString for f in proj.folderConnections]
    except Exception:
        pass
    try:
        data["databases"] = [d.get("databaseConnection") or d.get("connectionString")
                             for d in proj.databases]
    except Exception:
        pass
    try:
        data["toolboxes"] = list(proj.listToolboxes())
    except Exception:
        pass
    try:
        data["active_map"] = proj.activeMap.name if proj.activeMap else None
    except Exception:
        data["active_map"] = None
    return data


@command("save_project", GROUP)
def save_project(params):
    """Save the project, optionally as a copy at save_as_path."""
    proj = project()
    save_as = params.get("save_as_path")
    if save_as:
        target = resolve_path(save_as, proj)
        proj.saveACopy(target)
        return {"saved_copy": target, "original": proj.filePath}
    proj.save()
    return {"saved": proj.filePath}


@command("list_maps", GROUP)
def list_maps(params):
    """List all maps/scenes with CRS and layer counts."""
    proj = project()
    result = []
    for m in proj.listMaps():
        result.append({
            "name": m.name,
            "map_type": getattr(m, "mapType", None),
            "spatial_reference": spatial_reference_dict(m.spatialReference),
            "layer_count": len(m.listLayers()),
            "table_count": len(m.listTables()),
            "bookmark_count": len(m.listBookmarks()),
        })
    return result


@command("create_map", GROUP)
def create_map(params):
    """Create a new map or scene."""
    proj = project()
    new_map = proj.createMap(params["name"], params.get("map_type", "MAP"))
    epsg = params.get("epsg")
    if epsg:
        new_map.spatialReference = spatial_reference_from(epsg)
    if params.get("basemap"):
        try:
            new_map.addBasemap(params["basemap"])
        except Exception as exc:
            return {"created": new_map.name, "basemap_warning": str(exc)}
    return {"created": new_map.name, "map_type": params.get("map_type", "MAP")}


@command("remove_map", GROUP)
def remove_map(params):
    """Delete a map from the project."""
    proj = project()
    maps = proj.listMaps(params["map_name"])
    if not maps:
        raise ValueError("Map not found: {}".format(params["map_name"]))
    proj.deleteItem(maps[0])
    return {"removed": params["map_name"]}


@command("activate_map", GROUP)
def activate_map(params):
    """Open/activate a map's view in the ArcGIS Pro UI (Pro 3.x)."""
    m = get_map(map_name=params["map_name"])
    try:
        m.openView()
    except AttributeError:
        raise RuntimeError(
            "Map.openView() needs ArcGIS Pro 3.0+. Pass map_name explicitly instead."
        )
    return {"activated": m.name}


@command("set_map_properties", GROUP)
def set_map_properties(params):
    """Rename a map or change its coordinate system."""
    m = get_map(map_name=params.get("map_name"))
    changed = {}
    if params.get("new_name"):
        m.name = params["new_name"]
        changed["name"] = m.name
    if params.get("epsg"):
        m.spatialReference = spatial_reference_from(params["epsg"])
        changed["spatial_reference"] = m.spatialReference.name
    return {"map": m.name, "changed": changed}


# --- geoprocessing environment ------------------------------------------------

_ENV_KEYS = (
    "workspace", "scratchWorkspace", "outputCoordinateSystem", "extent",
    "overwriteOutput", "parallelProcessingFactor", "snapRaster", "mask",
    "cellSize", "XYResolution", "XYTolerance", "qualifiedFieldNames",
    "addOutputsToMap", "geographicTransformations", "nodata", "compression",
    "pyramid", "resamplingMethod",
)


@command("get_environment", GROUP)
def get_environment(params):
    """Read the current arcpy geoprocessing environment settings."""
    out = {}
    for key in _ENV_KEYS:
        try:
            value = getattr(arcpy.env, key)
        except Exception:
            continue
        out[key] = str(value) if value is not None else None
    return out


@command("set_environment", GROUP)
def set_environment(params):
    """Set arcpy geoprocessing environment settings, e.g. {"workspace": "..."}.

    Pass null for a setting to reset it.
    """
    settings = params.get("settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object of environment name/value pairs")
    applied, unknown = {}, []
    for key, value in settings.items():
        if not hasattr(arcpy.env, key):
            unknown.append(key)
            continue
        if key == "outputCoordinateSystem" and value not in (None, ""):
            value = spatial_reference_from(value)
        setattr(arcpy.env, key, value)
        applied[key] = str(getattr(arcpy.env, key))
    result = {"applied": applied}
    if unknown:
        result["unknown_settings"] = unknown
    return result


@command("get_map_extent", GROUP)
def get_map_extent(params):
    """The map's full extent (union of its layers)."""
    m = get_map(map_name=params.get("map_name"))
    extents = []
    for lyr in m.listLayers():
        if lyr.isGroupLayer or lyr.isBasemapLayer:
            continue
        try:
            extents.append(arcpy.Describe(lyr).extent)
        except Exception:
            continue
    if not extents:
        return {"map": m.name, "extent": None}
    total = extents[0]
    for ext in extents[1:]:
        total = total.union(ext)
    return {"map": m.name, "extent": extent_dict(total)}
