# -*- coding: utf-8 -*-
"""Command registry for the ArcGIS Pro MCP bridge.

Handler modules register themselves with the @command decorator, so adding a
new capability is a single decorated function -- no central dispatch table to
keep in sync.
"""

HANDLERS = {}
GROUPS = {}


def command(name, group="misc", summary=""):
    """Register a bridge command.

    The decorated function takes a single ``params`` dict and returns any
    JSON-serialisable value.
    """
    def decorator(fn):
        HANDLERS[name] = fn
        GROUPS[name] = group
        fn.mcp_command = name
        fn.mcp_group = group
        fn.mcp_summary = summary or (fn.__doc__ or "").strip().split("\n")[0]
        return fn
    return decorator


def get_handler(name):
    return HANDLERS.get(name)


def describe_commands():
    """Every registered command, grouped -- used by get_capabilities."""
    out = {}
    for name, fn in sorted(HANDLERS.items()):
        out.setdefault(GROUPS.get(name, "misc"), []).append({
            "command": name,
            "summary": getattr(fn, "mcp_summary", ""),
        })
    return out
