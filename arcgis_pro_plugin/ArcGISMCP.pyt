# -*- coding: utf-8 -*-
"""ArcGIS Pro MCP toolbox -- start/stop the MCP bridge server inside ArcGIS Pro."""

import importlib
import os
import sys

import arcpy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import arcgis_mcp  # noqa: E402
import mcp_bridge  # noqa: E402

importlib.reload(mcp_bridge)  # pick up edits; running server survives in builtins


class Toolbox(object):
    def __init__(self):
        self.label = "ArcGIS MCP"
        self.alias = "arcgismcp"
        self.tools = [StartMCPServer, StopMCPServer, MCPServerStatus,
                      ReloadMCPHandlers]


class StartMCPServer(object):
    def __init__(self):
        self.label = "Start MCP Server"
        self.description = (
            "Start the MCP bridge server so AI assistants (Claude Code, Codex, "
            "Gemini CLI) can control this ArcGIS Pro session."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        port = arcpy.Parameter(
            displayName="Port",
            name="port",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        port.value = mcp_bridge.DEFAULT_PORT

        auto_port = arcpy.Parameter(
            displayName="Use the next free port if this one is taken",
            name="auto_port",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        auto_port.value = True
        return [port, auto_port]

    def execute(self, parameters, messages):
        auto_port = True if parameters[1].value is None else bool(parameters[1].value)
        message = mcp_bridge.start_server(port=parameters[0].value,
                                          auto_port=auto_port)
        messages.addMessage(message)
        messages.addMessage(
            "Keep ArcGIS Pro open -- the server stops when Pro is closed."
        )
        messages.addMessage(
            "The AI client finds this bridge automatically via {}".format(
                mcp_bridge.INSTANCE_DIR)
        )


class StopMCPServer(object):
    def __init__(self):
        self.label = "Stop MCP Server"
        self.description = "Stop the MCP bridge server."
        self.canRunInBackground = False

    def getParameterInfo(self):
        return []

    def execute(self, parameters, messages):
        messages.addMessage(mcp_bridge.stop_server())


class MCPServerStatus(object):
    def __init__(self):
        self.label = "MCP Server Status"
        self.description = (
            "Check whether the bridge is running and run a self-diagnosis of the "
            "current project."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        return []

    def execute(self, parameters, messages):
        messages.addMessage(mcp_bridge.server_status())
        state_dir = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "ArcGIS-MCP")
        if os.path.exists(os.path.join(state_dir, "autostart.json")):
            messages.addMessage(
                "Auto-start is installed -- the bridge comes up on its own when "
                "ArcGIS Pro opens a project. Log: {}".format(
                    os.path.join(state_dir, "autostart.log")))
        else:
            messages.addMessage(
                "Auto-start is not installed. Run install.ps1 from an elevated "
                "PowerShell to have the bridge start with ArcGIS Pro.")
        try:
            from arcgis_mcp.registry import HANDLERS
            report = HANDLERS["diagnose"]({})
            for check in report["checks"]:
                if check["status"] == "ok":
                    messages.addMessage("[ok]   {}: {}".format(
                        check["check"], check.get("result")))
                else:
                    messages.addWarningMessage("[warn] {}: {}".format(
                        check["check"], check.get("error")))
        except Exception as exc:
            messages.addWarningMessage("Diagnosis failed: {}".format(exc))


class ReloadMCPHandlers(object):
    def __init__(self):
        self.label = "Reload MCP Handlers"
        self.description = (
            "Re-import the handler modules after editing them, without "
            "restarting ArcGIS Pro or dropping the running server."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        return []

    def execute(self, parameters, messages):
        importlib.reload(arcgis_mcp)
        messages.addMessage(mcp_bridge.reload_handlers())
