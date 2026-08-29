"""Regenerate the tool tables in README.md from the catalog.

Run after adding or changing a tool:

    python scripts/gen_tool_docs.py

The tables live between the <!-- TOOLS:START --> / <!-- TOOLS:END --> markers.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arcgis_pro_mcp.catalog import CATALOG, groups  # noqa: E402

START = "<!-- TOOLS:START -->"
END = "<!-- TOOLS:END -->"

GROUP_TITLES = {
    "Session": "Session and project",
    "Layers": "Layer",
    "Data": "Attributes and editing",
    "Selection": "Selection",
    "Schema": "Schema and dataset creation",
    "Geoprocessing": "Geoprocessing",
    "Symbology": "Symbology and labels",
    "View": "Map view and bookmarks",
    "Layouts": "Layouts and printing",
    "Raster": "Raster",
    "Catalog": "Finding and inspecting data",
    "Utility": "Escape hatch",
}


def summary(tool):
    text = tool.description.split(". ")[0].rstrip(".")
    return text.replace("|", "\\|")


def render():
    lines = [START, ""]
    lines.append(f"**{len(CATALOG)} tools.** Anything not listed is still reachable "
                 "through `run_geoprocessing_tool` or `execute_arcpy_code`.")
    for group, tools in groups().items():
        lines.append("")
        lines.append(f"### {GROUP_TITLES.get(group, group)} ({len(tools)})")
        lines.append("")
        lines.append("| Tool | What it does |")
        lines.append("|---|---|")
        for tool in tools:
            mark = " ⚠️" if tool.destructive else ""
            image = " 🖼️" if tool.returns_image else ""
            lines.append(f"| `{tool.name}`{mark}{image} | {summary(tool)} |")
    lines.append("")
    lines.append("⚠️ = changes or deletes real data &nbsp;&nbsp; "
                 "🖼️ = returns an image the AI can look at")
    lines.append("")
    lines.append(END)
    return "\n".join(lines)


def main():
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(
            f"Markers {START} / {END} not found in README.md -- add them first."
        )
    before = text.split(START)[0]
    after = text.split(END, 1)[1]
    readme.write_text(before + render() + after, encoding="utf-8")
    print(f"README.md updated with {len(CATALOG)} tools")


if __name__ == "__main__":
    main()
