# -*- coding: utf-8 -*-
"""
ArcGIS Pro MCP Bridge
=====================
Socket server that runs INSIDE ArcGIS Pro's Python runtime and executes
arcpy commands against the currently open project ("CURRENT").

It speaks newline-delimited JSON over TCP (localhost only):

    request : {"id": 1, "command": "get_layers", "params": {...}}\n
    response: {"id": 1, "success": true, "data": {...}}\n
    error   : {"id": 1, "success": false, "error": "message"}\n

Start it from the ArcGISMCP.pyt toolbox, or from the Pro Python window:

    import sys; sys.path.insert(0, r"<this folder>")
    import mcp_bridge; mcp_bridge.start_server()
"""

import builtins
import contextlib
import io
import json
import os
import socket
import threading
import traceback

import arcpy

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6510
_REGISTRY_KEY = "_ARCGIS_MCP_BRIDGE"  # survives .pyt reloads

MAX_FEATURES = 1000
MAX_LIST_ITEMS = 200


# ---------------------------------------------------------------------------
# arcpy helpers
# ---------------------------------------------------------------------------

def _project():
    return arcpy.mp.ArcGISProject("CURRENT")


def _get_map(project=None, map_name=None):
    project = project or _project()
    if map_name:
        maps = project.listMaps(map_name)
        if not maps:
            raise ValueError("Map not found: {}".format(map_name))
        return maps[0]
    try:
        active = project.activeMap
    except Exception:
        active = None
    if active is not None:
        return active
    maps = project.listMaps()
    if not maps:
        raise ValueError("Project has no maps")
    return maps[0]


def _find_layer(map_obj, layer_name):
    for lyr in map_obj.listLayers():
        if lyr.name == layer_name or lyr.longName == layer_name:
            return lyr
    raise ValueError(
        "Layer not found in map '{}': {}".format(map_obj.name, layer_name)
    )


def _resolve_path(project, path):
    """Make relative output paths land in the project home folder."""
    if path and not os.path.isabs(path):
        return os.path.join(project.homeFolder, path)
    return path


def _extent_dict(extent):
    if extent is None:
        return None
    d = {
        "xmin": extent.XMin,
        "ymin": extent.YMin,
        "xmax": extent.XMax,
        "ymax": extent.YMax,
    }
    try:
        if extent.spatialReference:
            d["spatial_reference"] = extent.spatialReference.name
    except Exception:
        pass
    return d


def _field_dict(field):
    return {
        "name": field.name,
        "alias": field.aliasName,
        "type": field.type,
        "length": field.length,
    }


def _layer_dict(lyr):
    info = {
        "name": lyr.name,
        "long_name": lyr.longName,
        "visible": lyr.visible,
        "is_group": lyr.isGroupLayer,
        "is_feature_layer": lyr.isFeatureLayer,
        "is_raster_layer": lyr.isRasterLayer,
        "is_basemap": lyr.isBasemapLayer,
        "is_web_layer": lyr.isWebLayer,
    }
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
    if lyr.isFeatureLayer:
        try:
            info["geometry_type"] = arcpy.Describe(lyr).shapeType
        except Exception:
            pass
    return info


def _data_fields(dataset, include_geometry=False):
    skip = {"Geometry", "Blob", "Raster"}
    if include_geometry:
        skip.discard("Geometry")
    return [f for f in arcpy.ListFields(dataset) if f.type not in skip]


# ---------------------------------------------------------------------------
# Command handlers — each takes a params dict and returns JSON-serializable data
# ---------------------------------------------------------------------------

def ping(params):
    return {"pong": True}


def get_arcgis_info(params):
    install = arcpy.GetInstallInfo()
    project = _project()
    return {
        "product": install.get("ProductName"),
        "version": install.get("Version"),
        "build": install.get("BuildNumber"),
        "license": arcpy.ProductInfo(),
        "project_path": project.filePath,
        "default_geodatabase": project.defaultGeodatabase,
    }


def get_project_info(params):
    project = _project()
    maps = []
    for m in project.listMaps():
        maps.append({
            "name": m.name,
            "layer_count": len(m.listLayers()),
            "spatial_reference": m.spatialReference.name if m.spatialReference else None,
        })
    return {
        "path": project.filePath,
        "home_folder": project.homeFolder,
        "default_geodatabase": project.defaultGeodatabase,
        "default_toolbox": project.defaultToolbox,
        "maps": maps,
        "layouts": [l.name for l in project.listLayouts()],
    }


def list_maps(params):
    project = _project()
    result = []
    for m in project.listMaps():
        result.append({
            "name": m.name,
            "map_type": getattr(m, "mapType", None),
            "spatial_reference": m.spatialReference.name if m.spatialReference else None,
            "layer_count": len(m.listLayers()),
            "table_count": len(m.listTables()),
        })
    return result


def create_map(params):
    project = _project()
    name = params["name"]
    map_type = params.get("map_type", "MAP")  # MAP or SCENE
    new_map = project.createMap(name, map_type)
    return {"created": new_map.name, "map_type": map_type}


def save_project(params):
    project = _project()
    project.save()
    return {"saved": project.filePath}


def get_layers(params):
    m = _get_map(map_name=params.get("map_name"))
    layers = [_layer_dict(lyr) for lyr in m.listLayers()]
    tables = [{"name": t.name} for t in m.listTables()]
    return {"map": m.name, "layers": layers, "tables": tables}


def add_layer(params):
    """Add data by path/URL: feature class, shapefile, raster, .lyrx, service URL."""
    m = _get_map(map_name=params.get("map_name"))
    path = params["path"]
    result = m.addDataFromPath(path)
    name = getattr(result, "name", str(result))
    return {"added": name, "map": m.name}


def remove_layer(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    m.removeLayer(lyr)
    return {"removed": params["layer_name"], "map": m.name}


def set_layer_visibility(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    lyr.visible = bool(params["visible"])
    return {"layer": lyr.name, "visible": lyr.visible}


def set_definition_query(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    lyr.definitionQuery = params.get("query") or ""
    return {"layer": lyr.name, "definition_query": lyr.definitionQuery}


def get_layer_info(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    info = _layer_dict(lyr)
    desc = arcpy.Describe(lyr)
    info["data_type"] = desc.dataType
    try:
        info["spatial_reference"] = desc.spatialReference.name
        info["spatial_reference_code"] = desc.spatialReference.factoryCode
    except Exception:
        pass
    try:
        info["extent"] = _extent_dict(desc.extent)
    except Exception:
        pass
    if lyr.isFeatureLayer:
        info["fields"] = [_field_dict(f) for f in arcpy.ListFields(lyr)]
        info["feature_count"] = int(arcpy.management.GetCount(lyr)[0])
    return info


def zoom_to_layer(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    view = m.defaultView
    if view is None:
        raise RuntimeError("Map has no view to zoom")
    extent = arcpy.Describe(lyr).extent
    camera = view.camera
    camera.setExtent(extent)
    return {"zoomed_to": lyr.name, "extent": _extent_dict(extent)}


def set_basemap(params):
    m = _get_map(map_name=params.get("map_name"))
    m.addBasemap(params["basemap_name"])
    return {"map": m.name, "basemap": params["basemap_name"]}


def get_features(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    where = params.get("where") or None
    limit = min(int(params.get("limit", 50)), MAX_FEATURES)
    include_geometry = bool(params.get("include_geometry", False))

    fields = params.get("fields")
    if not fields:
        fields = [f.name for f in _data_fields(lyr)]
    cursor_fields = list(fields)
    if include_geometry:
        cursor_fields.append("SHAPE@WKT")

    rows = []
    with arcpy.da.SearchCursor(lyr, cursor_fields, where_clause=where) as cursor:
        for i, row in enumerate(cursor):
            if i >= limit:
                break
            rows.append(dict(zip(cursor_fields, row)))
    return {
        "layer": lyr.name,
        "fields": cursor_fields,
        "count": len(rows),
        "limit": limit,
        "features": rows,
    }


def get_unique_values(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    field = params["field"]
    limit = min(int(params.get("limit", 100)), MAX_FEATURES)
    values = set()
    with arcpy.da.SearchCursor(lyr, [field]) as cursor:
        for row in cursor:
            values.add(row[0])
            if len(values) > limit:
                break
    truncated = len(values) > limit
    return {
        "layer": lyr.name,
        "field": field,
        "values": sorted(list(values)[:limit], key=lambda v: (v is None, str(v))),
        "truncated": truncated,
    }


def get_field_statistics(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    field = params["field"]
    values = []
    null_count = 0
    with arcpy.da.SearchCursor(lyr, [field]) as cursor:
        for row in cursor:
            if row[0] is None:
                null_count += 1
            else:
                values.append(row[0])
    stats = {
        "layer": lyr.name,
        "field": field,
        "count": len(values),
        "null_count": null_count,
    }
    if values and isinstance(values[0], (int, float)):
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        stats.update({
            "min": min(values),
            "max": max(values),
            "sum": sum(values),
            "mean": mean,
            "std_dev": variance ** 0.5,
        })
    return stats


def select_features(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    method = params.get("method", "NEW_SELECTION")
    arcpy.management.SelectLayerByAttribute(lyr, method, params.get("where") or "")
    count = int(arcpy.management.GetCount(lyr)[0])
    return {"layer": lyr.name, "selected_count": count, "method": method}


def clear_selection(params):
    m = _get_map(map_name=params.get("map_name"))
    layer_name = params.get("layer_name")
    if layer_name:
        lyr = _find_layer(m, layer_name)
        arcpy.management.SelectLayerByAttribute(lyr, "CLEAR_SELECTION")
        return {"cleared": lyr.name}
    m.clearSelection()
    return {"cleared": "all layers in map '{}'".format(m.name)}


def add_field(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    arcpy.management.AddField(
        lyr,
        params["field_name"],
        params.get("field_type", "TEXT"),
        field_length=params.get("field_length"),
        field_alias=params.get("field_alias"),
    )
    return {"layer": lyr.name, "added_field": params["field_name"]}


def delete_field(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    arcpy.management.DeleteField(lyr, params["field_name"])
    return {"layer": lyr.name, "deleted_field": params["field_name"]}


def calculate_field(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    arcpy.management.CalculateField(
        lyr,
        params["field_name"],
        params["expression"],
        params.get("expression_type", "PYTHON3"),
    )
    return {"layer": lyr.name, "calculated_field": params["field_name"]}


def create_feature_class(params):
    project = _project()
    out_path = params.get("out_path") or project.defaultGeodatabase
    name = params["name"]
    geometry_type = params.get("geometry_type", "POLYGON")
    sr = None
    if params.get("epsg"):
        sr = arcpy.SpatialReference(int(params["epsg"]))
    result = arcpy.management.CreateFeatureclass(
        out_path, name, geometry_type, spatial_reference=sr
    )
    fc_path = str(result)
    if params.get("add_to_map", True):
        _get_map(project, params.get("map_name")).addDataFromPath(fc_path)
    return {"created": fc_path, "geometry_type": geometry_type}


def run_geoprocessing_tool(params):
    """Run any arcpy geoprocessing tool.

    tool_name: "analysis.Buffer", "arcpy.analysis.Buffer" or "Buffer_analysis"
    parameters: dict of keyword arguments, or
    args: list of positional arguments
    """
    tool_name = params["tool_name"].strip()
    name = tool_name[6:] if tool_name.startswith("arcpy.") else tool_name
    if "." in name:
        module_name, func_name = name.split(".", 1)
        tool = getattr(getattr(arcpy, module_name), func_name)
    else:
        tool = getattr(arcpy, name)

    kwargs = params.get("parameters") or {}
    args = params.get("args") or []
    result = tool(*args, **kwargs)

    data = {"tool": tool_name}
    if hasattr(result, "getMessages"):
        data["messages"] = result.getMessages()
        try:
            data["outputs"] = [
                str(result.getOutput(i)) for i in range(result.outputCount)
            ]
        except Exception:
            pass
    else:
        data["result"] = str(result)
    return data


def list_geoprocessing_tools(params):
    wildcard = params.get("wildcard", "*")
    tools = arcpy.ListTools(wildcard)
    truncated = len(tools) > MAX_LIST_ITEMS
    return {
        "wildcard": wildcard,
        "count": len(tools),
        "tools": tools[:MAX_LIST_ITEMS],
        "truncated": truncated,
    }


def set_layer_renderer(params):
    """renderer_type: simple | unique_values | graduated_colors"""
    project = _project()
    m = _get_map(project, params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    renderer_type = params.get("renderer_type", "simple")
    sym = lyr.symbology

    if renderer_type == "simple":
        sym.updateRenderer("SimpleRenderer")
        color = params.get("color")  # [r, g, b] or [r, g, b, alpha]
        if color:
            rgba = list(color) + [100] * (4 - len(color))
            sym.renderer.symbol.color = {"RGB": rgba}
        if params.get("outline_color"):
            rgba = list(params["outline_color"]) + [100] * (4 - len(params["outline_color"]))
            sym.renderer.symbol.outlineColor = {"RGB": rgba}
    elif renderer_type == "unique_values":
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = [params["field"]]
        if params.get("color_ramp"):
            ramps = project.listColorRamps(params["color_ramp"])
            if ramps:
                sym.renderer.colorRamp = ramps[0]
    elif renderer_type == "graduated_colors":
        sym.updateRenderer("GraduatedColorsRenderer")
        sym.renderer.classificationField = params["field"]
        sym.renderer.breakCount = int(params.get("break_count", 5))
        if params.get("color_ramp"):
            ramps = project.listColorRamps(params["color_ramp"])
            if ramps:
                sym.renderer.colorRamp = ramps[0]
    else:
        raise ValueError("Unknown renderer_type: {}".format(renderer_type))

    lyr.symbology = sym
    return {"layer": lyr.name, "renderer": renderer_type}


def list_layouts(params):
    project = _project()
    result = []
    for layout in project.listLayouts():
        result.append({
            "name": layout.name,
            "page_width": layout.pageWidth,
            "page_height": layout.pageHeight,
            "page_units": layout.pageUnits,
        })
    return result


def export_layout(params):
    project = _project()
    layouts = project.listLayouts(params["layout_name"])
    if not layouts:
        raise ValueError("Layout not found: {}".format(params["layout_name"]))
    layout = layouts[0]
    output_path = _resolve_path(project, params["output_path"])
    dpi = int(params.get("dpi", 200))
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".pdf":
        layout.exportToPDF(output_path, resolution=dpi)
    elif ext == ".png":
        layout.exportToPNG(output_path, resolution=dpi)
    elif ext in (".jpg", ".jpeg"):
        layout.exportToJPEG(output_path, resolution=dpi)
    elif ext == ".svg":
        layout.exportToSVG(output_path)
    else:
        raise ValueError("Unsupported export format: {}".format(ext))
    return {"layout": layout.name, "exported": output_path, "dpi": dpi}


def export_map_view(params):
    project = _project()
    m = _get_map(project, params.get("map_name"))
    view = m.defaultView
    if view is None:
        raise RuntimeError("Map has no view to export")
    output_path = _resolve_path(project, params["output_path"])
    width = int(params.get("width", 1200))
    height = int(params.get("height", 800))
    view.exportToPNG(output_path, width, height)
    return {"map": m.name, "exported": output_path, "width": width, "height": height}


def get_raster_info(params):
    m = _get_map(map_name=params.get("map_name"))
    lyr = _find_layer(m, params["layer_name"])
    desc = arcpy.Describe(lyr)
    raster = arcpy.Raster(lyr.dataSource if lyr.supports("DATASOURCE") else lyr)
    info = {
        "layer": lyr.name,
        "band_count": raster.bandCount,
        "width": raster.width,
        "height": raster.height,
        "cell_size_x": raster.meanCellWidth,
        "cell_size_y": raster.meanCellHeight,
        "pixel_type": raster.pixelType,
        "nodata_value": raster.noDataValue,
        "extent": _extent_dict(raster.extent),
    }
    try:
        info["spatial_reference"] = desc.spatialReference.name
    except Exception:
        pass
    try:
        info["minimum"] = raster.minimum
        info["maximum"] = raster.maximum
        info["mean"] = raster.mean
    except Exception:
        pass
    return info


def execute_arcpy_code(params):
    """Execute arbitrary Python code inside ArcGIS Pro. arcpy is pre-imported."""
    code = params["code"]
    namespace = {"arcpy": arcpy}
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(code, namespace)
    return {"output": buffer.getvalue() or "(no output — use print() to return values)"}


HANDLERS = {
    "ping": ping,
    "get_arcgis_info": get_arcgis_info,
    "get_project_info": get_project_info,
    "list_maps": list_maps,
    "create_map": create_map,
    "save_project": save_project,
    "get_layers": get_layers,
    "add_layer": add_layer,
    "remove_layer": remove_layer,
    "set_layer_visibility": set_layer_visibility,
    "set_definition_query": set_definition_query,
    "get_layer_info": get_layer_info,
    "zoom_to_layer": zoom_to_layer,
    "set_basemap": set_basemap,
    "get_features": get_features,
    "get_unique_values": get_unique_values,
    "get_field_statistics": get_field_statistics,
    "select_features": select_features,
    "clear_selection": clear_selection,
    "add_field": add_field,
    "delete_field": delete_field,
    "calculate_field": calculate_field,
    "create_feature_class": create_feature_class,
    "run_geoprocessing_tool": run_geoprocessing_tool,
    "list_geoprocessing_tools": list_geoprocessing_tools,
    "set_layer_renderer": set_layer_renderer,
    "list_layouts": list_layouts,
    "export_layout": export_layout,
    "export_map_view": export_map_view,
    "get_raster_info": get_raster_info,
    "execute_arcpy_code": execute_arcpy_code,
}


# ---------------------------------------------------------------------------
# Socket server
# ---------------------------------------------------------------------------

class BridgeServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.host = host
        self.port = port
        self._server_socket = None
        self._thread = None
        self._running = False

    @property
    def running(self):
        return self._running

    def start(self):
        if self._running:
            raise RuntimeError("Server already running on port {}".format(self.port))
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen(1)
        self._running = True
        self._thread = threading.Thread(
            target=self._serve, name="ArcGISMCPBridge", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

    def _serve(self):
        while self._running:
            try:
                client, _addr = self._server_socket.accept()
            except OSError:
                break  # socket closed by stop()
            try:
                self._handle_client(client)
            except Exception:
                pass
            finally:
                try:
                    client.close()
                except Exception:
                    pass

    def _handle_client(self, client):
        buffer = b""
        while self._running:
            chunk = client.recv(65536)
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                response = self._dispatch(line)
                client.sendall(response.encode("utf-8") + b"\n")

    def _dispatch(self, raw):
        request_id = None
        try:
            request = json.loads(raw.decode("utf-8"))
            request_id = request.get("id")
            command = request.get("command")
            handler = HANDLERS.get(command)
            if handler is None:
                raise ValueError("Unknown command: {}".format(command))
            data = handler(request.get("params") or {})
            payload = {"id": request_id, "success": True, "data": data}
        except Exception as exc:
            payload = {
                "id": request_id,
                "success": False,
                "error": "{}: {}".format(type(exc).__name__, exc),
                "traceback": traceback.format_exc(),
            }
        return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Module-level control (state kept in builtins so it survives .pyt reloads)
# ---------------------------------------------------------------------------

def _get_registered():
    return getattr(builtins, _REGISTRY_KEY, None)


def start_server(port=DEFAULT_PORT):
    server = _get_registered()
    if server and server.running:
        return "MCP bridge already running on port {}".format(server.port)
    server = BridgeServer(port=port)
    server.start()
    setattr(builtins, _REGISTRY_KEY, server)
    return "MCP bridge started on {}:{}".format(server.host, server.port)


def stop_server():
    server = _get_registered()
    if not server or not server.running:
        return "MCP bridge is not running"
    server.stop()
    return "MCP bridge stopped"


def server_status():
    server = _get_registered()
    if server and server.running:
        return "MCP bridge is running on {}:{}".format(server.host, server.port)
    return "MCP bridge is not running"
