"""TCP client that talks to the MCP bridge running inside ArcGIS Pro.

The bridge writes a small file per running instance, so the port it ended up
on is discovered automatically -- no configuration needed when the default
port is busy or several ArcGIS Pro sessions are open.
"""

from __future__ import annotations

import glob
import itertools
import json
import os
import socket
from typing import Any, Optional

DEFAULT_HOST = os.environ.get("ARCGIS_MCP_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("ARCGIS_MCP_PORT", "6510"))
DEFAULT_TIMEOUT = float(os.environ.get("ARCGIS_MCP_TIMEOUT", "600"))
PORT_WAS_SET = "ARCGIS_MCP_PORT" in os.environ

INSTANCE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
    "ArcGIS-MCP", "instances",
)

SETUP_HINT = (
    "Open ArcGIS Pro, then run the 'Start MCP Server' tool in the ArcGIS MCP "
    "toolbox (Catalog > Toolboxes > ArcGISMCP.pyt). The bridge stops whenever "
    "ArcGIS Pro closes, so it has to be started again each session."
)


class ArcGISProNotAvailable(Exception):
    """Raised when the bridge inside ArcGIS Pro cannot be reached."""


def describe_instances() -> list:
    """Bridge instances that have registered themselves, newest first."""
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
    """Addresses to try, in order: the configured one, then any registered."""
    endpoints = [(DEFAULT_HOST, DEFAULT_PORT)]
    if PORT_WAS_SET:
        return endpoints
    for instance in describe_instances():
        endpoint = (instance.get("host") or DEFAULT_HOST, int(instance.get("port", 0)))
        if endpoint[1] and endpoint not in endpoints:
            endpoints.append(endpoint)
    return endpoints


class ArcGISConnection:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self._ids = itertools.count(1)

    def _connect(self) -> None:
        errors = []
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
            "Cannot reach the ArcGIS Pro MCP bridge. Tried "
            + ", ".join(errors) + ". " + SETUP_HINT
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

    def send_command(self, command: str, params: Optional[dict] = None) -> dict:
        payload: dict[str, Any] = {
            "id": next(self._ids),
            "command": command,
            "params": {k: v for k, v in (params or {}).items() if v is not None},
        }
        try:
            return self._send_once(payload)
        except ArcGISProNotAvailable:
            raise
        except socket.timeout:
            self.close()
            raise ArcGISProNotAvailable(
                f"ArcGIS Pro did not answer '{command}' within {self.timeout:.0f}s. "
                "Long geoprocessing runs can exceed this -- raise "
                "ARCGIS_MCP_TIMEOUT, or check whether a dialog in ArcGIS Pro is "
                "waiting for input."
            )
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
