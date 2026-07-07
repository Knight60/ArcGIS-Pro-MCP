"""ArcGIS Pro MCP server (stdio).

Exposes MCP tools to AI assistants (Claude Code, Codex, Gemini CLI) and relays
each call to the MCP bridge running inside ArcGIS Pro over a local TCP socket.
"""

import json
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .connection import ArcGISProNotAvailable, get_connection

mcp = FastMCP(
    "ArcGIS Pro MCP",
    instructions=(
        "Control a live ArcGIS Pro session. ArcGIS Pro must be open with the "
        "'Start MCP Server' toolbox tool running. Start with get_arcgis_info or "
        "get_layers to inspect the current state. map_name is optional almost "
        "everywhere and defaults to the active map."
    ),
)


def _call(command: str, **params: Any) -> str:
    try:
        response = get_connection().send_command(command, params)
    except ArcGISProNotAvailable as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001 — surface transport errors to the agent
        return f"Error communicating with ArcGIS Pro: {type(exc).__name__}: {exc}"
    if not response.get("success"):
        return f"ArcGIS Pro error: {response.get('error')}"
    return json.dumps(response.get("data"), ensure_ascii=False, indent=2, default=str)


# --- Session / project ------------------------------------------------------

@mcp.tool()
def ping() -> str:
    """Check that the ArcGIS Pro bridge is reachable."""
    return _call("ping")


@mcp.tool()
def get_arcgis_info() -> str:
    """Get ArcGIS Pro version, license level, and current project path."""
    return _call("get_arcgis_info")


@mcp.tool()
def get_project_info() -> str:
    """Get current project details: path, default geodatabase, maps, layouts."""
    return _call("get_project_info")


@mcp.tool()
def list_maps() -> str:
    """List all maps in the project with spatial reference and layer counts."""
    return _call("list_maps")


@mcp.tool()
def create_map(name: str, map_type: str = "MAP") -> str:
    """Create a new map in the project. map_type: MAP or SCENE."""
    return _call("create_map", name=name, map_type=map_type)


@mcp.tool()
def save_project() -> str:
    """Save the current ArcGIS Pro project (.aprx)."""
    return _call("save_project")


# --- Layers ------------------------------------------------------------------

@mcp.tool()
def get_layers(map_name: Optional[str] = None) -> str:
    """List layers and standalone tables in a map (default: active map)."""
    return _call("get_layers", map_name=map_name)


@mcp.tool()
def add_layer(path: str, map_name: Optional[str] = None) -> str:
    """Add data to a map by path or URL: feature class, shapefile, raster,
    .lyrx layer file, or web service URL."""
    return _call("add_layer", path=path, map_name=map_name)


@mcp.tool()
def remove_layer(layer_name: str, map_name: Optional[str] = None) -> str:
    """Remove a layer from a map."""
    return _call("remove_layer", layer_name=layer_name, map_name=map_name)


@mcp.tool()
def set_layer_visibility(
    layer_name: str, visible: bool, map_name: Optional[str] = None
) -> str:
    """Show or hide a layer."""
    return _call(
        "set_layer_visibility", layer_name=layer_name, visible=visible, map_name=map_name
    )


@mcp.tool()
def set_definition_query(
    layer_name: str, query: str = "", map_name: Optional[str] = None
) -> str:
    """Set a layer's definition query (SQL where clause). Empty string clears it."""
    return _call(
        "set_definition_query", layer_name=layer_name, query=query, map_name=map_name
    )


@mcp.tool()
def get_layer_info(layer_name: str, map_name: Optional[str] = None) -> str:
    """Get layer details: source, spatial reference, extent, fields, feature count."""
    return _call("get_layer_info", layer_name=layer_name, map_name=map_name)


@mcp.tool()
def zoom_to_layer(layer_name: str, map_name: Optional[str] = None) -> str:
    """Zoom the map view to a layer's extent."""
    return _call("zoom_to_layer", layer_name=layer_name, map_name=map_name)


@mcp.tool()
def set_basemap(basemap_name: str, map_name: Optional[str] = None) -> str:
    """Set the basemap, e.g. 'Topographic', 'Imagery', 'Light Gray Canvas',
    'Dark Gray Canvas', 'Streets', 'Oceans'."""
    return _call("set_basemap", basemap_name=basemap_name, map_name=map_name)


# --- Attribute data ----------------------------------------------------------

@mcp.tool()
def get_features(
    layer_name: str,
    where: Optional[str] = None,
    fields: Optional[list[str]] = None,
    limit: int = 50,
    include_geometry: bool = False,
    map_name: Optional[str] = None,
) -> str:
    """Read features from a layer as attribute rows. Optional SQL where clause
    and field list. include_geometry adds WKT geometry (can be large)."""
    return _call(
        "get_features",
        layer_name=layer_name,
        where=where,
        fields=fields,
        limit=limit,
        include_geometry=include_geometry,
        map_name=map_name,
    )


@mcp.tool()
def get_unique_values(
    layer_name: str, field: str, limit: int = 100, map_name: Optional[str] = None
) -> str:
    """Get the distinct values of a field."""
    return _call(
        "get_unique_values", layer_name=layer_name, field=field, limit=limit,
        map_name=map_name,
    )


@mcp.tool()
def get_field_statistics(
    layer_name: str, field: str, map_name: Optional[str] = None
) -> str:
    """Get min/max/mean/sum/std of a numeric field (plus count and null count)."""
    return _call(
        "get_field_statistics", layer_name=layer_name, field=field, map_name=map_name
    )


@mcp.tool()
def select_features(
    layer_name: str,
    where: str,
    method: str = "NEW_SELECTION",
    map_name: Optional[str] = None,
) -> str:
    """Select features by SQL where clause. method: NEW_SELECTION,
    ADD_TO_SELECTION, REMOVE_FROM_SELECTION, SUBSET_SELECTION."""
    return _call(
        "select_features", layer_name=layer_name, where=where, method=method,
        map_name=map_name,
    )


@mcp.tool()
def clear_selection(
    layer_name: Optional[str] = None, map_name: Optional[str] = None
) -> str:
    """Clear the selection on one layer, or on all layers if layer_name is omitted."""
    return _call("clear_selection", layer_name=layer_name, map_name=map_name)


# --- Schema / editing ---------------------------------------------------------

@mcp.tool()
def add_field(
    layer_name: str,
    field_name: str,
    field_type: str = "TEXT",
    field_length: Optional[int] = None,
    field_alias: Optional[str] = None,
    map_name: Optional[str] = None,
) -> str:
    """Add a field to a layer. field_type: TEXT, LONG, SHORT, DOUBLE, FLOAT,
    DATE, GUID, BLOB."""
    return _call(
        "add_field",
        layer_name=layer_name,
        field_name=field_name,
        field_type=field_type,
        field_length=field_length,
        field_alias=field_alias,
        map_name=map_name,
    )


@mcp.tool()
def delete_field(
    layer_name: str, field_name: str, map_name: Optional[str] = None
) -> str:
    """Delete a field from a layer."""
    return _call(
        "delete_field", layer_name=layer_name, field_name=field_name, map_name=map_name
    )


@mcp.tool()
def calculate_field(
    layer_name: str,
    field_name: str,
    expression: str,
    expression_type: str = "PYTHON3",
    map_name: Optional[str] = None,
) -> str:
    """Calculate field values, e.g. expression "!AREA! / 10000". expression_type:
    PYTHON3, ARCADE, SQL."""
    return _call(
        "calculate_field",
        layer_name=layer_name,
        field_name=field_name,
        expression=expression,
        expression_type=expression_type,
        map_name=map_name,
    )


@mcp.tool()
def create_feature_class(
    name: str,
    geometry_type: str = "POLYGON",
    epsg: Optional[int] = None,
    out_path: Optional[str] = None,
    add_to_map: bool = True,
    map_name: Optional[str] = None,
) -> str:
    """Create a new feature class (default: in the project's default geodatabase).
    geometry_type: POINT, MULTIPOINT, POLYLINE, POLYGON."""
    return _call(
        "create_feature_class",
        name=name,
        geometry_type=geometry_type,
        epsg=epsg,
        out_path=out_path,
        add_to_map=add_to_map,
        map_name=map_name,
    )


# --- Geoprocessing ------------------------------------------------------------

@mcp.tool()
def run_geoprocessing_tool(
    tool_name: str,
    parameters: Optional[dict] = None,
    args: Optional[list] = None,
) -> str:
    """Run any arcpy geoprocessing tool. tool_name like "analysis.Buffer" or
    "Buffer_analysis". Pass keyword parameters in `parameters` (preferred) or
    positional values in `args`. Layer names in the active map can be used as
    inputs. Example: tool_name="analysis.Buffer", parameters={"in_features":
    "roads", "out_feature_class": "roads_buf", "buffer_distance_or_field":
    "100 Meters"}."""
    return _call(
        "run_geoprocessing_tool", tool_name=tool_name, parameters=parameters, args=args
    )


@mcp.tool()
def list_geoprocessing_tools(wildcard: str = "*") -> str:
    """List available geoprocessing tools, e.g. wildcard "*_analysis" or "Clip*"."""
    return _call("list_geoprocessing_tools", wildcard=wildcard)


# --- Symbology / layout / export -----------------------------------------------

@mcp.tool()
def set_layer_renderer(
    layer_name: str,
    renderer_type: str = "simple",
    field: Optional[str] = None,
    color: Optional[list[int]] = None,
    outline_color: Optional[list[int]] = None,
    color_ramp: Optional[str] = None,
    break_count: int = 5,
    map_name: Optional[str] = None,
) -> str:
    """Change layer symbology. renderer_type: simple (with RGB color like
    [255, 0, 0]), unique_values (needs field), graduated_colors (needs field;
    optional color_ramp name like "Viridis" and break_count)."""
    return _call(
        "set_layer_renderer",
        layer_name=layer_name,
        renderer_type=renderer_type,
        field=field,
        color=color,
        outline_color=outline_color,
        color_ramp=color_ramp,
        break_count=break_count,
        map_name=map_name,
    )


@mcp.tool()
def list_layouts() -> str:
    """List print layouts in the project."""
    return _call("list_layouts")


@mcp.tool()
def export_layout(layout_name: str, output_path: str, dpi: int = 200) -> str:
    """Export a layout to PDF/PNG/JPEG/SVG (format inferred from the file
    extension). Relative paths are resolved against the project home folder."""
    return _call(
        "export_layout", layout_name=layout_name, output_path=output_path, dpi=dpi
    )


@mcp.tool()
def export_map_view(
    output_path: str,
    width: int = 1200,
    height: int = 800,
    map_name: Optional[str] = None,
) -> str:
    """Export the map view to a PNG image (useful as a visual check of the map)."""
    return _call(
        "export_map_view", output_path=output_path, width=width, height=height,
        map_name=map_name,
    )


# --- Raster ---------------------------------------------------------------------

@mcp.tool()
def get_raster_info(layer_name: str, map_name: Optional[str] = None) -> str:
    """Get raster layer details: bands, size, cell size, pixel type, statistics."""
    return _call("get_raster_info", layer_name=layer_name, map_name=map_name)


# --- Escape hatch -----------------------------------------------------------------

@mcp.tool()
def execute_arcpy_code(code: str) -> str:
    """Execute arbitrary Python code inside ArcGIS Pro (arcpy is pre-imported;
    use arcpy.mp.ArcGISProject('CURRENT') for the open project). Use print()
    to return output. Use this when no dedicated tool covers the task."""
    return _call("execute_arcpy_code", code=code)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
