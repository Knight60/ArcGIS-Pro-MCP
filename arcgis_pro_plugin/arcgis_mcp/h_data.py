# -*- coding: utf-8 -*-
"""Attribute data: read, summarise and edit features."""

import contextlib

import arcpy

from .common import (MAX_FEATURES, data_fields, oid_field, resolve_target,
                     spatial_reference_from, target_name, truncate_list)
from .registry import command

GROUP = "data"


def _workspace_of(target):
    """The workspace holding a layer's data, or None if it can't be determined."""
    try:
        path = arcpy.Describe(target).path
    except Exception:
        return None
    return path if path and arcpy.Exists(path) else None


@contextlib.contextmanager
def _edit_session(target, use_session=True):
    """Wrap edits in an edit session when the workspace requires one."""
    workspace = _workspace_of(target) if use_session else None
    editor = None
    if workspace:
        try:
            editor = arcpy.da.Editor(workspace)
            editor.startEditing(False, False)
            editor.startOperation()
        except Exception:
            editor = None
    try:
        yield
    except Exception:
        if editor is not None:
            try:
                editor.abortOperation()
                editor.stopEditing(False)
            except Exception:
                pass
            editor = None
        raise
    finally:
        if editor is not None:
            try:
                editor.stopOperation()
                editor.stopEditing(True)
            except Exception:
                pass


@command("get_features", GROUP)
def get_features(params):
    """Read rows from a layer, table, or dataset path.

    Supports a where clause, field subset, ordering, offset and WKT geometry.
    """
    target, _m = resolve_target(params)
    where = params.get("where") or None
    limit = min(int(params.get("limit", 50)), MAX_FEATURES)
    offset = int(params.get("offset", 0) or 0)
    include_geometry = bool(params.get("include_geometry", False))

    fields = params.get("fields")
    if not fields:
        fields = [f.name for f in data_fields(target)]
    cursor_fields = list(fields)
    if include_geometry:
        cursor_fields.append("SHAPE@WKT")

    sql_clause = (None, None)
    order_by = params.get("order_by")
    if order_by:
        sql_clause = (None, "ORDER BY {}".format(order_by))

    rows = []
    with arcpy.da.SearchCursor(target, cursor_fields, where_clause=where,
                               sql_clause=sql_clause) as cursor:
        for i, row in enumerate(cursor):
            if i < offset:
                continue
            if len(rows) >= limit:
                break
            rows.append(dict(zip(cursor_fields, row)))
    return {
        "layer": target_name(target),
        "fields": cursor_fields,
        "count": len(rows),
        "offset": offset,
        "limit": limit,
        "features": rows,
    }


@command("count_features", GROUP)
def count_features(params):
    """Count features, optionally matching a where clause."""
    target, _m = resolve_target(params)
    where = params.get("where")
    if not where:
        return {"layer": target_name(target),
                "count": int(arcpy.management.GetCount(target)[0])}
    count = 0
    with arcpy.da.SearchCursor(target, [oid_field(target)], where_clause=where) as cur:
        for _row in cur:
            count += 1
    return {"layer": target_name(target), "where": where, "count": count}


@command("get_unique_values", GROUP)
def get_unique_values(params):
    """Distinct values of a field, with counts."""
    target, _m = resolve_target(params)
    field = params["field"]
    limit = min(int(params.get("limit", 200)), MAX_FEATURES)
    where = params.get("where") or None
    counts = {}
    with arcpy.da.SearchCursor(target, [field], where_clause=where) as cursor:
        for row in cursor:
            counts[row[0]] = counts.get(row[0], 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (kv[0] is None, str(kv[0])))
    values, truncated = truncate_list(ordered, limit)
    return {
        "layer": target_name(target),
        "field": field,
        "distinct_count": len(counts),
        "values": [{"value": v, "count": c} for v, c in values],
        "truncated": truncated,
    }


@command("get_field_statistics", GROUP)
def get_field_statistics(params):
    """min / max / mean / sum / std / median of a numeric field."""
    target, _m = resolve_target(params)
    field = params["field"]
    where = params.get("where") or None
    values, null_count = [], 0
    with arcpy.da.SearchCursor(target, [field], where_clause=where) as cursor:
        for row in cursor:
            if row[0] is None:
                null_count += 1
            else:
                values.append(row[0])
    stats = {
        "layer": target_name(target), "field": field,
        "count": len(values), "null_count": null_count,
    }
    numeric = [v for v in values if isinstance(v, (int, float))
               and not isinstance(v, bool)]
    if numeric:
        n = len(numeric)
        mean = sum(numeric) / n
        variance = sum((v - mean) ** 2 for v in numeric) / n
        ordered = sorted(numeric)
        median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
        stats.update({
            "min": min(numeric), "max": max(numeric), "sum": sum(numeric),
            "mean": mean, "median": median, "std_dev": variance ** 0.5,
        })
    return stats


@command("summarize_features", GROUP)
def summarize_features(params):
    """Group rows by one or more fields and aggregate (count/sum/mean/min/max).

    Answers "how many / how much per category" without a geoprocessing round trip.
    """
    target, _m = resolve_target(params)
    group_fields = params.get("group_by")
    if isinstance(group_fields, str):
        group_fields = [group_fields]
    if not group_fields:
        raise ValueError("group_by is required (field name or list of field names)")
    value_field = params.get("value_field")
    where = params.get("where") or None
    limit = min(int(params.get("limit", 200)), MAX_FEATURES)

    cursor_fields = list(group_fields) + ([value_field] if value_field else [])
    buckets = {}
    with arcpy.da.SearchCursor(target, cursor_fields, where_clause=where) as cursor:
        for row in cursor:
            key = tuple(row[:len(group_fields)])
            bucket = buckets.setdefault(key, {"count": 0, "values": []})
            bucket["count"] += 1
            if value_field and row[-1] is not None:
                bucket["values"].append(row[-1])

    results = []
    for key, bucket in buckets.items():
        entry = dict(zip(group_fields, key))
        entry["count"] = bucket["count"]
        nums = [v for v in bucket["values"] if isinstance(v, (int, float))
                and not isinstance(v, bool)]
        if nums:
            entry["sum"] = sum(nums)
            entry["mean"] = sum(nums) / len(nums)
            entry["min"] = min(nums)
            entry["max"] = max(nums)
        results.append(entry)
    results.sort(key=lambda e: e.get("sum", e["count"]), reverse=True)
    rows, truncated = truncate_list(results, limit)
    return {
        "layer": target_name(target),
        "group_by": group_fields,
        "value_field": value_field,
        "group_count": len(results),
        "groups": rows,
        "truncated": truncated,
    }


def _geometry_from(value, spatial_reference=None):
    """Accept WKT, WKB-free GeoJSON-ish dict, or [x, y] for points."""
    if value is None:
        return None
    sr = spatial_reference_from(spatial_reference) if spatial_reference else None
    if isinstance(value, str):
        geom = arcpy.FromWKT(value, sr) if sr else arcpy.FromWKT(value)
        return geom
    if isinstance(value, dict):
        return arcpy.AsShape(value, True)
    if isinstance(value, (list, tuple)) and len(value) >= 2 \
            and isinstance(value[0], (int, float)):
        return arcpy.PointGeometry(arcpy.Point(value[0], value[1]), sr)
    raise ValueError("Unsupported geometry value: {}".format(type(value).__name__))


@command("insert_features", GROUP)
def insert_features(params):
    """Insert new rows. Each feature is {"attributes": {...}, "geometry": WKT}."""
    target, _m = resolve_target(params)
    features = params.get("features") or []
    if not features:
        raise ValueError("features is required (list of {attributes, geometry})")
    sr = params.get("geometry_spatial_reference")

    attr_names = []
    for feat in features:
        for key in (feat.get("attributes") or {}):
            if key not in attr_names:
                attr_names.append(key)
    has_geometry = any(f.get("geometry") is not None for f in features)
    cursor_fields = list(attr_names) + (["SHAPE@"] if has_geometry else [])
    if not cursor_fields:
        raise ValueError("Each feature needs attributes and/or geometry")

    inserted = 0
    with _edit_session(target, params.get("use_edit_session", True)):
        with arcpy.da.InsertCursor(target, cursor_fields) as cursor:
            for feat in features:
                attrs = feat.get("attributes") or {}
                row = [attrs.get(name) for name in attr_names]
                if has_geometry:
                    row.append(_geometry_from(feat.get("geometry"), sr))
                cursor.insertRow(row)
                inserted += 1
    return {"layer": target_name(target), "inserted": inserted,
            "fields": cursor_fields}


@command("update_features", GROUP)
def update_features(params):
    """Update attributes (and optionally geometry) of rows matching a where clause."""
    target, _m = resolve_target(params)
    updates = params.get("attributes") or {}
    geometry = params.get("geometry")
    where = params.get("where") or None
    if not updates and geometry is None:
        raise ValueError("Provide attributes and/or geometry to update")
    if not where and not params.get("allow_update_all"):
        raise ValueError(
            "Refusing to update every row: pass a where clause, or set "
            "allow_update_all=true to confirm."
        )
    limit = int(params.get("limit", 0) or 0)
    sr = params.get("geometry_spatial_reference")

    names = list(updates.keys())
    cursor_fields = list(names) + (["SHAPE@"] if geometry is not None else [])
    updated = 0
    with _edit_session(target, params.get("use_edit_session", True)):
        with arcpy.da.UpdateCursor(target, cursor_fields, where_clause=where) as cursor:
            for row in cursor:
                new_row = [updates[name] for name in names]
                if geometry is not None:
                    new_row.append(_geometry_from(geometry, sr))
                cursor.updateRow(new_row)
                updated += 1
                if limit and updated >= limit:
                    break
    return {"layer": target_name(target), "updated": updated, "where": where}


@command("delete_features", GROUP)
def delete_features(params):
    """Delete rows matching a where clause (or the current selection)."""
    target, _m = resolve_target(params)
    where = params.get("where") or None
    if not where and not params.get("allow_delete_all"):
        raise ValueError(
            "Refusing to delete every row: pass a where clause, or set "
            "allow_delete_all=true to confirm."
        )
    deleted = 0
    with _edit_session(target, params.get("use_edit_session", True)):
        with arcpy.da.UpdateCursor(target, [oid_field(target)],
                                   where_clause=where) as cursor:
            for _row in cursor:
                cursor.deleteRow()
                deleted += 1
    return {"layer": target_name(target), "deleted": deleted, "where": where}


@command("calculate_field", GROUP)
def calculate_field(params):
    """Calculate field values, e.g. expression "!AREA! / 10000"."""
    target, _m = resolve_target(params)
    result = arcpy.management.CalculateField(
        target,
        params["field_name"],
        params["expression"],
        params.get("expression_type", "PYTHON3"),
        params.get("code_block"),
    )
    return {"layer": target_name(target),
            "calculated_field": params["field_name"],
            "messages": result.getMessages()}


@command("save_edits", GROUP)
def save_edits(params):
    """Commit pending edits.

    arcpy commits as each edit session closes, so there is normally nothing
    pending here; the command exists so the same call works against either
    implementation.
    """
    return {"saved": False,
            "message": "arcpy commits edits as it makes them; nothing was pending."}


@command("discard_edits", GROUP)
def discard_edits(params):
    """Throw away pending edits (arcpy has already committed them)."""
    return {"discarded": False,
            "message": "arcpy commits edits as it makes them; nothing to discard."}
