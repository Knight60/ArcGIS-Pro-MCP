"""Client that sends commands to ArcGIS Pro, through the add-in when it is there.

Two ways in, tried in this order:

1. **The add-in's MCP endpoint**, ``http://127.0.0.1:6520/mcp`` -- the same
   address every AI client uses. Each command is a ``tools/call``, and the MCP
   result is turned back into the ``{"success", "data", "error"}`` shape the
   rest of this package expects. This is the fast path: the add-in runs
   commands on ArcGIS Pro's Main CIM Thread.
2. **The Python bridge inside ArcGIS Pro**, newline-delimited JSON over TCP on
   127.0.0.1:6521, or whichever port a running bridge registered. This is the
   original all-Python path, kept for anyone running the bridge without the
   add-in. It reaches the open project through the bridge's dispatcher on Pro's
   Python thread, which is much slower.

Setting ``ARCGIS_MCP_PORT`` pins the connection to a TCP bridge on that port and
skips the add-in; the tests use it to talk to a stand-in bridge.
"""

from __future__ import annotations

import glob
import itertools
import json
import os
import socket
import urllib.request
from typing import Any, Optional

DEFAULT_HOST = os.environ.get("ARCGIS_MCP_HOST", "127.0.0.1")
DEFAULT_URL = os.environ.get("ARCGIS_MCP_URL", f"http://{DEFAULT_HOST}:6520/mcp")
DEFAULT_PORT = int(os.environ.get("ARCGIS_MCP_PORT", "6521"))
DEFAULT_TIMEOUT = float(os.environ.get("ARCGIS_MCP_TIMEOUT", "600"))
PORT_WAS_SET = "ARCGIS_MCP_PORT" in os.environ
MCP_PROTOCOL = "2025-03-26"

INSTANCE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
    "ArcGIS-MCP", "instances",
)

SETUP_HINT = (
    "Open ArcGIS Pro with the ArcGIS Pro MCP add-in installed: its MCP tab shows "
    "whether it is listening on http://127.0.0.1:6520/mcp. Without the add-in, "
    "start the Python bridge from the ArcGIS MCP toolbox (ArcGISMCP.pyt) each session."
)


class ArcGISProNotAvailable(Exception):
    """Raised when neither the add-in nor a Python bridge can be reached."""


def describe_instances() -> list:
    """Python bridge instances that have registered themselves, newest first."""
    instances = []
    for path in sorted(glob.glob(os.path.join(INSTANCE_DIR, "bridge-*.json")),
                       key=os.path.getmtime, reverse=True):
        try:
            with open(path) as handle:
                instances.append(json.load(handle))
        except (OSError, ValueError):
            continue
    return instances


def candidate_endpoints() -> list:
    """TCP bridge addresses to try, in order: the configured one, then any registered."""
    endpoints = [(DEFAULT_HOST, DEFAULT_PORT)]
    if PORT_WAS_SET:
        return endpoints
    for instance in describe_instances():
        endpoint = (instance.get("host") or DEFAULT_HOST, int(instance.get("port", 0)))
        if endpoint[1] and endpoint not in endpoints:
            endpoints.append(endpoint)
    return endpoints


class _AddinHttp:
    """Commands as MCP tools/call requests to the add-in's endpoint."""

    def __init__(self, url: str, timeout: float):
        self.url = url
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._initialised = False

    def _post(self, method: str, params: Optional[dict] = None, notification: bool = False) -> Any:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            payload["id"] = next(self._ids)
        request = urllib.request.Request(
            self.url, json.dumps(payload, default=str).encode("utf-8"),
            {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": MCP_PROTOCOL})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if notification:
                return None
            body = json.load(response)
        if "error" in body:
            raise RuntimeError(body["error"].get("message", str(body["error"])))
        return body["result"]

    def available(self) -> bool:
        try:
            self._initialise()
            return True
        except (OSError, ValueError, RuntimeError):
            self._initialised = False
            return False

    def _initialise(self) -> None:
        if self._initialised:
            return
        self._post("initialize", {"protocolVersion": MCP_PROTOCOL, "capabilities": {},
                                  "clientInfo": {"name": "arcgis-pro-mcp", "version": "1"}})
        self._post("notifications/initialized", notification=True)
        self._initialised = True

    def send_command(self, command: str, params: dict) -> dict:
        self._initialise()
        result = self._post("tools/call", {"name": command, "arguments": params})
        content = result.get("content", [])
        texts = [block.get("text", "") for block in content if block.get("type") == "text"]
        images = [block for block in content if block.get("type") == "image"]
        if result.get("isError"):
            return {"success": False, "error": " ".join(texts) or "unknown error"}
        data: Any = None
        if texts:
            try:
                data = json.loads(texts[0])
            except ValueError:
                data = texts[0]
        if images:
            # The TCP protocol carried images as base64 in the data; keep that shape.
            data = dict(data) if isinstance(data, dict) else ({} if data is None else {"result": data})
            data["image_base64"] = images[0].get("data")
            data["image_format"] = (images[0].get("mimeType") or "image/png").split("/")[-1]
        return {"success": True, "data": data}


class ArcGISConnection:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = DEFAULT_TIMEOUT, url: str = DEFAULT_URL):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self._ids = itertools.count(1)
        self._http = None if PORT_WAS_SET else _AddinHttp(url, timeout)
        self._use_http: Optional[bool] = None   # None: not decided yet

    # --- the Python bridge, over TCP --------------------------------------

    def _connect(self) -> None:
        errors = [DEFAULT_URL] if self._http is not None else []
        for host, port in candidate_endpoints():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            try:
                sock.connect((host, port))
            except OSError as exc:
                sock.close()
                errors.append(f"{host}:{port} ({exc.strerror or exc})")
                continue
            self._socket = sock
            self.host, self.port = host, port
            return
        raise ArcGISProNotAvailable(
            "Cannot reach ArcGIS Pro. Tried " + ", ".join(errors) + ". " + SETUP_HINT
        )

    def close(self) -> None:
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _send_once(self, payload: dict) -> dict:
        if self._socket is None:
            self._connect()
        assert self._socket is not None
        self._socket.sendall(json.dumps(payload, default=str).encode("utf-8") + b"\n")
        buffer = b""
        while b"\n" not in buffer:
            chunk = self._socket.recv(1 << 20)
            if not chunk:
                raise ConnectionError("Connection closed by the ArcGIS Pro bridge")
            buffer += chunk
        line = buffer.split(b"\n", 1)[0]
        return json.loads(line.decode("utf-8"))

    def _timed_out(self, command: str) -> ArcGISProNotAvailable:
        return ArcGISProNotAvailable(
            f"ArcGIS Pro did not answer '{command}' within {self.timeout:.0f}s. "
            "Long geoprocessing runs can exceed this -- raise ARCGIS_MCP_TIMEOUT, "
            "or check whether a dialog in ArcGIS Pro is waiting for input."
        )

    # --- whichever is there -----------------------------------------------

    def send_command(self, command: str, params: Optional[dict] = None) -> dict:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        if self._http is not None and self._use_http is not False:
            if self._use_http or self._http.available():
                self._use_http = True
                try:
                    return self._http.send_command(command, params)
                except socket.timeout:
                    raise self._timed_out(command)
                except OSError:
                    self._use_http = None   # Pro closed or restarted: look again next call
                    raise ArcGISProNotAvailable("Lost the connection to the add-in. " + SETUP_HINT)
            self._use_http = False
        payload: dict[str, Any] = {"id": next(self._ids), "command": command, "params": params}
        try:
            return self._send_once(payload)
        except ArcGISProNotAvailable:
            self._use_http = None
            raise
        except socket.timeout:
            self.close()
            raise self._timed_out(command)
        except (OSError, ConnectionError, json.JSONDecodeError):
            # Stale socket (Pro restarted, bridge reloaded) -- reconnect once.
            self.close()
            return self._send_once(payload)


_connection: Optional[ArcGISConnection] = None


def get_connection() -> ArcGISConnection:
    global _connection
    if _connection is None:
        _connection = ArcGISConnection()
    return _connection
