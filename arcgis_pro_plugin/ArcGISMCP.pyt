# -*- coding: utf-8 -*-
"""ArcGIS Pro MCP toolbox — start/stop the MCP bridge server inside ArcGIS Pro."""

import importlib
import os
import sys

import arcpy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mcp_bridge
importlib.reload(mcp_bridge)  # pick up edits; running server survives in builtins


class Toolbox(object):
    def __init__(self):
        self.label = "ArcGIS MCP"
        self.alias = "arcgismcp"
        self.tools = [StartMCPServer, StopMCPServer, MCPServerStatus]


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
        return [port]

    def execute(self, parameters, messages):
        message = mcp_bridge.start_server(port=parameters[0].value)
        messages.addMessage(message)
        messages.addMessage(
            "Keep ArcGIS Pro open. The server stops when Pro is closed."
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
        self.description = "Check whether the MCP bridge server is running."
        self.canRunInBackground = False

    def getParameterInfo(self):
        return []

    def execute(self, parameters, messages):
        messages.addMessage(mcp_bridge.server_status())
