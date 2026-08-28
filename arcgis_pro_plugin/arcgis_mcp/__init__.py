# -*- coding: utf-8 -*-
"""ArcGIS Pro MCP bridge handlers.

Importing this package registers every command with the registry. Handler
modules are named h_<area>.py and register themselves with @command.
"""

import importlib

from .registry import HANDLERS, describe_commands, get_handler  # noqa: F401

# "pump" is deliberately absent: it holds live state and must survive reloads.
HANDLER_MODULES = (
    "common",
    "h_project",
    "h_layers",
    "h_data",
    "h_schema",
    "h_selection",
    "h_geoprocessing",
    "h_symbology",
    "h_layout",
    "h_view",
    "h_raster",
    "h_catalog",
    "h_code",
    "h_pump",
)


def _import_all():
    for name in HANDLER_MODULES:
        importlib.import_module("." + name, __name__)


def reload_all():
    """Re-import every handler module so code edits take effect without
    restarting ArcGIS Pro."""
    from . import registry
    # Keep the registry module object (and its dicts) identical so references
    # held elsewhere stay valid; only the handler modules are re-executed.
    registry.HANDLERS.clear()
    registry.GROUPS.clear()
    for name in HANDLER_MODULES:
        module = importlib.import_module("." + name, __name__)
        importlib.reload(module)
    return len(registry.HANDLERS)


_import_all()
