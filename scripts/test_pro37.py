"""Exercise a loaded 1.1.1 add-in over the official MCP Python HTTP client.

Open a disposable project first. Creates a uniquely named map, layout and file
geodatabase under --output. Does not modify pre-existing layers or datasets.
Requires the repository's mcp<2 dependency. No stdio relay or Python fallback.
"""
import argparse
import asyncio
import json
import pathlib
import uuid
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def run(output):
    output.mkdir(parents=True, exist_ok=False)
    suffix = uuid.uuid4().hex[:8]
    map_name = "MCP_Test_" + suffix
    layout_name = "MCP_Layout_" + suffix
    evidence = {"checks": [], "output": str(output)}
    async with streamablehttp_client("http://127.0.0.1:6520/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.version == "1.1.1.0", initialized.serverInfo
            evidence["server"] = initialized.serverInfo.model_dump()
            tools = await session.list_tools()
            assert len(tools.tools) == 112

            async def call(name, **args):
                result = await session.call_tool(name, args)
                assert not result.isError, (name, result.content)
                data = json.loads(next(c.text for c in result.content if c.type == "text"))
                evidence["checks"].append({"tool": name, "result": data})
                print("PASS", name, flush=True)
                return data

            info = await call("get_arcgis_info")
            assert info["version"].startswith("3.7.")
            project = await call("get_project_info")
            # Prevent accidental mutation of a user's ordinary project.
            assert "artifacts" in pathlib.Path(project["path"]).parts, "Open a test project under artifacts first"
            await call("create_map", name=map_name, basemap="NONE")
            await call("create_file_geodatabase", name="smoke.gdb", folder=str(output))
            gdb = output / "smoke.gdb"
            await call("create_feature_class", name="smoke_points", geometry_type="POINT",
                       epsg=4326, out_path=str(gdb), map_name=map_name,
                       fields=[{"name": "NAME", "type": "TEXT", "length": 30}])
            await call("insert_features", layer_name="smoke_points", map_name=map_name,
                       features=[{"attributes": {"NAME": "HTTP test"}, "geometry": [100, 15]}], save_edits=True)
            counted = await call("count_features", layer_name="smoke_points", map_name=map_name)
            assert counted["count"] == 1, counted
            await call("get_features", layer_name="smoke_points", map_name=map_name)
            await call("select_features", layer_name="smoke_points", where="NAME = 'HTTP test'", map_name=map_name)
            await call("set_layer_renderer", layer_name="smoke_points", color=[30, 120, 220], map_name=map_name)
            await call("run_geoprocessing_tool", tool_name="management.GetCount",
                       parameters={"in_rows": str(gdb / "smoke_points")})
            await call("run_geoprocessing_tool", tool_name="management.GetCount",
                       args=[str(gdb / "smoke_points")])
            await call("create_layout", name=layout_name, map_name=map_name)
            await call("export_layout", layout_name=layout_name, output_path=str(output / "layout.pdf"), dpi=96)
            assert (output / "layout.pdf").stat().st_size > 100
            await call("save_project")
    (output / "results.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print("All Pro 3.7 HTTP runtime checks passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    asyncio.run(run(parser.parse_args().output.resolve()))
