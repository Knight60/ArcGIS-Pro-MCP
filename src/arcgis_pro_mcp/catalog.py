"""The MCP tool catalog -- one entry per bridge command.

This is the single source of truth for the tools exposed to AI assistants.
``server.py`` turns each entry into a real MCP tool, so adding a capability is
a handler in ``arcgis_pro_plugin/arcgis_mcp/`` plus one entry here.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

REQUIRED = object()


@dataclass
class Param:
    name: str
    type: str = "str"
    default: Any = REQUIRED
    description: str = ""

    @property
    def required(self) -> bool:
        return self.default is REQUIRED


@dataclass
class Tool:
    name: str
    group: str
    description: str
    params: List[Param] = field(default_factory=list)
    returns_image: bool = False
    destructive: bool = False


def P(name, type="str", default=REQUIRED, description=""):
    return Param(name, type, default, description)


def T(name, group, description, *params, returns_image=False, destructive=False):
    return Tool(name, group, description, list(params),
                returns_image=returns_image, destructive=destructive)


MAP_NAME = P("map_name", "str", None, "Map to act on; defaults to the active map.")
LAYER = P("layer_name", "str", REQUIRED,
          "Layer or table name as shown by get_layers, or a full dataset path.")

CATALOG: List[Tool] = [

    # --- session / project ---------------------------------------------------
    T("ping", "Session",
      "Check that the ArcGIS Pro bridge is reachable and see which project it "
      "is attached to."),

    T("get_capabilities", "Session",
      "List every command the connected bridge supports, grouped by area. Use "
      "this to discover functionality beyond the named tools."),

    T("diagnose", "Session",
      "Self-check the connection: ArcGIS Pro version, licence, open project, "
      "active map, open map view and write access. Run this first when "
      "something does not work."),

    T("get_arcgis_info", "Session",
      "ArcGIS Pro version, licence level, available extensions and the current "
      "project path."),

    T("get_project_info", "Session",
      "Project paths, default geodatabase and toolbox, maps, layouts, folder "
      "and database connections."),

    T("save_project", "Session",
      "Save the ArcGIS Pro project (.aprx), or save a copy elsewhere.",
      P("save_as_path", "str", None,
        "Optional path for a copy; the open project is left untouched.")),

    T("list_maps", "Session",
      "List all maps and scenes with coordinate system and layer counts."),

    T("create_map", "Session",
      "Create a new map or scene in the project.",
      P("name", "str", REQUIRED, "Name for the new map."),
      P("map_type", "str", "MAP", "MAP or SCENE."),
      P("epsg", "int", None, "Optional coordinate system WKID, e.g. 32647."),
      P("basemap", "str", None, "Optional basemap to add, e.g. 'Topographic'.")),

    T("remove_map", "Session",
      "Delete a map from the project.",
      P("map_name", "str", REQUIRED, "Map to delete."), destructive=True),

    T("activate_map", "Session",
      "Open/activate a map's view in the ArcGIS Pro UI. Needed before camera "
      "commands and export_map_view.",
      P("map_name", "str", REQUIRED, "Map to activate.")),

    T("set_map_properties", "Session",
      "Rename a map or change its coordinate system.",
      MAP_NAME,
      P("new_name", "str", None, "New map name."),
      P("epsg", "int", None, "New coordinate system WKID.")),

    T("get_map_extent", "Session",
      "The combined extent of all data layers in a map.", MAP_NAME),

    T("get_environment", "Session",
      "Read the current arcpy geoprocessing environment settings."),

    T("set_environment", "Session",
      "Set arcpy geoprocessing environment settings such as workspace, "
      "outputCoordinateSystem, extent, mask, cellSize, overwriteOutput or "
      "parallelProcessingFactor.",
      P("settings", "dict", REQUIRED,
        'Environment name/value pairs, e.g. {"overwriteOutput": true, '
        '"workspace": "D:/data/project.gdb"}.')),

    # --- layers --------------------------------------------------------------
    T("get_layers", "Layers",
      "List the layers (with draw order and group nesting) and standalone "
      "tables in a map. Start here to see what is in the project.",
      MAP_NAME,
      P("include_basemap", "bool", False, "Include basemap layers.")),

    T("get_layer_info", "Layers",
      "Full detail for one layer: data source, coordinate system, extent, "
      "fields, feature count, renderer and label state.",
      LAYER, MAP_NAME),

    T("add_layer", "Layers",
      "Add data to a map from a path or service URL: feature class, shapefile, "
      "raster, table, .lyrx layer file or web service.",
      P("path", "str", REQUIRED, "Dataset path or service URL."),
      MAP_NAME,
      P("group_layer", "str", None, "Optional group layer to add it into."),
      P("position", "str", "AUTO_ARRANGE", "AUTO_ARRANGE, TOP or BOTTOM.")),

    T("add_web_layer", "Layers",
      "Add a web service layer (Feature/Map/Image service, WMS, WMTS, vector "
      "tile) by URL.",
      P("url", "str", REQUIRED, "Service URL."),
      MAP_NAME),

    T("remove_layer", "Layers",
      "Remove a layer or standalone table from a map.",
      LAYER, MAP_NAME, destructive=True),

    T("rename_layer", "Layers",
      "Rename a layer in the table of contents.",
      LAYER,
      P("new_name", "str", REQUIRED, "New display name."),
      MAP_NAME),

    T("duplicate_layer", "Layers",
      "Copy a layer within the map so it can be symbolised differently.",
      LAYER,
      P("new_name", "str", None, "Name for the copy."),
      MAP_NAME),

    T("set_layer_visibility", "Layers",
      "Show or hide one layer, several layers, or every layer in the map.",
      P("visible", "bool", REQUIRED, "True to show, False to hide."),
      P("layer_name", "str", None, "Single layer to change."),
      P("layer_names", "list[str]", None, "Several layers to change."),
      MAP_NAME),

    T("set_layer_transparency", "Layers",
      "Set layer transparency (0 = opaque, 100 = fully transparent).",
      LAYER,
      P("transparency", "int", REQUIRED, "0-100."),
      MAP_NAME),

    T("set_layer_scale_range", "Layers",
      "Limit the scale range a layer draws at.",
      LAYER,
      P("min_scale", "float", None,
        "Zoomed-out limit, e.g. 100000 (0 = no limit)."),
      P("max_scale", "float", None,
        "Zoomed-in limit, e.g. 1000 (0 = no limit)."),
      MAP_NAME),

    T("set_definition_query", "Layers",
      "Set a layer's definition query (SQL where clause). Empty string clears it.",
      LAYER,
      P("query", "str", "", "SQL where clause, e.g. \"POP > 10000\"."),
      MAP_NAME),

    T("move_layer", "Layers",
      "Reorder a layer relative to another, or move it into a group layer.",
      LAYER,
      P("reference_layer", "str", None, "Layer to position relative to."),
      P("group_layer", "str", None, "Group layer to move it into instead."),
      P("position", "str", "BEFORE", "BEFORE or AFTER the reference layer."),
      MAP_NAME),

    T("create_group_layer", "Layers",
      "Create a group layer, optionally moving existing layers into it.",
      P("name", "str", REQUIRED, "Group layer name."),
      P("layer_names", "list[str]", None, "Layers to move into the group."),
      MAP_NAME),

    T("zoom_to_layer", "Layers",
      "Zoom the map view to a layer's extent.",
      LAYER,
      P("expand_factor", "float", None,
        "Optional padding, e.g. 0.1 for 10% extra around the extent."),
      MAP_NAME),

    T("set_basemap", "Layers",
      "Set the basemap: Topographic, Imagery, Imagery Hybrid, Streets, "
      "Navigation, Light Gray Canvas, Dark Gray Canvas, Terrain, Oceans, "
      "OpenStreetMap, National Geographic Style Map.",
      P("basemap_name", "str", REQUIRED, "Basemap name."),
      MAP_NAME),

    T("get_broken_layers", "Layers",
      "List layers across all maps whose data source is missing."),

    T("repair_layer_source", "Layers",
      "Repoint a layer at a new workspace or dataset to fix a broken source.",
      LAYER,
      P("new_source", "str", REQUIRED,
        "New workspace (folder/.gdb) or full dataset path."),
      P("dataset_name", "str", None, "Dataset name inside the new workspace."),
      MAP_NAME),

    T("add_join", "Layers",
      "Join a table to a layer on a common field.",
      LAYER,
      P("layer_field", "str", REQUIRED, "Field on the layer."),
      P("join_table", "str", REQUIRED, "Table layer name or dataset path."),
      P("join_field", "str", REQUIRED, "Field on the join table."),
      P("keep_all", "str", "KEEP_ALL", "KEEP_ALL or KEEP_COMMON."),
      MAP_NAME),

    T("remove_join", "Layers",
      "Remove a join from a layer.",
      LAYER,
      P("join_name", "str", None, "Join to remove; defaults to the last one."),
      MAP_NAME),

    # --- data ----------------------------------------------------------------
    T("get_features", "Data",
      "Read attribute rows from a layer, table or dataset path, with an "
      "optional where clause, field subset, ordering and WKT geometry.",
      LAYER,
      P("where", "str", None, "SQL where clause."),
      P("fields", "list[str]", None, "Fields to return; default all."),
      P("limit", "int", 50, "Maximum rows to return (max 5000)."),
      P("offset", "int", 0, "Rows to skip -- use for paging."),
      P("order_by", "str", None, 'ORDER BY clause, e.g. "POP DESC".'),
      P("include_geometry", "bool", False,
        "Add SHAPE@WKT geometry (can be very large)."),
      MAP_NAME),

    T("count_features", "Data",
      "Count features, optionally matching a where clause.",
      LAYER,
      P("where", "str", None, "SQL where clause."),
      MAP_NAME),

    T("get_unique_values", "Data",
      "Distinct values of a field with the count of rows for each.",
      LAYER,
      P("field", "str", REQUIRED, "Field name."),
      P("where", "str", None, "SQL where clause."),
      P("limit", "int", 200, "Maximum distinct values to return."),
      MAP_NAME),

    T("get_field_statistics", "Data",
      "min / max / mean / median / sum / standard deviation of a numeric field.",
      LAYER,
      P("field", "str", REQUIRED, "Field name."),
      P("where", "str", None, "SQL where clause."),
      MAP_NAME),

    T("summarize_features", "Data",
      "Group rows by one or more fields and aggregate -- the fast way to "
      "answer 'how many / how much per category' without geoprocessing.",
      LAYER,
      P("group_by", "list[str]", REQUIRED, "Field(s) to group by."),
      P("value_field", "str", None,
        "Numeric field to sum/average per group."),
      P("where", "str", None, "SQL where clause."),
      P("limit", "int", 200, "Maximum groups to return."),
      MAP_NAME),

    T("insert_features", "Data",
      "Insert new rows into a layer or table.",
      LAYER,
      P("features", "list[dict]", REQUIRED,
        'Rows, e.g. [{"attributes": {"NAME": "A"}, "geometry": '
        '"POINT (100 15)"}]. geometry accepts WKT, [x, y] or Esri JSON.'),
      P("geometry_spatial_reference", "int", None,
        "WKID of the supplied geometry; defaults to the layer's."),
      P("use_edit_session", "bool", True,
        "Wrap in an edit session (needed for enterprise/versioned data)."),
      P("save_edits", "bool", False,
        "Commit the edits immediately instead of leaving them pending."),
      MAP_NAME),

    T("update_features", "Data",
      "Update attributes and/or geometry of rows matching a where clause.",
      LAYER,
      P("attributes", "dict", None, 'Field/value pairs to write.'),
      P("geometry", "str", None, "New geometry as WKT, applied to every match."),
      P("where", "str", None,
        "SQL where clause selecting the rows to update."),
      P("limit", "int", 0, "Stop after this many rows (0 = no limit)."),
      P("allow_update_all", "bool", False,
        "Required confirmation when no where clause is given."),
      P("geometry_spatial_reference", "int", None, "WKID of the geometry."),
      P("use_edit_session", "bool", True, "Wrap in an edit session."),
      P("save_edits", "bool", False,
        "Commit the edits immediately instead of leaving them pending."),
      MAP_NAME, destructive=True),

    T("delete_features", "Data",
      "Delete rows matching a where clause.",
      LAYER,
      P("where", "str", None, "SQL where clause selecting rows to delete."),
      P("allow_delete_all", "bool", False,
        "Required confirmation when no where clause is given."),
      P("use_edit_session", "bool", True, "Wrap in an edit session."),
      P("save_edits", "bool", False,
        "Commit the edits immediately instead of leaving them pending."),
      MAP_NAME, destructive=True),

    T("save_edits", "Data",
      "Commit pending edits. ArcGIS Pro keeps edits open so they can be undone, "
      "which also leaves the data locked until they are saved -- deleting or "
      "overwriting an edited dataset fails until then."),

    T("discard_edits", "Data",
      "Throw away pending edits."),

    T("calculate_field", "Data",
      "Calculate field values across a layer, e.g. expression \"!Shape_Area! "
      "/ 10000\".",
      LAYER,
      P("field_name", "str", REQUIRED, "Field to write to."),
      P("expression", "str", REQUIRED, "Expression."),
      P("expression_type", "str", "PYTHON3", "PYTHON3, ARCADE or SQL."),
      P("code_block", "str", None, "Optional helper function definitions."),
      MAP_NAME),

    # --- selection -----------------------------------------------------------
    T("select_features", "Selection",
      "Select features by SQL where clause.",
      LAYER,
      P("where", "str", REQUIRED, "SQL where clause."),
      P("method", "str", "NEW_SELECTION",
        "NEW_SELECTION, ADD_TO_SELECTION, REMOVE_FROM_SELECTION, "
        "SUBSET_SELECTION, SWITCH_SELECTION or CLEAR_SELECTION."),
      P("invert", "str", "NON_INVERT",
        "INVERT to select everything the clause does not match."),
      MAP_NAME),

    T("select_by_location", "Selection",
      "Select features by spatial relationship to another layer.",
      LAYER,
      P("select_features", "str", REQUIRED,
        "Layer or path whose features define the relationship."),
      P("relationship", "str", "INTERSECT",
        "INTERSECT, WITHIN_A_DISTANCE, CONTAINS, WITHIN, COMPLETELY_WITHIN, "
        "HAVE_THEIR_CENTER_IN, CROSSED_BY_THE_OUTLINE_OF, ..."),
      P("search_distance", "str", None,
        'Distance for WITHIN_A_DISTANCE, e.g. "500 Meters".'),
      P("method", "str", "NEW_SELECTION", "How to combine with the current selection."),
      P("invert", "str", "NOT_INVERT",
        "INVERT to select everything the relationship does not match."),
      MAP_NAME),

    T("get_selection", "Selection",
      "Report what is currently selected, per layer, with ObjectIDs and "
      "optionally the attribute rows.",
      P("layer_name", "str", None, "Single layer; default every feature layer."),
      P("limit", "int", 100, "Maximum ObjectIDs/rows per layer."),
      P("include_attributes", "bool", False, "Also return the selected rows."),
      MAP_NAME),

    T("set_selection", "Selection",
      "Select specific features by ObjectID.",
      LAYER,
      P("oids", "list[int]", REQUIRED, "ObjectIDs to select."),
      P("method", "str", "NEW", "NEW, DIFFERENCE, INTERSECT, SYMDIFFERENCE, UNION."),
      MAP_NAME),

    T("clear_selection", "Selection",
      "Clear the selection on one layer, or on every layer in the map.",
      P("layer_name", "str", None, "Layer to clear; default all layers."),
      MAP_NAME),

    T("zoom_to_selection", "Selection",
      "Zoom the map view to the currently selected features.",
      LAYER, MAP_NAME),

    # --- schema --------------------------------------------------------------
    T("list_fields", "Schema",
      "List a layer's fields with type, alias, length and domain.",
      LAYER,
      P("wildcard", "str", None, 'Optional name filter, e.g. "POP*".'),
      MAP_NAME),

    T("add_field", "Schema",
      "Add a field to a layer or table.",
      LAYER,
      P("field_name", "str", REQUIRED, "New field name."),
      P("field_type", "str", "TEXT",
        "TEXT, LONG, SHORT, DOUBLE, FLOAT, DATE, BIGINTEGER, GUID or BLOB."),
      P("field_length", "int", None, "Length for TEXT fields."),
      P("field_alias", "str", None, "Display alias."),
      P("field_precision", "int", None, "Numeric precision."),
      P("field_scale", "int", None, "Numeric scale."),
      P("field_domain", "str", None, "Attribute domain to assign."),
      P("nullable", "str", "NULLABLE", "NULLABLE or NON_NULLABLE."),
      MAP_NAME),

    T("add_fields", "Schema",
      "Add several fields in one call.",
      LAYER,
      P("fields", "list[dict]", REQUIRED,
        'e.g. [{"name": "AREA_HA", "type": "DOUBLE", "alias": "Area (ha)"}].'),
      MAP_NAME),

    T("delete_field", "Schema",
      "Delete one or more fields.",
      LAYER,
      P("field_name", "str", None, "Single field to delete."),
      P("field_names", "list[str]", None, "Several fields to delete."),
      MAP_NAME, destructive=True),

    T("alter_field", "Schema",
      "Rename a field or change its alias/length.",
      LAYER,
      P("field_name", "str", REQUIRED, "Existing field name."),
      P("new_name", "str", None, "New field name."),
      P("new_alias", "str", None, "New alias."),
      P("field_length", "int", None, "New length for TEXT fields."),
      MAP_NAME),

    T("create_feature_class", "Schema",
      "Create an empty feature class, by default in the project's default "
      "geodatabase, and add it to the map.",
      P("name", "str", REQUIRED, "Feature class name."),
      P("geometry_type", "str", "POLYGON",
        "POINT, MULTIPOINT, POLYLINE or POLYGON."),
      P("epsg", "int", None, "Coordinate system WKID, e.g. 32647."),
      P("out_path", "str", None, "Target geodatabase or folder."),
      P("template", "str", None, "Dataset to copy the schema from."),
      P("fields", "list[dict]", None,
        'Fields to create, e.g. [{"name": "NAME", "type": "TEXT", '
        '"length": 50}].'),
      P("has_z", "str", "DISABLED", "ENABLED or DISABLED."),
      P("has_m", "str", "DISABLED", "ENABLED or DISABLED."),
      P("add_to_map", "bool", True, "Add the result to the map."),
      MAP_NAME),

    T("create_table", "Schema",
      "Create an empty standalone table.",
      P("name", "str", REQUIRED, "Table name."),
      P("out_path", "str", None, "Target geodatabase or folder."),
      P("template", "str", None, "Table to copy the schema from."),
      P("fields", "list[dict]", None, "Fields to create."),
      P("add_to_map", "bool", True, "Add the result to the map."),
      MAP_NAME),

    T("create_file_geodatabase", "Schema",
      "Create a new file geodatabase.",
      P("name", "str", REQUIRED, "Geodatabase name (.gdb is added if missing)."),
      P("folder", "str", None, "Parent folder; default the project home folder.")),

    T("truncate_table", "Schema",
      "Delete every row from a table or feature class, keeping the schema.",
      LAYER, MAP_NAME, destructive=True),

    T("delete_dataset", "Schema",
      "Delete a dataset from disk or a geodatabase. This cannot be undone.",
      P("path", "str", REQUIRED, "Dataset path."), destructive=True),

    T("export_features", "Schema",
      "Export a layer -- honouring its current selection and definition query "
      "-- to a new dataset.",
      LAYER,
      P("out_path", "str", REQUIRED, "Output dataset path."),
      P("where", "str", None, "Extra where clause."),
      P("add_to_map", "bool", True, "Add the result to the map."),
      MAP_NAME),

    # --- geoprocessing -------------------------------------------------------
    T("run_geoprocessing_tool", "Geoprocessing",
      "Run any arcpy geoprocessing tool -- the universal escape hatch for "
      "analysis. Layer names resolve to live layers so selections and "
      "definition queries apply. Call describe_geoprocessing_tool first if the "
      "parameter names are not known.",
      P("tool_name", "str", REQUIRED,
        'e.g. "analysis.Buffer", "management.Dissolve", "sa.Slope" or '
        '"Buffer_analysis".'),
      P("parameters", "dict", None,
        'Keyword parameters, e.g. {"in_features": "roads", '
        '"out_feature_class": "roads_buf", "buffer_distance_or_field": '
        '"500 Meters"}.'),
      P("args", "list", None, "Positional parameters instead of keywords."),
      P("add_to_map", "bool", False, "Add the tool's outputs to the map."),
      P("overwrite", "bool", None, "Temporarily allow overwriting outputs."),
      P("checkout_extension", "str", None,
        'Extension to check out for this run, e.g. "Spatial" or "3D".'),
      MAP_NAME),

    T("list_geoprocessing_tools", "Geoprocessing",
      "Search the available geoprocessing tools by name.",
      P("wildcard", "str", "*", 'Name pattern, e.g. "*Buffer*".'),
      P("toolbox", "str", None,
        'Restrict to one toolbox alias, e.g. "analysis" or "management".'),
      P("limit", "int", 500, "Maximum tool names to return.")),

    T("list_toolboxes", "Geoprocessing",
      "List the arcpy toolbox modules and any toolboxes in the project."),

    T("describe_geoprocessing_tool", "Geoprocessing",
      "Get a tool's parameters, data types, defaults and usage text before "
      "running it.",
      P("tool_name", "str", REQUIRED,
        'e.g. "analysis.Buffer" or "Buffer_analysis".')),

    T("run_python_toolbox_tool", "Geoprocessing",
      "Run a tool from a custom .pyt / .atbx / .tbx toolbox on disk.",
      P("toolbox_path", "str", REQUIRED, "Path to the toolbox."),
      P("tool_name", "str", REQUIRED, "Tool name inside the toolbox."),
      P("alias", "str", None, "Toolbox alias to import under."),
      P("parameters", "dict", None, "Keyword parameters."),
      P("args", "list", None, "Positional parameters.")),

    T("check_extension", "Geoprocessing",
      "Check, and optionally check out, an ArcGIS extension licence.",
      P("extension", "str", REQUIRED,
        '"Spatial", "3D", "Network", "ImageAnalyst", "GeoStats", ...'),
      P("checkout", "bool", False, "Check the licence out if it is available.")),

    T("get_messages", "Geoprocessing",
      "Messages from the most recent geoprocessing operation.",
      P("severity", "int", 0, "0 all, 1 warnings, 2 errors.")),

    # --- symbology -----------------------------------------------------------
    T("set_layer_renderer", "Symbology",
      "Change a layer's symbology: a single symbol, unique values by "
      "category, or a classified/continuous colour scheme by numeric field.",
      LAYER,
      P("renderer_type", "str", "simple",
        "simple, unique_values, graduated_colors, graduated_symbols or "
        "unclassed_colors."),
      P("field", "str", None, "Field to symbolise by (all types except simple)."),
      P("fields", "list[str]", None,
        "Several fields for unique_values symbology."),
      P("color", "list[int]", None,
        "Fill colour for simple symbology as [r, g, b] or [r, g, b, alpha]."),
      P("outline_color", "list[int]", None, "Outline colour as [r, g, b]."),
      P("outline_width", "float", None, "Outline width in points."),
      P("symbol_size", "float", None, "Point/line symbol size in points."),
      P("color_ramp", "str", None,
        'Colour ramp name, e.g. "Viridis" -- see list_color_ramps.'),
      P("break_count", "int", 5, "Number of classes for graduated symbology."),
      P("classification_method", "str", None,
        "NaturalBreaks, EqualInterval, Quantile, StandardDeviation, "
        "GeometricInterval or DefinedInterval."),
      P("min_symbol_size", "float", None, "Smallest size for graduated_symbols."),
      P("max_symbol_size", "float", None, "Largest size for graduated_symbols."),
      P("value_colors", "dict", None,
        'Explicit colours per category for unique_values, e.g. '
        '{"Forest": [34, 139, 34]}.'),
      P("class_colors", "list[list]", None,
        "Explicit colour per class for graduated symbology, lowest class "
        "first, e.g. [[244,166,166],[249,220,164],[147,203,163]]. Use it when "
        "no built-in ramp has the colours you want."),
      P("transparency", "int", None, "Layer transparency 0-100."),
      P("label", "str", None, "Legend label for simple symbology."),
      MAP_NAME),

    T("get_layer_symbology", "Symbology",
      "Inspect a layer's current renderer, class breaks, unique values and "
      "label settings.",
      LAYER, MAP_NAME),

    T("list_color_ramps", "Symbology",
      "List the colour ramps available in the project.",
      P("wildcard", "str", "*", 'Name filter, e.g. "*Viridis*".'),
      P("limit", "int", 500, "Maximum names to return.")),

    T("set_layer_labeling", "Symbology",
      "Turn labels on or off and set the expression, font and halo.",
      LAYER,
      P("enabled", "bool", True, "Show labels."),
      P("expression", "str", None,
        'Label expression, Arcade by default, e.g. "$feature.NAME".'),
      P("expression_engine", "str", "Arcade", "Arcade, Python or VBScript."),
      P("where", "str", None, "Only label features matching this SQL clause."),
      P("font_size", "float", None, "Font size in points."),
      P("font_family", "str", None, 'Font name, e.g. "Tahoma".'),
      P("font_color", "list[int]", None, "Font colour as [r, g, b]."),
      P("bold", "bool", None, "Bold text."),
      P("italic", "bool", None, "Italic text."),
      P("halo_size", "float", None, "Halo size in points."),
      MAP_NAME),

    T("apply_symbology_from_layer", "Symbology",
      "Copy symbology from a .lyrx file or another layer.",
      LAYER,
      P("symbology_source", "str", REQUIRED,
        "Path to a .lyrx file, or the name of another layer."),
      P("update_symbology", "str", "MAINTAIN",
        "MAINTAIN, UPDATE or DEFAULT -- how to handle differing field values."),
      MAP_NAME),

    T("save_layer_file", "Symbology",
      "Save a layer with its symbology to a .lyrx file for reuse.",
      LAYER,
      P("output_path", "str", REQUIRED, "Output .lyrx path."),
      P("relative_paths", "str", "ABSOLUTE", "ABSOLUTE or RELATIVE."),
      MAP_NAME),

    # --- view ----------------------------------------------------------------
    T("get_map_view", "View",
      "Current camera position: centre, scale, rotation and visible extent. "
      "Requires the map's tab to be open in ArcGIS Pro.",
      MAP_NAME),

    T("set_map_view", "View",
      "Move the map view: set an extent, a centre point, a scale and/or a "
      "rotation.",
      P("extent", "dict", None,
        'Extent as {"xmin": ..., "ymin": ..., "xmax": ..., "ymax": ...}.'),
      P("x", "float", None, "Centre X in map units."),
      P("y", "float", None, "Centre Y in map units."),
      P("scale", "float", None, "Map scale denominator, e.g. 50000."),
      P("rotation", "float", None, "Rotation in degrees."),
      P("epsg", "int", None, "WKID the extent coordinates are in."),
      MAP_NAME),

    T("export_map_view", "View",
      "Render the map view to PNG and return the image so it can be looked "
      "at -- the way to visually check a map. Requires the map's tab to be "
      "open in ArcGIS Pro.",
      P("output_path", "str", None,
        "Optional file to save to; omit for a temporary image."),
      P("width", "int", 1200, "Image width in pixels."),
      P("height", "int", 800, "Image height in pixels."),
      P("dpi", "int", 96, "Resolution."),
      P("zoom_to_layer", "str", None, "Zoom to this layer before exporting."),
      P("return_image", "bool", True, "Return the image inline."),
      MAP_NAME, returns_image=True),

    T("list_bookmarks", "View",
      "List the spatial bookmarks defined on a map.", MAP_NAME),

    T("create_bookmark", "View",
      "Save the current view, or a given extent, as a named bookmark.",
      P("name", "str", REQUIRED, "Bookmark name."),
      P("extent", "dict", None, "Extent to bookmark instead of the current view."),
      P("description", "str", None, "Optional bookmark description."),
      MAP_NAME),

    T("apply_bookmark", "View",
      "Zoom the map view to a bookmark.",
      P("bookmark_name", "str", REQUIRED, "Bookmark to apply."),
      MAP_NAME),

    T("delete_bookmark", "View",
      "Delete a bookmark from a map.",
      P("bookmark_name", "str", REQUIRED, "Bookmark to delete."),
      MAP_NAME, destructive=True),

    # --- layouts -------------------------------------------------------------
    T("list_layouts", "Layouts",
      "List the print layouts with page size and element counts."),

    T("get_layout_info", "Layouts",
      "Inspect a layout: page setup and every element with position and size.",
      P("layout_name", "str", REQUIRED, "Layout name.")),

    T("create_layout", "Layouts",
      "Create a new layout page, by default with a map frame filling it.",
      P("name", "str", REQUIRED, "Layout name."),
      P("page_width", "float", 11, "Page width."),
      P("page_height", "float", 8.5, "Page height."),
      P("page_units", "str", "INCH", "INCH, CENTIMETER, MILLIMETER or POINT."),
      P("add_map_frame", "bool", True, "Add a map frame filling the page."),
      P("margin", "float", 0.5, "Margin around the map frame, in page units."),
      P("map_frame_name", "str", "Map Frame", "Name for the map frame."),
      MAP_NAME),

    T("delete_layout", "Layouts",
      "Delete a layout from the project.",
      P("layout_name", "str", REQUIRED, "Layout to delete."), destructive=True),

    T("add_map_frame", "Layouts",
      "Add a map frame to a layout at a page position.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("x", "float", 0.5, "Lower-left X in page units."),
      P("y", "float", 0.5, "Lower-left Y in page units."),
      P("width", "float", 6, "Frame width in page units."),
      P("height", "float", 5, "Frame height in page units."),
      P("name", "str", "Map Frame", "Element name."),
      MAP_NAME),

    T("set_map_frame_extent", "Layouts",
      "Point a layout's map frame at a layer, an extent or a scale.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("map_frame_name", "str", "Map Frame", "Map frame element name."),
      P("layer_name", "str", None, "Zoom the frame to this layer."),
      P("selection_only", "bool", False,
        "Zoom to the layer's selected features only."),
      P("extent", "dict", None, "Explicit extent to show."),
      P("zoom_to_all", "bool", False, "Zoom to all layers in the frame's map."),
      P("scale", "float", None, "Fixed scale denominator."),
      P("rotation", "float", None, "Frame rotation in degrees.")),

    T("add_layout_text", "Layouts",
      "Add a text element such as a title or credits to a layout.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("text", "str", REQUIRED, "Text to display."),
      P("x", "float", 0.5, "X position in page units."),
      P("y", "float", 8.0, "Y position in page units."),
      P("font_size", "float", 14, "Font size in points."),
      P("font", "str", "Tahoma", "Font family."),
      P("color", "list[int]", None, "Text colour as [r, g, b]."),
      P("bold", "bool", None, "Bold text."),
      P("italic", "bool", None, "Italic text."),
      P("name", "str", None, "Element name.")),

    T("add_layout_legend", "Layouts",
      "Add a legend tied to a layout's map frame.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("map_frame_name", "str", "Map Frame", "Map frame to describe."),
      P("x", "float", 0.5, "X position in page units."),
      P("y", "float", 0.5, "Y position in page units."),
      P("width", "float", None, "Width in page units."),
      P("height", "float", None, "Height in page units."),
      P("title", "str", None, "Legend title."),
      P("layers", "list[str]", None, "Only show these layers in the legend."),
      P("style_item", "str", None, "Legend style item name."),
      P("name", "str", None, "Element name.")),

    T("add_layout_scale_bar", "Layouts",
      "Add a scale bar tied to a layout's map frame.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("map_frame_name", "str", "Map Frame", "Map frame to measure."),
      P("x", "float", 0.5, "X position in page units."),
      P("y", "float", 0.5, "Y position in page units."),
      P("width", "float", None, "Width in page units."),
      P("height", "float", None, "Height in page units."),
      P("style_item", "str", None, "Scale bar style item name."),
      P("name", "str", None, "Element name.")),

    T("add_layout_north_arrow", "Layouts",
      "Add a north arrow tied to a layout's map frame.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("map_frame_name", "str", "Map Frame", "Map frame to orient to."),
      P("x", "float", 0.5, "X position in page units."),
      P("y", "float", 0.5, "Y position in page units."),
      P("width", "float", None, "Width in page units."),
      P("height", "float", None, "Height in page units."),
      P("style_item", "str", None, "North arrow style item name."),
      P("name", "str", None, "Element name.")),

    T("add_layout_picture", "Layouts",
      "Place an image such as a logo on a layout.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("picture_path", "str", REQUIRED, "Image file path."),
      P("x", "float", 0.5, "X position in page units."),
      P("y", "float", 0.5, "Y position in page units."),
      P("width", "float", 1.5, "Width in page units."),
      P("height", "float", 1.0, "Height in page units."),
      P("name", "str", "Picture", "Element name.")),

    T("set_layout_element", "Layouts",
      "Move, resize, rename, hide or change the text of any layout element.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("element_name", "str", REQUIRED, "Element to change."),
      P("x", "float", None, "New X position."),
      P("y", "float", None, "New Y position."),
      P("width", "float", None, "New width."),
      P("height", "float", None, "New height."),
      P("text", "str", None, "New text (text elements only)."),
      P("visible", "bool", None, "Show or hide the element."),
      P("new_name", "str", None, "Rename the element.")),

    T("delete_layout_element", "Layouts",
      "Remove an element from a layout.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("element_name", "str", REQUIRED, "Element to delete."), destructive=True),

    T("export_layout", "Layouts",
      "Export a layout to PDF / PNG / JPEG / SVG / TIFF. PNG and JPEG come "
      "back as an inline image so the result can be checked.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("output_path", "str", REQUIRED,
        "Output file; the format follows the extension."),
      P("dpi", "int", 200, "Export resolution."),
      P("return_image", "bool", True, "Return PNG/JPEG output inline."),
      returns_image=True),

    T("preview_layout", "Layouts",
      "Render a layout to a temporary image and return it, without writing a "
      "file -- use it to visually check a layout while building it.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("dpi", "int", 100, "Render resolution."), returns_image=True),

    T("export_map_series", "Layouts",
      "Export a layout's map series (map book) to a multi-page PDF.",
      P("layout_name", "str", REQUIRED, "Layout name."),
      P("output_path", "str", REQUIRED, "Output PDF path."),
      P("page_range", "str", None, 'Pages to export, e.g. "1-5,8".'),
      P("dpi", "int", 200, "Export resolution.")),

    # --- raster --------------------------------------------------------------
    T("get_raster_info", "Raster",
      "Raster detail: bands, size, cell size, pixel type, statistics and CRS.",
      LAYER, MAP_NAME),

    T("set_raster_symbology", "Raster",
      "Set a raster layer's colorizer and colour ramp.",
      LAYER,
      P("colorizer", "str", "stretch",
        "stretch, classify, unique_values or rgb."),
      P("stretch_type", "str", None,
        "MinimumMaximum, StandardDeviation, PercentClip, HistogramEqualize, ..."),
      P("break_count", "int", None, "Number of classes for classify."),
      P("classification_method", "str", None, "Classification method."),
      P("color_ramp", "str", None, 'Colour ramp name, e.g. "Elevation #1".'),
      P("transparency", "int", None, "Layer transparency 0-100."),
      MAP_NAME),

    T("raster_calculator", "Raster",
      "Map algebra. Bind rasters to short names, then write a Python "
      "expression over them. Requires the Spatial Analyst extension.",
      P("rasters", "dict", REQUIRED,
        'Alias to layer name or path, e.g. {"dem": "elevation", "slp": '
        '"slope.tif"}.'),
      P("expression", "str", REQUIRED,
        'Expression over the aliases, e.g. "(dem - 100) / slp". arcpy.sa '
        'functions such as Con, Abs and Log are available by name.'),
      P("output_path", "str", REQUIRED, "Where to save the result raster."),
      P("add_to_map", "bool", True, "Add the result to the map."),
      MAP_NAME),

    T("sample_raster_values", "Raster",
      "Read raster cell values at map coordinates or at a point layer's features.",
      LAYER,
      P("points", "list[dict]", None,
        'Coordinates to sample, e.g. [{"x": 100.5, "y": 13.7}].'),
      P("point_layer", "str", None, "Point layer to sample at instead."),
      P("band", "str", None, "Band to read for multiband rasters."),
      P("limit", "int", 100, "Maximum points to sample from a layer."),
      MAP_NAME),

    T("zonal_statistics", "Raster",
      "Summarise raster values inside zone polygons and return the table. "
      "Requires the Spatial Analyst extension.",
      P("zone_layer", "str", REQUIRED, "Polygon layer defining the zones."),
      P("zone_field", "str", REQUIRED, "Field identifying each zone."),
      P("raster_layer", "str", REQUIRED, "Raster to summarise."),
      P("statistics_type", "str", "ALL",
        "ALL, MEAN, SUM, MINIMUM, MAXIMUM, MEDIAN, MAJORITY, ..."),
      P("output_table", "str", None, "Where to write the statistics table."),
      P("ignore_nodata", "str", "DATA", "DATA or NODATA."),
      MAP_NAME),

    # --- catalog -------------------------------------------------------------
    T("list_workspace_contents", "Catalog",
      "List the datasets inside a geodatabase or folder. Defaults to the "
      "project's default geodatabase.",
      P("workspace", "str", None, "Geodatabase or folder path."),
      P("wildcard", "str", None, 'Name filter, e.g. "road*".'),
      P("include_details", "bool", False,
        "Also describe each feature class (type, CRS, row count)."),
      P("limit", "int", 500, "Maximum names per category.")),

    T("list_folder", "Catalog",
      "List GIS files and subfolders on disk. Defaults to the project home "
      "folder.",
      P("folder", "str", None, "Folder to list."),
      P("pattern", "str", None, "Substring filter on the file name."),
      P("recursive", "bool", False, "Walk subfolders."),
      P("only_data", "bool", True, "Only list recognised GIS/data files."),
      P("limit", "int", 500, "Maximum entries to return.")),

    T("describe_dataset", "Catalog",
      "Describe any dataset by path -- type, geometry, CRS, extent, fields and "
      "row count -- without adding it to a map.",
      P("path", "str", REQUIRED, "Dataset path.")),

    T("search_data", "Catalog",
      "Find datasets by name across the project's geodatabase, home folder and "
      "folder connections. The quickest way to locate data before adding it.",
      P("name", "str", None, "Substring to search for."),
      P("workspaces", "list[str]", None, "Restrict the search to these workspaces."),
      P("limit", "int", 100, "Maximum matches to return.")),

    T("get_project_items", "Catalog",
      "Folder connections, database connections and toolboxes registered in "
      "the project."),

    T("add_folder_connection", "Catalog",
      "Register a folder with the project so its data is easy to browse.",
      P("folder", "str", REQUIRED, "Folder path."),
      P("alias", "str", None, "Display name.")),

    # --- metadata ------------------------------------------------------------
    T("get_metadata", "Metadata",
      "Read a dataset's metadata record: the current metadata style plus "
      "title, summary, description, tags, credits, access constraints and "
      "use limitations. Works on feature classes, tables, rasters and "
      "geodatabases.",
      P("source", "str", REQUIRED, "Dataset or geodatabase path.")),

    T("set_metadata", "Metadata",
      "Write metadata fields on a dataset or geodatabase, optionally "
      "upgrading the record to the ISO 19139 style first. Field names may be "
      "given in English or Spanish.",
      P("source", "str", REQUIRED, "Dataset or geodatabase path."),
      P("fields", "dict", REQUIRED,
        'Metadata fields and values, e.g. {"title": "Coberturas 2009", '
        '"tags": "coberturas,clc"}.'),
      P("estilo_iso19139", "bool", True,
        "Upgrade the record to the ISO 19139 style before applying fields."),
      destructive=True),

    T("export_metadata_iso19139", "Metadata",
      "Export a dataset's metadata record to an ISO 19139 XML file.",
      P("source", "str", REQUIRED, "Dataset or geodatabase path."),
      P("out_path", "str", REQUIRED, "Output .xml file path.")),

    T("set_metadata_from_table", "Metadata",
      "Apply metadata to one or many datasets from a CSV/XLSX reference "
      "table. Two shapes are recognised: a campo|valor form for a single "
      "dataset (pass 'source'), and a batch table with a dataset column plus "
      "one metadata column per field.",
      P("table_path", "str", REQUIRED, "CSV or XLSX reference table path."),
      P("source", "str", None,
        "Dataset path when the table is a single-dataset form."),
      P("estilo_iso19139", "bool", True,
        "Upgrade each record to the ISO 19139 style first."),
      destructive=True),

    # --- utility -------------------------------------------------------------
    T("execute_arcpy_code", "Utility",
      "Run Python inside ArcGIS Pro. arcpy is already imported and "
      "arcpy.mp.ArcGISProject('CURRENT') is the open project. Variables "
      "persist between calls, print() output is captured, and the value of a "
      "final expression is returned. Use this whenever no dedicated tool "
      "covers the task.",
      P("code", "str", REQUIRED, "Python source to run."),
      P("reset_namespace", "bool", False,
        "Forget variables kept from earlier calls.")),

    T("get_pump_status", "Utility",
      "Whether the main-thread dispatcher is installed. It is what lets "
      "commands reach the open ArcGIS Pro project; without it only path-based "
      "work (geoprocessing, dataset inspection) runs."),

    T("stop_pump", "Utility",
      "Remove the main-thread dispatcher. Live-project commands stop working "
      "until the user installs it again."),

    T("run_batch", "Utility",
      "Run several commands in one round trip -- much faster for multi-step "
      "workflows.",
      P("commands", "list[dict]", REQUIRED,
        'e.g. [{"command": "set_layer_visibility", "params": {"layer_name": '
        '"roads", "visible": true}}].'),
      P("continue_on_error", "bool", False,
        "Keep going after a failed step instead of stopping.")),
]

BY_NAME = {tool.name: tool for tool in CATALOG}


def groups() -> Dict[str, List[Tool]]:
    out: Dict[str, List[Tool]] = {}
    for tool in CATALOG:
        out.setdefault(tool.group, []).append(tool)
    return out
