# -*- coding: utf-8 -*-
"""Start the ArcGIS Pro MCP bridge automatically when ArcGIS Pro launches.

install.ps1 copies this module into the ArcGIS Pro Python environment's
site-packages together with a .pth file that imports it, so Python runs it at
interpreter startup.

That means it runs in EVERY process using that environment -- background
geoprocessing workers, propy.bat scripts, Notebooks. It must therefore be
cheap and silent, and do nothing at all unless it is inside the ArcGIS Pro
application itself. Two guards enforce that:

  1. a fast check on the host executable name, before arcpy is imported;
  2. a check that arcpy.mp.ArcGISProject("CURRENT") resolves, which only
     succeeds inside the running app.

Anything that goes wrong is logged and swallowed -- this must never be able to
stop ArcGIS Pro from starting.
"""

import os
import sys
import threading
import time

STATE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "ArcGIS-MCP")
CONFIG_PATH = os.path.join(STATE_DIR, "autostart.json")
LOG_PATH = os.path.join(STATE_DIR, "autostart.log")

HOST_EXECUTABLES = ("arcgispro.exe",)
STARTUP_DELAY = 5.0      # let ArcGIS Pro finish booting before touching arcpy
RETRY_SECONDS = 180.0    # keep waiting this long for a project to open
RETRY_INTERVAL = 3.0
MAX_LOG_BYTES = 256 * 1024


def _log(message):
    try:
        if not os.path.isdir(STATE_DIR):
            os.makedirs(STATE_DIR)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_BYTES:
            os.remove(LOG_PATH)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write("{} [pid {}] {}\n".format(stamp, os.getpid(), message))
    except Exception:
        pass


def _config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        import json
        # utf-8-sig: PowerShell 5.1 writes UTF-8 with a BOM.
        with open(CONFIG_PATH, encoding="utf-8-sig") as handle:
            return json.load(handle)
    except Exception as exc:
        _log("could not read {}: {}: {}".format(
            CONFIG_PATH, type(exc).__name__, exc))
        return {}


def _in_arcgis_pro():
    if os.environ.get("ARCGIS_MCP_AUTOSTART_FORCE"):
        return True
    return os.path.basename(sys.executable or "").lower() in HOST_EXECUTABLES


def _start_when_ready(plugin_dir, port):
    time.sleep(STARTUP_DELAY)
    deadline = time.time() + RETRY_SECONDS
    while time.time() < deadline:
        try:
            import arcpy
            arcpy.mp.ArcGISProject("CURRENT")
        except Exception:
            time.sleep(RETRY_INTERVAL)
            continue
        try:
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)
            import mcp_bridge
            _log(mcp_bridge.start_server(port=port))
            _log("Commands that touch the open project also need the "
                 "main-thread dispatcher. Run this once in the ArcGIS Pro "
                 "Python window: import mcp_bridge; mcp_bridge.start_pump()")
        except Exception as exc:
            _log("could not start the bridge: {}: {}".format(
                type(exc).__name__, exc))
        return
    _log("no ArcGIS Pro project opened within {:.0f}s -- not starting. Use the "
         "ArcGIS MCP toolbox to start it manually.".format(RETRY_SECONDS))


def main():
    if not _in_arcgis_pro():
        return
    config = _config()
    if not config.get("enabled", True):
        _log("autostart is disabled in {}".format(CONFIG_PATH))
        return
    plugin_dir = config.get("plugin_dir")
    if not plugin_dir or not os.path.isdir(plugin_dir):
        _log("plugin_dir is missing or invalid in {}: {!r}".format(
            CONFIG_PATH, plugin_dir))
        return
    _log("ArcGIS Pro detected ({}) -- waiting for a project".format(
        sys.executable))
    thread = threading.Thread(
        target=_start_when_ready,
        args=(plugin_dir, int(config.get("port", 6510))),
        name="ArcGISMCPAutostart", daemon=True,
    )
    thread.start()


main()
