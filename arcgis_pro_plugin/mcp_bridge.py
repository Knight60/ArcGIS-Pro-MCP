"""Retired legacy bridge. No arcpy import, listener, dispatch, or code fallback.

Use the authenticated C# HTTP add-in. Kept as a compatibility stub so old
toolbox/startup references fail explicitly instead of starting an unsafe server.
"""
_DISABLED = "Legacy Python/TCP bridge disabled in the hardened build; use authenticated C# MCP HTTP."

class BridgeServer:
    def __init__(self, host="127.0.0.1", port=6510):
        self.host, self.port = host, port
        self.running = False

    def start(self, auto_port=True):
        raise RuntimeError(_DISABLED)

    def stop(self):
        return _DISABLED

def start_server(port=6510, auto_port=True):
    raise RuntimeError(_DISABLED)

def stop_server():
    return _DISABLED

def server_status():
    return {"running": False, "disabled": True, "message": _DISABLED}

def start_pump():
    raise RuntimeError(_DISABLED)

def stop_pump():
    return _DISABLED
