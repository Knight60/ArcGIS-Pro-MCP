"""Read-only MCP HTTP smoke test; run after installing a candidate and opening Pro.

This validates the running server, not the package on disk. Record the candidate
SHA256 and restart Pro before using these results as release evidence.
"""
import argparse
import json
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:6520/mcp")
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    sequence = 0

    def call(method, params=None, notification=False):
        nonlocal sequence
        sequence += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            payload["id"] = sequence
        request = urllib.request.Request(args.url, json.dumps(payload).encode(),
            {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": "2025-03-26"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if notification:
                assert response.status == 202, response.status
                return
            assert response.headers.get_content_type() == "application/json"
            body = json.load(response)
        assert body.get("id") == sequence, body
        assert "error" not in body, body
        return body["result"]

    initialized = call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "arcgis-release-smoke", "version": "1"}})
    assert initialized["protocolVersion"] == "2025-03-26"
    if args.expected_version:
        assert initialized["serverInfo"]["version"] == args.expected_version, initialized["serverInfo"]
    print("PASS initialize:", initialized["serverInfo"])
    call("notifications/initialized", notification=True)
    call("ping")
    tools = call("tools/list")["tools"]
    names = [tool["name"] for tool in tools]
    assert len(names) == len(set(names)) and "get_project_info" in names
    print(f"PASS initialized notification, ping, tools/list ({len(names)} tools)")
    result = call("tools/call", {"name": "get_project_info", "arguments": {}})
    assert not result.get("isError"), result
    assert result.get("content"), result
    print("PASS tools/call get_project_info (read only)")


if __name__ == "__main__":
    main()
