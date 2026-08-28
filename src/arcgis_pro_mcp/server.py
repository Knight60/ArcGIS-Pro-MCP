"""ArcGIS Pro MCP server (stdio).

Exposes MCP tools to AI assistants (Claude Code, Codex, Gemini CLI) and relays
each call to the MCP bridge running inside ArcGIS Pro over a local TCP socket.

The tools themselves are generated from ``catalog.py`` so that the tool list,
its documentation and the bridge's handlers stay in step.
"""

from __future__ import annotations

import base64
import json
import textwrap
from typing import Annotated, Any, Optional  # noqa: F401 -- used by generated code

from mcp.server.fastmcp import FastMCP, Image
from pydantic import Field  # noqa: F401 -- used by generated code

from .catalog import CATALOG, Tool, groups
from .connection import ArcGISProNotAvailable, describe_instances, get_connection

INSTRUCTIONS = """\
Control a live ArcGIS Pro session through arcpy.

Setup has two parts, both inside ArcGIS Pro, and neither can be done from
here -- ask the user if either is missing:
  1. the bridge ('Start MCP Server' in the ArcGIS MCP toolbox, or auto-start);
  2. the main-thread dispatcher. ArcGIS Pro only exposes the open project to
     its own main thread, so the user installs a dispatcher there once per
     session, with a one-liner in the ArcGIS Pro Python window that returns
     immediately:
         import mcp_bridge; mcp_bridge.start_pump()
     Without it, path-based work (geoprocessing, describe_dataset,
     list_workspace_contents) still runs, but anything reading or changing the
     open project fails. get_pump_status and diagnose report this.

Getting oriented: get_project_info and get_layers show what is open;
search_data and list_workspace_contents find data that is not in a map yet;
diagnose explains why something is not working.

Conventions: map_name is optional almost everywhere and defaults to the active
map. Anywhere a layer_name is accepted you may pass either a layer in the map
or a full dataset path. Layer names must match get_layers exactly (layers
inside a group use the long name, "Group\\Layer").

Anything not covered by a named tool is still reachable:
run_geoprocessing_tool runs any of the ~2000 arcpy tools (use
describe_geoprocessing_tool to learn a tool's parameters first), and
execute_arcpy_code runs arbitrary Python inside Pro. get_capabilities lists
every command the connected bridge supports.

Working on real data: these tools edit the user's open project. Prefer
non-destructive steps, use save_project deliberately, and confirm before bulk
edits or deletes. export_map_view and preview_layout return images, so the map
can be checked visually after a change.
"""

mcp = FastMCP("ArcGIS Pro MCP", instructions=INSTRUCTIONS)


# --- transport ---------------------------------------------------------------

def _send(command: str, params: dict) -> dict:
    """Send one command, returning the decoded bridge response."""
    params = {k: v for k, v in params.items() if v is not None}
    return get_connection().send_command(command, params)


def _call(command: str, **params: Any) -> str:
    try:
        response = _send(command, params)
    except ArcGISProNotAvailable as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001 -- surface transport errors to the agent
        return f"Error communicating with ArcGIS Pro: {type(exc).__name__}: {exc}"
    if not response.get("success"):
        return _format_error(command, response)
    return json.dumps(response.get("data"), ensure_ascii=False, indent=2, default=str)


def _call_image(command: str, **params: Any) -> Any:
    """Like _call, but hands back rendered PNG/JPEG output as a real image."""
    try:
        response = _send(command, params)
    except ArcGISProNotAvailable as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"Error communicating with ArcGIS Pro: {type(exc).__name__}: {exc}"
    if not response.get("success"):
        return _format_error(command, response)

    data = dict(response.get("data") or {})
    encoded = data.pop("image_base64", None)
    image_format = data.pop("image_format", "png")
    summary = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if not encoded:
        return summary
    return [summary, Image(data=base64.b64decode(encoded), format=image_format)]


def _format_error(command: str, response: dict) -> str:
    error = response.get("error", "unknown error")
    message = f"ArcGIS Pro error in {command}: {error}"
    hint = _hint_for(error)
    if hint:
        message += f"\nHint: {hint}"
    return message


def _hint_for(error: str) -> Optional[str]:
    lowered = str(error).lower()
    if "layer not found" in lowered or "no layer or table" in lowered:
        return "Call get_layers to see the exact layer names in the map."
    if "pump" in lowered or "current" in lowered:
        return ("The main-thread dispatcher is not installed. Ask the user "
                "to run this once in the ArcGIS Pro Python window (it returns "
                "immediately):  import mcp_bridge; mcp_bridge.start_pump()")
    if "unknown command" in lowered:
        return ("This bridge is older than the MCP server. Run 'Reload MCP "
                "Handlers' in the ArcGIS MCP toolbox, or restart ArcGIS Pro.")
    if "no open view" in lowered or "has no view" in lowered:
        return ("Open the map's tab in ArcGIS Pro (or call activate_map) -- "
                "camera and export commands need an open view.")
    if "does not exist" in lowered or "cannot open" in lowered:
        return "Use search_data or list_workspace_contents to locate the dataset."
    if "already exists" in lowered:
        return ("Set overwrite=true on run_geoprocessing_tool, or choose a "
                "different output name.")
    if "license" in lowered or "extension" in lowered:
        return "Check the licence with check_extension before running this tool."
    return None


# --- tool generation ---------------------------------------------------------

TYPE_ANNOTATIONS = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "list": "list",
    "dict": "dict",
    "list[str]": "list[str]",
    "list[int]": "list[int]",
    "list[float]": "list[float]",
    "list[dict]": "list[dict]",
}


def _annotation(param) -> str:
    base = TYPE_ANNOTATIONS.get(param.type, "str")
    if not param.required and param.default is None:
        base = f"Optional[{base}]"
    return f"Annotated[{base}, Field(description={param.description!r})]"


def _signature(tool: Tool) -> str:
    ordered = ([p for p in tool.params if p.required]
               + [p for p in tool.params if not p.required])
    parts = []
    for param in ordered:
        piece = f"{param.name}: {_annotation(param)}"
        if not param.required:
            piece += f" = {param.default!r}"
        parts.append(piece)
    return ", ".join(parts)


def _build_source(tool: Tool) -> str:
    call = "_call_image" if tool.returns_image else "_call"
    kwargs = "".join(f", {p.name}={p.name}" for p in tool.params)
    doc = textwrap.fill(tool.description, 72).replace("\\", "\\\\")
    body_return = "" if tool.returns_image else " -> str"
    return (
        f"def {tool.name}({_signature(tool)}){body_return}:\n"
        f'    """{doc}"""\n'
        f'    return {call}("{tool.name}"{kwargs})\n'
    )


def _register_tools() -> int:
    namespace: dict = {
        "_call": _call, "_call_image": _call_image,
        "Optional": Optional, "Annotated": Annotated, "Field": Field,
        "Any": Any,
    }
    source = "\n".join(_build_source(tool) for tool in CATALOG)
    exec(compile(source, "<arcgis_pro_mcp.generated>", "exec"), namespace)
    for tool in CATALOG:
        mcp.add_tool(
            namespace[tool.name],
            name=tool.name,
            description=tool.description,
        )
    return len(CATALOG)


TOOL_COUNT = _register_tools()


# --- resources ---------------------------------------------------------------

@mcp.resource("arcgis://tools")
def tool_index() -> str:
    """The full tool list, grouped by area."""
    lines = [f"# ArcGIS Pro MCP -- {TOOL_COUNT} tools", ""]
    for group, tools in groups().items():
        lines.append(f"## {group}")
        for tool in tools:
            first_line = tool.description.split(". ")[0].rstrip(".")
            lines.append(f"- **{tool.name}** -- {first_line}")
        lines.append("")
    return "\n".join(lines)


@mcp.resource("arcgis://status")
def status() -> str:
    """Whether ArcGIS Pro is reachable right now, and which projects are open."""
    instances = describe_instances()
    lines = ["# ArcGIS Pro bridge status", ""]
    if instances:
        for inst in instances:
            lines.append(
                "- {host}:{port} -- {project} (pid {pid})".format(
                    host=inst.get("host"), port=inst.get("port"),
                    project=inst.get("project_path") or "unsaved project",
                    pid=inst.get("pid"))
            )
    else:
        lines.append("- No bridge registered. Open ArcGIS Pro and run "
                     "'Start MCP Server' from the ArcGIS MCP toolbox.")
    lines.append("")
    lines.append(_call("ping"))
    return "\n".join(lines)


@mcp.resource("arcgis://project")
def project_summary() -> str:
    """A snapshot of the open project: maps, layers and layouts."""
    return _call("get_project_info")


# --- prompts -----------------------------------------------------------------

@mcp.prompt()
def explore_project() -> str:
    """Survey the open ArcGIS Pro project and summarise what is in it."""
    return (
        "Survey the ArcGIS Pro project that is currently open:\n"
        "1. Call get_project_info, then get_layers.\n"
        "2. For each data layer, call get_layer_info for the geometry type, "
        "coordinate system and feature count.\n"
        "3. Flag anything that looks wrong: broken sources (get_broken_layers), "
        "mixed coordinate systems, empty layers.\n"
        "4. Finish with a short summary table and suggest what analysis the "
        "data supports."
    )


@mcp.prompt()
def make_map(subject: str, style: str = "clean and print-ready") -> str:
    """Build a finished, exportable map of a subject."""
    return (
        f"Produce a {style} map of: {subject}.\n"
        "1. get_layers to see what is available; search_data if the data is "
        "not in the map yet.\n"
        "2. Symbolise the relevant layers with set_layer_renderer, and label "
        "them with set_layer_labeling.\n"
        "3. Set a suitable basemap and zoom with zoom_to_layer or set_map_view.\n"
        "4. Call export_map_view and actually look at the returned image; "
        "adjust colours, scale and labels until it reads well.\n"
        "5. Build a layout: create_layout, add_layout_legend, "
        "add_layout_scale_bar, add_layout_north_arrow and add_layout_text for "
        "the title.\n"
        "6. preview_layout to check it, then export_layout to PDF.\n"
        "Report each choice you made so it can be adjusted."
    )


@mcp.prompt()
def analyze(question: str) -> str:
    """Answer a spatial question with the data in the open project."""
    return (
        f"Answer this question using the open ArcGIS Pro project: {question}\n"
        "1. Inspect the data first (get_layers, get_layer_info, list_fields).\n"
        "2. Prefer reading tools -- summarize_features, get_field_statistics, "
        "select_by_location -- before creating new datasets.\n"
        "3. When geoprocessing is needed, call describe_geoprocessing_tool to "
        "confirm the parameters, then run_geoprocessing_tool.\n"
        "4. Write outputs to the project's default geodatabase with clear "
        "names, and say which ones you created.\n"
        "5. Give the answer with the numbers that support it, and note any "
        "assumptions (coordinate system, units, filters)."
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
