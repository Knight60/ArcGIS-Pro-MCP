"""Regression: legacy relay and Python listener must fail before socket creation."""
import pathlib
import sys
from unittest.mock import patch
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "arcgis_pro_plugin"))

def test_retired_transports():
    from arcgis_pro_mcp.connection import get_connection, ArcGISProNotAvailable, candidate_endpoints
    import mcp_bridge
    with patch("socket.socket", side_effect=AssertionError("Legacy transport opened a socket")):
        assert candidate_endpoints() == []
        try:
            get_connection().send_command("execute_arcpy_code", {"code": "raise Exception()"})
        except ArcGISProNotAvailable:
            pass
        else:
            raise AssertionError("Retired relay accepted request")
        try:
            mcp_bridge.BridgeServer().start()
        except RuntimeError as error:
            assert "disabled" in str(error)
        else:
            raise AssertionError("Retired Python bridge started")

if __name__ == "__main__":
    test_retired_transports()
    print("PASS legacy transports fail closed without socket creation")
