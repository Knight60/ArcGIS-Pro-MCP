"""TCP client that talks to the MCP bridge running inside ArcGIS Pro."""

import itertools
import json
import os
import socket

DEFAULT_HOST = os.environ.get("ARCGIS_MCP_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("ARCGIS_MCP_PORT", "6510"))
DEFAULT_TIMEOUT = float(os.environ.get("ARCGIS_MCP_TIMEOUT", "300"))


class ArcGISProNotAvailable(Exception):
    """Raised when the bridge inside ArcGIS Pro cannot be reached."""


class ArcGISConnection:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket = None
        self._ids = itertools.count(1)

    def _connect(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.host, self.port))
        except OSError as exc:
            sock.close()
            raise ArcGISProNotAvailable(
                f"Cannot connect to ArcGIS Pro MCP bridge at {self.host}:{self.port}. "
                "Make sure ArcGIS Pro is open and the 'Start MCP Server' tool in the "
                "ArcGIS MCP toolbox has been run."
            ) from exc
        self._socket = sock

    def close(self):
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _send_once(self, payload):
        if self._socket is None:
            self._connect()
        self._socket.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        buffer = b""
        while b"\n" not in buffer:
            chunk = self._socket.recv(65536)
            if not chunk:
                raise ConnectionError("Connection closed by ArcGIS Pro bridge")
            buffer += chunk
        line = buffer.split(b"\n", 1)[0]
        return json.loads(line.decode("utf-8"))

    def send_command(self, command, params=None):
        payload = {
            "id": next(self._ids),
            "command": command,
            "params": {k: v for k, v in (params or {}).items() if v is not None},
        }
        try:
            return self._send_once(payload)
        except ArcGISProNotAvailable:
            raise
        except (OSError, ConnectionError, json.JSONDecodeError):
            # stale socket (e.g. Pro restarted) — reconnect and retry once
            self.close()
            return self._send_once(payload)


_connection = None


def get_connection():
    global _connection
    if _connection is None:
        _connection = ArcGISConnection()
    return _connection
