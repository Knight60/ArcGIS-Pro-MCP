# -*- coding: utf-8 -*-
"""Control the main-thread pump that gives commands access to the live project."""

from . import pump
from .registry import command

GROUP = "utility"

# These never need the live project, so the socket thread runs them directly
# and they keep answering even when no pump is running.
INLINE_COMMANDS = frozenset({
    "ping", "get_capabilities", "get_pump_status", "stop_pump",
})


@command("get_pump_status", GROUP)
def get_pump_status(params):
    """Whether the main-thread pump is running.

    The pump is what lets commands reach the open ArcGIS Pro project;
    without it only path-based work (geoprocessing, dataset inspection) runs.
    """
    data = pump.status()
    data["hint"] = (
        "Running -- live project commands work."
        if data.get("running") else
        "Not running. In the ArcGIS Pro Python window run:  "
        "import mcp_bridge; mcp_bridge.start_pump()"
    )
    return data


@command("stop_pump", GROUP)
def stop_pump(params):
    """Stop the main-thread dispatcher."""
    stopped = pump.stop()
    return {
        "stopped": stopped,
        "message": ("Dispatcher asked to stop."
                    if stopped else "No dispatcher was running."),
    }
