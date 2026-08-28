# -*- coding: utf-8 -*-
"""Data discovery: browse workspaces and folders, describe any dataset."""

import os

import arcpy

from .common import (MAX_LIST_ITEMS, extent_dict, field_dict, project,
                     resolve_path, spatial_reference_dict, truncate_list)
from .registry import command

GROUP = "catalog"

DATA_EXTENSIONS = (".shp", ".gdb", ".tif", ".tiff", ".img", ".lyrx", ".gpkg",
                   ".csv", ".xlsx", ".kml", ".kmz", ".geojson", ".json", ".dwg",
                   ".sde", ".aprx", ".jpg", ".png", ".mdb", ".nc", ".las", ".zip")


@command("list_workspace_contents", GROUP)
def list_workspace_contents(params):
    """List datasets inside a geodatabase or folder workspace.

    Defaults to the project's default geodatabase.
    """
    proj = project()
    workspace = resolve_path(params.get("workspace") or proj.defaultGeodatabase, proj)
    if not arcpy.Exists(workspace):
        raise ValueError("Workspace does not exist: {}".format(workspace))

    previous = arcpy.env.workspace
    arcpy.env.workspace = workspace
    try:
        wildcard = params.get("wildcard") or None
        feature_classes = list(arcpy.ListFeatureClasses(wildcard) or [])
        tables = list(arcpy.ListTables(wildcard) or [])
        rasters = list(arcpy.ListRasters(wildcard) or [])
        datasets = list(arcpy.ListDatasets(wildcard) or [])
        # Feature classes inside feature datasets are not returned at the root.
        nested = []
        for dataset in datasets:
            for fc in (arcpy.ListFeatureClasses("*", "", dataset) or []):
                nested.append("{}\\{}".format(dataset, fc))
    finally:
        arcpy.env.workspace = previous

    limit = int(params.get("limit", MAX_LIST_ITEMS) or MAX_LIST_ITEMS)
    result = {"workspace": workspace}
    for key, values in (("feature_classes", feature_classes + nested),
                        ("tables", tables), ("rasters", rasters),
                        ("feature_datasets", datasets)):
        items, truncated = truncate_list(sorted(values), limit)
        result[key] = items
        if truncated:
            result[key + "_truncated"] = True
    result["total"] = (len(feature_classes) + len(nested) + len(tables)
                       + len(rasters))
    if params.get("include_details") and result["feature_classes"]:
        details = []
        for name in result["feature_classes"][:50]:
            path = os.path.join(workspace, name)
            try:
                desc = arcpy.Describe(path)
                details.append({
                    "name": name,
                    "type": desc.dataType,
                    "shape_type": getattr(desc, "shapeType", None),
                    "spatial_reference": getattr(
                        getattr(desc, "spatialReference", None), "name", None),
                    "count": int(arcpy.management.GetCount(path)[0]),
                })
            except Exception as exc:
                details.append({"name": name, "error": str(exc)})
        result["details"] = details
    return result


@command("list_folder", GROUP)
def list_folder(params):
    """List GIS files and subfolders on disk (defaults to the project home folder)."""
    proj = project()
    folder = resolve_path(params.get("folder") or proj.homeFolder, proj)
    if not os.path.isdir(folder):
        raise ValueError("Folder does not exist: {}".format(folder))
    recursive = bool(params.get("recursive", False))
    pattern = (params.get("pattern") or "").lower()
    only_data = params.get("only_data", True)
    limit = int(params.get("limit", MAX_LIST_ITEMS) or MAX_LIST_ITEMS)

    files, folders = [], []
    if recursive:
        for root, dirnames, filenames in os.walk(folder):
            for name in dirnames:
                folders.append(os.path.join(root, name))
            for name in filenames:
                files.append(os.path.join(root, name))
            if len(files) > limit * 4:
                break
    else:
        for name in sorted(os.listdir(folder)):
            full = os.path.join(folder, name)
            (folders if os.path.isdir(full) else files).append(full)

    def keep(path):
        name = os.path.basename(path).lower()
        if pattern and pattern not in name:
            return False
        if only_data and not name.endswith(DATA_EXTENSIONS):
            return False
        return True

    kept_files, files_truncated = truncate_list([f for f in files if keep(f)], limit)
    kept_folders, _ = truncate_list(
        [f for f in folders if not pattern or pattern in os.path.basename(f).lower()],
        limit)
    return {"folder": folder, "files": kept_files, "folders": kept_folders,
            "files_truncated": files_truncated}


@command("describe_dataset", GROUP)
def describe_dataset(params):
    """Describe any dataset by path without adding it to a map."""
    path = resolve_path(params["path"])
    if not arcpy.Exists(path):
        raise ValueError("Dataset does not exist: {}".format(path))
    desc = arcpy.Describe(path)
    info = {"path": path, "name": desc.name, "data_type": desc.dataType}
    for attr in ("shapeType", "featureType", "hasZ", "hasM", "OIDFieldName",
                 "shapeFieldName", "datasetType", "bandCount", "format"):
        if hasattr(desc, attr):
            try:
                info[attr] = getattr(desc, attr)
            except Exception:
                continue
    try:
        info["spatial_reference"] = spatial_reference_dict(desc.spatialReference)
    except Exception:
        pass
    try:
        info["extent"] = extent_dict(desc.extent)
    except Exception:
        pass
    try:
        info["fields"] = [field_dict(f) for f in arcpy.ListFields(path)]
    except Exception:
        pass
    try:
        if desc.dataType in ("FeatureClass", "Table", "ShapeFile", "FeatureLayer"):
            info["row_count"] = int(arcpy.management.GetCount(path)[0])
    except Exception:
        pass
    return info


@command("search_data", GROUP)
def search_data(params):
    """Find datasets by name across the project's geodatabase, home folder and
    folder connections -- the fastest way to locate data before adding it."""
    proj = project()
    needle = (params.get("name") or "").lower()
    limit = int(params.get("limit", 100) or 100)
    roots = []
    if params.get("workspaces"):
        roots = [resolve_path(w, proj) for w in params["workspaces"]]
    else:
        if proj.defaultGeodatabase:
            roots.append(proj.defaultGeodatabase)
        if proj.homeFolder:
            roots.append(proj.homeFolder)
        try:
            roots.extend(f.connectionString for f in proj.folderConnections)
        except Exception:
            pass

    matches = []
    seen = set()
    max_roots = int(params.get("max_workspaces", 40) or 40)
    for root in roots:
        if len(seen) >= max_roots:
            break
        if not root or root in seen or not arcpy.Exists(root):
            continue
        seen.add(root)
        previous = arcpy.env.workspace
        arcpy.env.workspace = root
        try:
            for kind, lister in (("feature_class", arcpy.ListFeatureClasses),
                                 ("table", arcpy.ListTables),
                                 ("raster", arcpy.ListRasters)):
                for name in (lister() or []):
                    if needle and needle not in name.lower():
                        continue
                    matches.append({"name": name, "type": kind,
                                    "path": os.path.join(root, name),
                                    "workspace": root})
                    if len(matches) >= limit:
                        break
            for gdb_name in (arcpy.ListWorkspaces("*", "FileGDB") or []):
                if gdb_name in seen:
                    continue
                roots.append(gdb_name)
        except Exception:
            pass
        finally:
            arcpy.env.workspace = previous
        if len(matches) >= limit:
            break
    return {"query": params.get("name"), "match_count": len(matches),
            "matches": matches[:limit], "searched": sorted(seen)}


@command("get_project_items", GROUP)
def get_project_items(params):
    """Folder connections, database connections and toolboxes registered in the project."""
    proj = project()
    data = {}
    try:
        data["folders"] = [f.connectionString for f in proj.folderConnections]
    except Exception:
        data["folders"] = []
    try:
        data["databases"] = [
            {"name": d.get("alias") or d.get("databaseConnection"),
             "connection": d.get("databaseConnection") or d.get("connectionString")}
            for d in proj.databases
        ]
    except Exception:
        data["databases"] = []
    try:
        data["toolboxes"] = list(proj.listToolboxes())
    except Exception:
        data["toolboxes"] = []
    data["default_geodatabase"] = proj.defaultGeodatabase
    data["home_folder"] = proj.homeFolder
    return data


@command("add_folder_connection", GROUP)
def add_folder_connection(params):
    """Register a folder with the project so its data is easy to browse."""
    proj = project()
    folder = resolve_path(params["folder"], proj)
    if not os.path.isdir(folder):
        raise ValueError("Folder does not exist: {}".format(folder))
    proj.folderConnections = list(proj.folderConnections) + [
        {"connectionString": folder, "alias": params.get("alias") or
         os.path.basename(folder), "isHomeFolder": False}
    ]
    return {"added_folder": folder}
