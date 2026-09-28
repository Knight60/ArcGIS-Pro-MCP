"""Compatibility shim: legacy unauthenticated TCP has been retired.

Use the authenticated C# HTTP endpoint. There is deliberately no discovery,
socket creation, replay or environment-variable override in this module.
"""
from typing import Optional

class ArcGISProNotAvailable(Exception):
    pass

def describe_instances() -> list:
    return []

def candidate_endpoints() -> list:
    return []

class ArcGISConnection:
    def __init__(self, host="127.0.0.1", port=6510, timeout=60):
        self.host, self.port, self.timeout = host, port, timeout

    def close(self):
        pass

    def send_command(self, command: str, params: Optional[dict] = None) -> dict:
        raise ArcGISProNotAvailable(
            "Legacy TCP relay disabled in the hardened build. "
            "Configure authenticated HTTP at http://127.0.0.1:6520/mcp instead."
        )

_connection = ArcGISConnection()

def get_connection() -> ArcGISConnection:
    return _connection
