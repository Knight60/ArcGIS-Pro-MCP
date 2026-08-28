"""Command line entry point.

    python -m arcgis_pro_mcp             run the MCP server over stdio
    python -m arcgis_pro_mcp doctor      check the connection to ArcGIS Pro
    python -m arcgis_pro_mcp tools       print the tool catalog
    python -m arcgis_pro_mcp setup       print client configuration snippets
    python -m arcgis_pro_mcp stop-pump   remove the main-thread dispatcher
"""

import json
import os
import sys


def _autostart_status() -> str:
    """Whether install.ps1 set up the hook that starts the bridge with Pro."""
    state_dir = os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "ArcGIS-MCP")
    config_path = os.path.join(state_dir, "autostart.json")
    if not os.path.exists(config_path):
        return ("not installed (run install.ps1 from an elevated PowerShell, "
                "or start the bridge from the ArcGIS MCP toolbox)")
    try:
        with open(config_path, encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        return f"config unreadable: {type(exc).__name__}: {exc}"
    if not config.get("enabled", True):
        return "disabled in autostart.json"
    log_path = os.path.join(state_dir, "autostart.log")
    last = ""
    try:
        with open(log_path, encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
        if lines:
            last = f" | last log: {lines[-1]}"
    except OSError:
        pass
    return f"enabled, plugin_dir={config.get('plugin_dir')}{last}"


def _doctor() -> int:
    from .catalog import CATALOG
    from .connection import (INSTANCE_DIR, SETUP_HINT, ArcGISProNotAvailable,
                             candidate_endpoints, describe_instances,
                             get_connection)

    print("ArcGIS Pro MCP -- connection check")
    print("=" * 46)
    print(f"MCP tools available   : {len(CATALOG)}")
    print(f"Instance registry     : {INSTANCE_DIR}")

    print(f"Auto-start            : {_autostart_status()}")

    instances = describe_instances()
    if instances:
        for inst in instances:
            print(f"Registered bridge     : {inst.get('host')}:{inst.get('port')} "
                  f"pid {inst.get('pid')} -- "
                  f"{inst.get('project_path') or 'unsaved project'}")
    else:
        print("Registered bridge     : none found")
    print("Endpoints to try      : "
          + ", ".join(f"{h}:{p}" for h, p in candidate_endpoints()))
    print()

    try:
        response = get_connection().send_command("diagnose", {})
    except ArcGISProNotAvailable as exc:
        print(f"FAILED: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}")
        print(SETUP_HINT)
        return 1

    if not response.get("success"):
        print(f"Bridge reported an error: {response.get('error')}")
        return 1

    report = response["data"]
    for check in report.get("checks", []):
        mark = "ok  " if check["status"] == "ok" else "WARN"
        detail = check.get("result") if check["status"] == "ok" else check.get("error")
        print(f"[{mark}] {check['check']}: {detail}")
    print()
    print(f"Bridge commands: {report.get('command_count')}")
    print("Connection is working." if report.get("ok")
          else "Connected, but some checks need attention (see above).")
    return 0 if report.get("ok") else 2


def _stop_pump() -> int:
    """Hand ArcGIS Pro's Python window back to the user."""
    from .connection import ArcGISProNotAvailable, get_connection
    try:
        response = get_connection().send_command("stop_pump", {})
    except ArcGISProNotAvailable as exc:
        print(f"FAILED: {exc}")
        return 1
    if not response.get("success"):
        print(f"Bridge reported an error: {response.get('error')}")
        return 1
    print(response["data"].get("message", "Done."))
    return 0


def _tools() -> int:
    from .catalog import groups
    total = 0
    for group, tools in groups().items():
        print(f"\n{group}")
        print("-" * len(group))
        for tool in tools:
            total += 1
            summary = tool.description.split(". ")[0].rstrip(".")
            flag = " [destructive]" if tool.destructive else ""
            print(f"  {tool.name:<30} {summary}{flag}")
    print(f"\n{total} tools")
    return 0


def _setup() -> int:
    plugin_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "arcgis_pro_plugin")
    config = {"mcpServers": {"arcgis": {"command": sys.executable,
                                        "args": ["-m", "arcgis_pro_mcp"]}}}
    print("1) In ArcGIS Pro: Catalog > Toolboxes > Add Toolbox >")
    print(f"   {os.path.join(plugin_dir, 'ArcGISMCP.pyt')}")
    print("   then run 'Start MCP Server'.")
    print()
    print("   Or paste this into the ArcGIS Pro Python window:")
    print(f'   import sys; sys.path.insert(0, r"{plugin_dir}")')
    print("   import mcp_bridge; print(mcp_bridge.start_server())")
    print()
    print("2) In the ArcGIS Pro Python window, install the dispatcher.")
    print("   Pro only exposes the open project to its own main thread, so this")
    print("   It returns immediately and does not tie the window up.")
    print("   import mcp_bridge; mcp_bridge.start_pump()")
    print()
    print("3) Register with your AI client.")
    print("   Claude Code:")
    print(f"     claude mcp add arcgis --scope user -- \"{sys.executable}\" "
          "-m arcgis_pro_mcp")
    print("   Claude Code / Gemini CLI JSON config:")
    print(json.dumps(config, indent=2))
    print("   Codex CLI (~/.codex/config.toml):")
    print("     [mcp_servers.arcgis]")
    print(f'     command = "{sys.executable}"'.replace("\\", "\\\\"))
    print('     args = ["-m", "arcgis_pro_mcp"]')
    print()
    print("4) Verify with: python -m arcgis_pro_mcp doctor")
    return 0


def main() -> None:
    command = sys.argv[1].lower().lstrip("-") if len(sys.argv) > 1 else ""
    if command in ("doctor", "check", "diagnose"):
        raise SystemExit(_doctor())
    if command in ("stop-pump", "stoppump"):
        raise SystemExit(_stop_pump())
    if command in ("tools", "list", "list-tools"):
        raise SystemExit(_tools())
    if command in ("setup", "config", "install"):
        raise SystemExit(_setup())
    if command in ("help", "h", "?"):
        print(__doc__)
        raise SystemExit(0)
    if command:
        print(f"Unknown command: {sys.argv[1]}\n")
        print(__doc__)
        raise SystemExit(2)

    from .server import main as run_server
    run_server()


if __name__ == "__main__":
    main()
