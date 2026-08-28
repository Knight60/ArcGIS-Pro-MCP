# -*- coding: utf-8 -*-
"""
ArcGIS Pro MCP Bridge
=====================
Socket server that runs INSIDE ArcGIS Pro's Python runtime and executes arcpy
commands against the currently open project ("CURRENT").

It speaks newline-delimited JSON over TCP (localhost only):

    request : {"id": 1, "command": "get_layers", "params": {...}}\n
    response: {"id": 1, "success": true, "data": {...}}\n
    error   : {"id": 1, "success": false, "error": "message"}\n

Start it from the ArcGISMCP.pyt toolbox, or from the Pro Python window:

    import sys; sys.path.insert(0, r"<this folder>")
    import mcp_bridge; mcp_bridge.start_server()

Commands live in the arcgis_mcp package next to this file; each handler module
registers itself, so nothing here needs editing to add a capability.
"""

import builtins
import json
import os
import socket
import threading
import traceback

import arcgis_mcp
from arcgis_mcp import pump
from arcgis_mcp.h_pump import INLINE_COMMANDS
from arcgis_mcp.registry import HANDLERS

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6510
PORT_SEARCH_RANGE = 10
_REGISTRY_KEY = "_ARCGIS_MCP_BRIDGE"  # survives .pyt reloads

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
LOCK_TIMEOUT = 120.0  # seconds to wait for a busy bridge

INSTANCE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
    "ArcGIS-MCP", "instances",
)


# ---------------------------------------------------------------------------
# Instance discovery -- lets the MCP server find a running bridge automatically
# ---------------------------------------------------------------------------

def _instance_file(port):
    return os.path.join(INSTANCE_DIR, "bridge-{}.json".format(port))


def _write_instance_file(host, port):
    try:
        if not os.path.isdir(INSTANCE_DIR):
            os.makedirs(INSTANCE_DIR)
        project_path = None
        try:
            import arcpy
            project_path = arcpy.mp.ArcGISProject("CURRENT").filePath
        except Exception:
            pass
        payload = {
            "host": host,
            "port": port,
            "pid": os.getpid(),
            "project_path": project_path,
            "command_count": len(HANDLERS),
        }
        with open(_instance_file(port), "w") as handle:
            json.dump(payload, handle)
    except Exception:
        pass  # discovery is a convenience, never a hard requirement


def _remove_instance_file(port):
    try:
        os.remove(_instance_file(port))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Socket server
# ---------------------------------------------------------------------------

class BridgeServer(object):
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.host = host
        self.port = port
        self._server_socket = None
        self._thread = None
        self._running = False
        self._lock = threading.RLock()  # arcpy is not safe to call concurrently
        self.request_count = 0
        self.current_command = None
        self.last_error = None

    @property
    def running(self):
        return self._running

    def start(self, auto_port=True):
        if self._running:
            raise RuntimeError("Server already running on port {}".format(self.port))
        last_error = None
        ports = [self.port] + (
            list(range(self.port + 1, self.port + 1 + PORT_SEARCH_RANGE))
            if auto_port else []
        )
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((self.host, port))
            except OSError as exc:
                sock.close()
                last_error = exc
                continue
            sock.listen(5)
            self._server_socket = sock
            self.port = port
            break
        else:
            raise RuntimeError(
                "Could not bind a port in {}-{}: {}".format(
                    ports[0], ports[-1], last_error)
            )

        self._running = True
        self._thread = threading.Thread(
            target=self._serve, name="ArcGISMCPBridge", daemon=True
        )
        self._thread.start()
        _write_instance_file(self.host, self.port)

    def stop(self):
        self._running = False
        _remove_instance_file(self.port)
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

    def _serve(self):
        while self._running:
            try:
                client, _addr = self._server_socket.accept()
            except OSError:
                break  # socket closed by stop()
            worker = threading.Thread(
                target=self._client_loop, args=(client,),
                name="ArcGISMCPClient", daemon=True,
            )
            worker.start()

    def _client_loop(self, client):
        try:
            self._handle_client(client)
        except Exception:
            self.last_error = traceback.format_exc()
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _handle_client(self, client):
        buffer = b""
        while self._running:
            chunk = client.recv(65536)
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                response = self._dispatch(line)
                client.sendall(response.encode("utf-8") + b"\n")

    def _run(self, command_name, handler, params):
        """Run a command where it can actually reach the ArcGIS Pro session.

        Anything touching the open project has to execute on Pro's main
        thread, so it is handed to the pump. Commands that only need paths
        still work inline when no pump is running.
        """
        if command_name in INLINE_COMMANDS:
            return handler(params)
        if pump.is_running():
            return pump.submit(handler, params)
        # A timeout, not a plain `with`: one wedged command must not make the
        # whole bridge unresponsive.
        if not self._lock.acquire(timeout=LOCK_TIMEOUT):
            raise RuntimeError(
                "The bridge is still busy with '{}' after {:.0f}s, so '{}' was "
                "not run. If that command is stuck, restart ArcGIS Pro."
                .format(self.current_command or "an earlier command",
                        LOCK_TIMEOUT, command_name)
            )
        try:
            self.current_command = command_name
            return handler(params)
        except Exception as exc:
            if "CURRENT" in str(exc):
                raise RuntimeError(
                    "{}: {}. This command needs the live ArcGIS Pro project, "
                    "which is only reachable from Pro's main thread. In the "
                    "ArcGIS Pro Python window run:  import mcp_bridge; "
                    "mcp_bridge.start_pump()".format(type(exc).__name__, exc)
                )
            raise
        finally:
            self.current_command = None
            self._lock.release()

    def _dispatch(self, raw):
        request_id = None
        try:
            request = json.loads(raw.decode("utf-8"))
            request_id = request.get("id")
            command_name = request.get("command")
            handler = HANDLERS.get(command_name)
            if handler is None:
                raise ValueError(
                    "Unknown command: {}. Call get_capabilities for the full "
                    "list.".format(command_name)
                )
            self.request_count += 1
            data = self._run(command_name, handler, request.get("params") or {})
            payload = {"id": request_id, "success": True, "data": data}
        except Exception as exc:
            self.last_error = traceback.format_exc()
            payload = {
                "id": request_id,
                "success": False,
                "error": "{}: {}".format(type(exc).__name__, exc),
                "traceback": self.last_error,
            }
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        if len(encoded) > MAX_RESPONSE_BYTES:
            payload = {
                "id": request_id,
                "success": False,
                "error": (
                    "Response too large ({} bytes). Narrow the request with a "
                    "where clause, fewer fields, or a smaller limit."
                ).format(len(encoded)),
            }
            encoded = json.dumps(payload, ensure_ascii=False)
        return encoded


# ---------------------------------------------------------------------------
# Module-level control (state kept in builtins so it survives .pyt reloads)
# ---------------------------------------------------------------------------

def _get_registered():
    return getattr(builtins, _REGISTRY_KEY, None)


def start_server(port=DEFAULT_PORT, auto_port=True):
    server = _get_registered()
    if server and server.running:
        return "MCP bridge already running on {}:{} ({} commands)".format(
            server.host, server.port, len(HANDLERS))
    server = BridgeServer(port=int(port or DEFAULT_PORT))
    server.start(auto_port=auto_port)
    setattr(builtins, _REGISTRY_KEY, server)
    return "MCP bridge started on {}:{} -- {} commands available".format(
        server.host, server.port, len(HANDLERS))


def stop_server():
    server = _get_registered()
    if not server or not server.running:
        return "MCP bridge is not running"
    server.stop()
    return "MCP bridge stopped"


def server_status():
    server = _get_registered()
    if server and server.running:
        return "MCP bridge is running on {}:{} -- {} commands, {} requests served".format(
            server.host, server.port, len(HANDLERS), server.request_count)
    return "MCP bridge is not running"


def start_pump():
    """Give the bridge access to the live project. Run once in Pro's Python window.

    ArcGIS Pro only exposes the open project to its own main thread, so this
    installs a message-only window there and returns immediately. ArcGIS Pro
    is never blocked; its own message loop calls back into the bridge whenever
    a command arrives.
    """
    return pump.start()


# The blocking name this used to have; kept so older notes still work.
run_pump = start_pump


def stop_pump():
    """Stop the main-thread dispatcher."""
    return ("Dispatcher asked to stop" if pump.stop()
            else "No dispatcher was running")


def pump_status():
    return pump.status()


def reload_handlers():
    """Pick up edits to the handler modules without restarting ArcGIS Pro."""
    count = arcgis_mcp.reload_all()
    return "Reloaded {} commands".format(count)


def command_count():
    return len(HANDLERS)
