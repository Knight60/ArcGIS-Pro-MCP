"""Export the MCP tool schemas for the add-in to serve over HTTP.

The add-in can speak MCP directly, which removes the separate Python process
from the setup. It still must not become a second place where tools are
defined, so the schemas come from the same catalog.py the Python server
generates its tools from, and are embedded in the add-in as a resource.

    python scripts/export_tool_schemas.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arcgis_pro_mcp.catalog import CATALOG  # noqa: E402

OUTPUT = ROOT / "addin" / "ArcGISProMCP" / "Resources" / "tools.json"

JSON_TYPES = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "dict": {"type": "object"},
    "list": {"type": "array"},
    "list[str]": {"type": "array", "items": {"type": "string"}},
    "list[int]": {"type": "array", "items": {"type": "integer"}},
    "list[float]": {"type": "array", "items": {"type": "number"}},
    "list[dict]": {"type": "array", "items": {"type": "object"}},
    "list[list]": {"type": "array", "items": {"type": "array"}},
}


def schema_for(tool):
    properties = {}
    required = []
    for param in tool.params:
        schema = dict(JSON_TYPES.get(param.type, {"type": "string"}))
        if param.description:
            schema["description"] = param.description
        if param.required:
            required.append(param.name)
        elif param.default is not None:
            schema["default"] = param.default
        properties[param.name] = schema

    input_schema = {"type": "object", "properties": properties}
    if required:
        input_schema["required"] = required
    return input_schema


def main() -> int:
    tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": schema_for(tool),
            # Read by the add-in so image results come back as image content.
            "returnsImage": tool.returns_image,
        }
        for tool in CATALOG
    ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"tools": tools}, separators=(",", ":")),
                      encoding="utf-8")
    print(f"{len(tools)} tool schemas -> {OUTPUT} "
          f"({OUTPUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
