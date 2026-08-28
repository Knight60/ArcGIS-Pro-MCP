# -*- coding: utf-8 -*-
"""Geoprocessing: run any arcpy tool, discover tools and their parameters."""

import arcpy

from .common import (MAX_LIST_ITEMS, add_layer_once, find_layer_or_table,
                     get_map, looks_like_path, project, resolve_path,
                     truncate_list)
from .registry import command

GROUP = "geoprocessing"


def _resolve_tool(tool_name):
    """Accept "analysis.Buffer", "arcpy.analysis.Buffer" or "Buffer_analysis"."""
    name = tool_name.strip()
    if name.startswith("arcpy."):
        name = name[6:]
    if "." in name:
        module_name, func_name = name.split(".", 1)
        module = getattr(arcpy, module_name, None)
        if module is None:
            raise ValueError(
                "Unknown arcpy module '{}'. Use e.g. analysis, management, "
                "conversion, sa, ia, cartography, da, na, stats.".format(module_name)
            )
        tool = getattr(module, func_name, None)
        if tool is None:
            raise ValueError(
                "Tool '{}' not found in arcpy.{}. Use list_geoprocessing_tools "
                "to search.".format(func_name, module_name)
            )
        return tool
    tool = getattr(arcpy, name, None)
    if tool is None:
        raise ValueError(
            "Tool '{}' not found. Use the toolbox-qualified name such as "
            "'analysis.Buffer' or 'Buffer_analysis'.".format(name)
        )
    return tool


def _resolve_value(value, map_obj):
    """Turn a layer name into the live layer object so selections are honoured."""
    if not isinstance(value, str) or map_obj is None:
        return value
    if looks_like_path(value):
        return value
    try:
        return find_layer_or_table(map_obj, value)
    except ValueError:
        return value


@command("run_geoprocessing_tool", GROUP)
def run_geoprocessing_tool(params):
    """Run any arcpy geoprocessing tool by name.

    Layer names from the active map are resolved to live layers, so current
    selections and definition queries apply.
    """
    tool_name = params["tool_name"]
    tool = _resolve_tool(tool_name)

    try:
        map_obj = get_map(map_name=params.get("map_name"))
    except Exception:
        map_obj = None

    kwargs = {k: _resolve_value(v, map_obj)
              for k, v in (params.get("parameters") or {}).items()}
    args = [_resolve_value(v, map_obj) for v in (params.get("args") or [])]

    extension = params.get("checkout_extension")
    if extension:
        status = arcpy.CheckOutExtension(extension)
        if status != "CheckedOut":
            raise RuntimeError(
                "Could not check out the {} extension: {}".format(extension, status)
            )
    previous_overwrite = arcpy.env.overwriteOutput
    if params.get("overwrite") is not None:
        arcpy.env.overwriteOutput = bool(params["overwrite"])
    try:
        result = tool(*args, **kwargs)
    finally:
        arcpy.env.overwriteOutput = previous_overwrite
        if extension:
            try:
                arcpy.CheckInExtension(extension)
            except Exception:
                pass

    data = {"tool": tool_name}
    outputs = []
    if hasattr(result, "getMessages"):
        data["messages"] = result.getMessages()
        try:
            outputs = [str(result.getOutput(i)) for i in range(result.outputCount)]
        except Exception:
            outputs = []
        data["outputs"] = outputs
    else:
        data["result"] = str(result)
        outputs = [str(result)]

    if params.get("add_to_map") and outputs and map_obj is not None:
        added, already = [], []
        for out in outputs:
            try:
                if not arcpy.Exists(out):
                    continue
                layer, was_added = add_layer_once(map_obj, out)
                (added if was_added else already).append(layer.name)
            except Exception:
                continue
        data["added_to_map"] = added
        if already:
            # ArcGIS Pro had already put these on the map itself.
            data["already_on_map"] = already
    return data


@command("list_geoprocessing_tools", GROUP)
def list_geoprocessing_tools(params):
    """Search available geoprocessing tools, e.g. wildcard "*Buffer*"."""
    wildcard = params.get("wildcard", "*")
    toolbox = params.get("toolbox")
    pattern = "{}_{}".format(wildcard, toolbox) if toolbox else wildcard
    tools = arcpy.ListTools(pattern)
    limit = int(params.get("limit", MAX_LIST_ITEMS) or MAX_LIST_ITEMS)
    items, truncated = truncate_list(sorted(tools), limit)
    return {"pattern": pattern, "count": len(tools),
            "tools": items, "truncated": truncated}


# arcpy exposes each system toolbox as a module; tool names end in "_<alias>".
ARCPY_TOOLBOX_MODULES = (
    "analysis", "cartography", "conversion", "data", "defense", "edit",
    "ga", "intelligence", "management", "md", "nax", "na", "network",
    "oi", "ows", "parcel", "sa", "ia", "server", "stats", "td", "topographic",
    "un", "wmx",
)


@command("list_toolboxes", GROUP)
def list_toolboxes(params):
    """List arcpy toolbox modules (analysis, management, sa, ...) and project toolboxes."""
    available = [name for name in ARCPY_TOOLBOX_MODULES if hasattr(arcpy, name)]
    data = {"arcpy_modules": available}
    try:
        data["project_toolboxes"] = list(project().listToolboxes())
    except Exception:
        pass
    try:
        data["system_toolboxes"] = arcpy.ListToolboxes()[:MAX_LIST_ITEMS]
    except Exception:
        pass
    return data


@command("describe_geoprocessing_tool", GROUP)
def describe_geoprocessing_tool(params):
    """Get a tool's parameters, data types and usage text before running it."""
    tool_name = params["tool_name"]
    lookup = tool_name
    if "." in lookup:
        module_name, func_name = lookup.replace("arcpy.", "").split(".", 1)
        lookup = "{}_{}".format(func_name, module_name)

    data = {"tool": tool_name, "lookup_name": lookup}
    try:
        data["usage"] = arcpy.Usage(lookup)
    except Exception as exc:
        data["usage_error"] = str(exc)
    try:
        info = []
        for p in arcpy.GetParameterInfo(lookup):
            info.append({
                "name": p.name,
                "display_name": p.displayName,
                "direction": p.direction,
                "data_type": p.datatype,
                "parameter_type": p.parameterType,
                "multi_value": p.multiValue,
                "default": str(p.value) if p.value not in (None, "") else None,
                "filter_list": list(p.filter.list) if getattr(p, "filter", None)
                and p.filter.list else None,
            })
        data["parameters"] = info
    except Exception as exc:
        data["parameters_error"] = str(exc)
    try:
        tool = _resolve_tool(tool_name)
        doc = (tool.__doc__ or "").strip()
        if doc:
            data["doc"] = doc[:4000]
    except Exception:
        pass
    return data


@command("check_extension", GROUP)
def check_extension(params):
    """Check or check out an ArcGIS extension license (Spatial, 3D, ImageAnalyst...)."""
    name = params["extension"]
    status = arcpy.CheckExtension(name)
    result = {"extension": name, "status": status}
    if params.get("checkout") and status == "Available":
        result["checkout"] = arcpy.CheckOutExtension(name)
    return result


@command("get_messages", GROUP)
def get_messages(params):
    """Messages from the most recent geoprocessing operation."""
    severity = int(params.get("severity", 0) or 0)
    return {"messages": arcpy.GetMessages(severity)}


@command("run_python_toolbox_tool", GROUP)
def run_python_toolbox_tool(params):
    """Run a tool from a custom .pyt / .atbx / .tbx toolbox on disk."""
    toolbox_path = resolve_path(params["toolbox_path"])
    alias = params.get("alias")
    arcpy.ImportToolbox(toolbox_path, alias)
    tool_name = params["tool_name"]
    tool = getattr(arcpy, tool_name, None)
    if tool is None and alias:
        tool = getattr(getattr(arcpy, alias, arcpy), tool_name, None)
    if tool is None:
        raise ValueError(
            "Tool '{}' not found after importing {}".format(tool_name, toolbox_path)
        )
    result = tool(*(params.get("args") or []), **(params.get("parameters") or {}))
    return {"toolbox": toolbox_path, "tool": tool_name,
            "messages": getattr(result, "getMessages", lambda: str(result))()}
