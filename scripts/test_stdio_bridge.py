"""Drive the generated stdio bridge the way a launching client does.

Claude Desktop can only start a server and talk to it over stdin/stdout, so the
add-in writes a PowerShell bridge and points the client at that. This runs the
official MCP stdio client against that exact file, with ArcGIS Pro open, and is
the only test that exercises the path Claude Desktop actually takes.

    python scripts/test_stdio_bridge.py --expected-version 1.1.1.0
"""
import argparse
import asyncio
import os
import pathlib
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def bridge_path():
    return pathlib.Path(os.environ["LOCALAPPDATA"]) / "ArcGIS Pro MCP" / "stdio-bridge.ps1"


def powershell():
    return str(pathlib.Path(os.environ["SystemRoot"]) / "System32"
               / "WindowsPowerShell" / "v1.0" / "powershell.exe")


async def run(expected_version):
    script = bridge_path()
    if not script.exists():
        raise SystemExit(
            f"No bridge at {script}. Register a stdio client from the MCP tab, "
            "or run the client-registration tests, to have the add-in write it.")

    parameters = StdioServerParameters(
        command=powershell(),
        args=["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            info = initialized.serverInfo
            if expected_version and info.version != expected_version:
                raise SystemExit(f"FAIL bridge reached version {info.version}, "
                                 f"expected {expected_version}")
            print(f"PASS bridge initialize: {info.name} {info.version}")

            tools = await session.list_tools()
            if len(tools.tools) != 112:
                raise SystemExit(f"FAIL bridge listed {len(tools.tools)} tools, expected 112")
            print(f"PASS bridge tools/list ({len(tools.tools)} tools)")

            result = await session.call_tool("get_project_info", {})
            if result.isError:
                raise SystemExit(f"FAIL bridge tools/call: {result.content}")
            print("PASS bridge tools/call get_project_info (read only)")

            # A tool that does not exist has to come back as an error, not as a
            # dropped message that leaves the client waiting.
            failed = await session.call_tool("no_such_tool", {})
            if not failed.isError:
                raise SystemExit("FAIL bridge did not report an unknown tool as an error")
            print("PASS bridge reports a tool error rather than hanging")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version")
    arguments = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(run(arguments.expected_version))
