"""End-to-end smoke test against a mock bridge.

Runs the real MCP server and the real socket client, with a stand-in for the
ArcGIS Pro side, so the protocol, error handling and image handling can be
exercised without ArcGIS Pro installed.
"""

import asyncio
import base64
import json
import os
import pathlib
import socket
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PORT = 6599
os.environ["ARCGIS_MCP_PORT"] = str(PORT)
os.environ["ARCGIS_MCP_TIMEOUT"] = "10"

# A 1x1 transparent PNG.
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

RESPONSES = {
    "ping": {"pong": True, "project_path": "D:/demo/demo.aprx"},
    "get_layers": {"map": "Map", "layers": [{"name": "roads"}]},
    "export_map_view": {
        "map": "Map", "scale": 50000,
        "image_base64": base64.b64encode(PIXEL_PNG).decode("ascii"),
        "image_format": "png",
    },
}


class MockBridge(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__()
        self.requests = []
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("127.0.0.1", PORT))
        self.socket.listen(5)

    def run(self):
        while True:
            try:
                client, _ = self.socket.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client):
        buffer = b""
        while True:
            chunk = client.recv(65536)
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                request = json.loads(line)
                self.requests.append(request)
                command = request["command"]
                if command in RESPONSES:
                    payload = {"id": request["id"], "success": True,
                               "data": RESPONSES[command]}
                else:
                    payload = {"id": request["id"], "success": False,
                               "error": "ValueError: Layer not found in map "
                                        "'Map': nope"}
                client.sendall(json.dumps(payload).encode("utf-8") + b"\n")


def main():
    bridge = MockBridge()
    bridge.start()

    from arcgis_pro_mcp.server import mcp

    async def run():
        tools = await mcp.list_tools()
        print(f"tools exposed: {len(tools)}")

        content, _ = await mcp.call_tool("ping", {})
        assert "pong" in content[0].text, content
        print("ping ->", content[0].text.replace("\n", " ")[:60])

        content, _ = await mcp.call_tool("get_layers", {})
        assert "roads" in content[0].text
        print("get_layers -> ok")

        # Parameters must survive the round trip with their real names.
        await mcp.call_tool("set_layer_renderer", {
            "layer_name": "roads", "renderer_type": "graduated_colors",
            "field": "AADT", "break_count": 7, "color_ramp": "Viridis",
        })
        sent = bridge.requests[-1]
        assert sent["command"] == "set_layer_renderer", sent
        assert sent["params"]["break_count"] == 7, sent
        assert sent["params"]["field"] == "AADT", sent
        print("set_layer_renderer params ->", sorted(sent["params"]))

        # Errors come back readable, with a hint.
        content, _ = await mcp.call_tool("get_layer_info", {"layer_name": "nope"})
        text = content[0].text
        assert "Layer not found" in text and "get_layers" in text, text
        print("error hint ->", text.splitlines()[-1])

        # Image tools return a real image alongside the summary.
        result = await mcp.call_tool("export_map_view", {})
        content = result[0] if isinstance(result, tuple) else result
        kinds = [c.type for c in content]
        assert "image" in kinds, kinds
        print("export_map_view ->", kinds)

        print("\nAll end-to-end checks passed.")

    asyncio.run(run())


if __name__ == "__main__":
    main()
