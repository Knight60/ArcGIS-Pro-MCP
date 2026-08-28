# -*- coding: utf-8 -*-
"""Schema and dataset creation."""

import os

import arcpy

from .common import (add_layer_once, field_dict, get_map, project,
                     resolve_path, resolve_target, spatial_reference_from,
                     target_name)
from .registry import command

GROUP = "schema"


@command("list_fields", GROUP)
def list_fields(params):
    """List a layer's or dataset's fields with type, alias, length and domain."""
    target, _m = resolve_target(params)
    wildcard = params.get("wildcard") or None
    fields = arcpy.ListFields(target, wildcard) if wildcard else arcpy.ListFields(target)
    return {"layer": target_name(target),
            "fields": [field_dict(f) for f in fields]}


@command("add_field", GROUP)
def add_field(params):
    """Add one field to a layer or table."""
    target, _m = resolve_target(params)
    arcpy.management.AddField(
        target,
        params["field_name"],
        params.get("field_type", "TEXT"),
        field_precision=params.get("field_precision"),
        field_scale=params.get("field_scale"),
        field_length=params.get("field_length"),
        field_alias=params.get("field_alias"),
        field_is_nullable=params.get("nullable", "NULLABLE"),
        field_domain=params.get("field_domain"),
    )
    return {"layer": target_name(target), "added_field": params["field_name"]}


@command("add_fields", GROUP)
def add_fields(params):
    """Add several fields at once.

    fields: [{"name": "AREA_HA", "type": "DOUBLE", "alias": "Area (ha)"}, ...]
    """
    target, _m = resolve_target(params)
    specs = params.get("fields") or []
    if not specs:
        raise ValueError("fields is required (list of field definitions)")
    added = []
    for spec in specs:
        arcpy.management.AddField(
            target, spec["name"], spec.get("type", "TEXT"),
            field_length=spec.get("length"),
            field_alias=spec.get("alias"),
        )
        added.append(spec["name"])
    return {"layer": target_name(target), "added_fields": added}


@command("delete_field", GROUP)
def delete_field(params):
    """Delete one or more fields."""
    target, _m = resolve_target(params)
    names = params.get("field_names") or [params["field_name"]]
    arcpy.management.DeleteField(target, names)
    return {"layer": target_name(target), "deleted_fields": names}


@command("alter_field", GROUP)
def alter_field(params):
    """Rename a field or change its alias / length."""
    target, _m = resolve_target(params)
    arcpy.management.AlterField(
        target,
        params["field_name"],
        new_field_name=params.get("new_name"),
        new_field_alias=params.get("new_alias"),
        field_length=params.get("field_length"),
    )
    return {"layer": target_name(target), "altered_field": params["field_name"],
            "new_name": params.get("new_name")}


@command("create_feature_class", GROUP)
def create_feature_class(params):
    """Create an empty feature class (default: the project's default geodatabase)."""
    proj = project()
    out_path = resolve_path(params.get("out_path") or proj.defaultGeodatabase, proj)
    geometry_type = params.get("geometry_type", "POLYGON")
    sr = spatial_reference_from(params.get("epsg"))
    result = arcpy.management.CreateFeatureclass(
        out_path, params["name"], geometry_type,
        template=params.get("template"),
        has_m=params.get("has_m", "DISABLED"),
        has_z=params.get("has_z", "DISABLED"),
        spatial_reference=sr,
    )
    fc_path = str(result)
    for spec in params.get("fields") or []:
        arcpy.management.AddField(fc_path, spec["name"], spec.get("type", "TEXT"),
                                  field_length=spec.get("length"),
                                  field_alias=spec.get("alias"))
    added = None
    if params.get("add_to_map", True):
        added = add_layer_once(get_map(proj, params.get("map_name")), fc_path)[0].name
    return {"created": fc_path, "geometry_type": geometry_type,
            "added_to_map": added}


@command("create_table", GROUP)
def create_table(params):
    """Create an empty standalone table."""
    proj = project()
    out_path = resolve_path(params.get("out_path") or proj.defaultGeodatabase, proj)
    result = arcpy.management.CreateTable(out_path, params["name"],
                                          template=params.get("template"))
    table_path = str(result)
    for spec in params.get("fields") or []:
        arcpy.management.AddField(table_path, spec["name"], spec.get("type", "TEXT"),
                                  field_length=spec.get("length"),
                                  field_alias=spec.get("alias"))
    added = None
    if params.get("add_to_map", True):
        added = add_layer_once(get_map(proj, params.get("map_name")),
                               table_path)[0].name
    return {"created": table_path, "added_to_map": added}


@command("create_file_geodatabase", GROUP)
def create_file_geodatabase(params):
    """Create a new file geodatabase (.gdb)."""
    proj = project()
    folder = resolve_path(params.get("folder") or proj.homeFolder, proj)
    name = params["name"]
    if not name.lower().endswith(".gdb"):
        name += ".gdb"
    result = arcpy.management.CreateFileGDB(folder, name)
    return {"created": str(result)}


@command("delete_dataset", GROUP)
def delete_dataset(params):
    """Delete a dataset on disk / in a geodatabase (irreversible)."""
    path = resolve_path(params["path"])
    if not arcpy.Exists(path):
        raise ValueError("Dataset does not exist: {}".format(path))
    arcpy.management.Delete(path)
    return {"deleted": path}


@command("truncate_table", GROUP)
def truncate_table(params):
    """Remove every row from a table or feature class, keeping the schema."""
    target, _m = resolve_target(params)
    arcpy.management.TruncateTable(target)
    return {"layer": target_name(target), "truncated": True}


@command("export_features", GROUP)
def export_features(params):
    """Export a layer (honouring its selection and definition query) to a new dataset."""
    target, _m = resolve_target(params)
    proj = project()
    out_path = resolve_path(params["out_path"], proj)
    out_dir, out_name = os.path.split(out_path)
    result = arcpy.conversion.ExportFeatures(
        target, out_path, where_clause=params.get("where") or "",
    ) if hasattr(arcpy.conversion, "ExportFeatures") else \
        arcpy.conversion.FeatureClassToFeatureClass(
            target, out_dir, out_name, where_clause=params.get("where") or "")
    exported = str(result)
    added = None
    if params.get("add_to_map", True):
        added = add_layer_once(get_map(proj, params.get("map_name")),
                               exported)[0].name
    return {"source": target_name(target), "exported": exported,
            "added_to_map": added}
