"""Dump every geoprocessing tool's parameter order for the C# add-in.

ArcGIS Pro's .NET API runs tools by position only, and exposes no way to ask
a tool what its parameters are called. arcpy does know, so the ordering is
taken from it once, here, and embedded in the add-in as a resource. That is
what lets run_geoprocessing_tool accept the named parameters everything else
in this project uses.

Run with ArcGIS Pro's Python:

    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" \\
        scripts/dump_gp_parameters.py
"""

import json
import pathlib
import sys

OUTPUT = pathlib.Path(__file__).resolve().parents[1] / "addin" / "ArcGISProMCP" \
    / "Resources" / "gp-parameters.json"


def main() -> int:
    try:
        import arcpy
    except ImportError:
        print("This must run with ArcGIS Pro's Python (arcpy is required).")
        return 1

    tools = sorted(arcpy.ListTools("*"))
    print(f"{len(tools)} tools reported by arcpy")

    catalogue = {}
    skipped = 0
    for tool in tools:
        try:
            parameters = arcpy.GetParameterInfo(tool)
        except Exception:
            skipped += 1
            continue
        names = [p.name for p in parameters]
        if not names:
            continue
        # "Buffer_analysis" -> "analysis.Buffer", the form the tools are called
        # by everywhere else in this project.
        if "_" in tool:
            name, _, alias = tool.rpartition("_")
            catalogue[f"{alias}.{name}"] = names
        catalogue[tool] = names

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(catalogue, separators=(",", ":"), sort_keys=True),
        encoding="utf-8")

    size_kb = OUTPUT.stat().st_size / 1024
    print(f"{len(catalogue)} entries -> {OUTPUT} ({size_kb:.0f} KB)")
    print("arcpy often segfaults as it shuts down after this; the file above is "
          "already written, so a non-zero exit code here is not a failure.")
    if skipped:
        print(f"{skipped} tools could not be inspected and were left out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
