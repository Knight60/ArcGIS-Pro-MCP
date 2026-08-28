# -*- coding: utf-8 -*-
"""Escape hatches: arbitrary code, batched commands, self-diagnosis."""

import ast
import contextlib
import io
import os
import sys
import time
import traceback

import arcpy

from . import pump
from .common import project
from .registry import HANDLERS, command

GROUP = "utility"

# Variables assigned by execute_arcpy_code persist between calls so multi-step
# work does not have to be squeezed into one snippet.
_SESSION_NAMESPACE = {"arcpy": arcpy}


@command("execute_arcpy_code", GROUP)
def execute_arcpy_code(params):
    """Run Python inside ArcGIS Pro. arcpy is imported; variables persist between
    calls. The value of the last expression is returned automatically, and
    print() output is captured."""
    code = params["code"]
    if params.get("reset_namespace"):
        _SESSION_NAMESPACE.clear()
        _SESSION_NAMESPACE["arcpy"] = arcpy
    namespace = _SESSION_NAMESPACE
    namespace.setdefault("project", project)

    buffer = io.StringIO()
    last_value = None
    started = time.time()
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError("SyntaxError in code: {}".format(exc))

    body = list(tree.body)
    tail = None
    if body and isinstance(body[-1], ast.Expr):
        tail = ast.Expression(body.pop().value)

    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        if body:
            exec(compile(ast.Module(body, type_ignores=[]), "<mcp>", "exec"),
                 namespace)
        if tail is not None:
            last_value = eval(compile(tail, "<mcp>", "eval"), namespace)

    output = buffer.getvalue()
    result = {"elapsed_seconds": round(time.time() - started, 3)}
    if output:
        result["output"] = output
    if last_value is not None:
        result["value"] = repr(last_value)[:20000]
    if not output and last_value is None:
        result["output"] = "(no output -- print() or end with an expression to " \
                           "return a value)"
    result["variables"] = sorted(
        k for k, v in namespace.items()
        if not k.startswith("_") and not callable(v) and k not in ("arcpy",)
    )[:100]
    return result


@command("run_batch", GROUP)
def run_batch(params):
    """Run several bridge commands in one round trip.

    commands: [{"command": "get_layers", "params": {}}, ...]
    Stops at the first failure unless continue_on_error is true.
    """
    commands = params.get("commands") or []
    if not commands:
        raise ValueError("commands is required (list of {command, params})")
    continue_on_error = bool(params.get("continue_on_error", False))
    results = []
    for step in commands:
        name = step.get("command")
        handler = HANDLERS.get(name)
        if handler is None:
            entry = {"command": name, "success": False,
                     "error": "Unknown command: {}".format(name)}
        else:
            try:
                entry = {"command": name, "success": True,
                         "data": handler(step.get("params") or {})}
            except Exception as exc:
                message = "{}: {}".format(type(exc).__name__, exc)
                if "CURRENT" in str(exc):
                    # Steps run inline here, so they miss the dispatcher's hint.
                    message += (". This step needs the live ArcGIS Pro project. "
                                "In the ArcGIS Pro Python window run: "
                                "import mcp_bridge; mcp_bridge.start_pump()")
                entry = {"command": name, "success": False, "error": message}
        results.append(entry)
        if not entry["success"] and not continue_on_error:
            break
    return {"executed": len(results),
            "all_succeeded": all(r["success"] for r in results),
            "results": results}


@command("diagnose", GROUP)
def diagnose(params):
    """Self-check: environment, project state and a dry run of the read-only
    commands. Run this first when something is not working."""
    report = {"checks": [], "ok": True}

    def check(name, fn):
        entry = {"check": name}
        try:
            entry["result"] = fn()
            entry["status"] = "ok"
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = "{}: {}".format(type(exc).__name__, exc)
            report["ok"] = False
        report["checks"].append(entry)

    def pump_check():
        state = pump.status()
        if not state.get("running"):
            raise RuntimeError(
                "The main-thread pump is not running, so commands cannot reach "
                "the open project. In the ArcGIS Pro Python window run:  "
                "import mcp_bridge; mcp_bridge.start_pump()"
            )
        return {"jobs_run": state.get("jobs_run"),
                "uptime_seconds": state.get("uptime_seconds")}

    check("main_thread_pump", pump_check)
    check("python", lambda: {"version": sys.version.split()[0],
                             "executable": sys.executable,
                             "pid": os.getpid()})
    check("arcgis_pro", lambda: {
        "version": arcpy.GetInstallInfo().get("Version"),
        "license": arcpy.ProductInfo(),
    })
    check("project", lambda: {
        "path": project().filePath,
        "default_gdb": project().defaultGeodatabase,
        "map_count": len(project().listMaps()),
    })

    def active_map_check():
        proj = project()
        active = proj.activeMap
        if active is None:
            raise RuntimeError(
                "No active map. Open a map tab in ArcGIS Pro, or pass map_name "
                "explicitly to each command."
            )
        return {"active_map": active.name, "layers": len(active.listLayers())}

    check("active_map", active_map_check)

    def view_check():
        m = project().activeMap
        if m is None or m.defaultView is None:
            raise RuntimeError(
                "No open map view -- export_map_view and camera commands need "
                "the map's tab to be open in ArcGIS Pro."
            )
        return {"scale": m.defaultView.camera.scale}

    check("map_view", view_check)
    check("write_access", lambda: {
        "home_folder_writable": os.access(project().homeFolder, os.W_OK)
    })
    report["command_count"] = len(HANDLERS)
    return report


@command("get_last_traceback", GROUP)
def get_last_traceback(params):
    """The most recent Python traceback raised inside the bridge."""
    return {"traceback": traceback.format_exc()}
