"""Fetch MCP is discovered from the registry; this file checks the client mapping."""

import json
from pathlib import Path
from unittest.mock import patch

from tools.mcp_client import fetch_registry_servers

_FETCH_DIR = Path(__file__).resolve().parents[3] / "kustomize" / "mcp-fetch"


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_mcp_is_discovered_from_registry():
    payload = {
        "servers": [
            {
                "server": {
                    "name": "io.modelcontextprotocol.anonymous/fetch",
                    "remotes": [
                        {
                            "type": "streamable-http",
                            "url": "http://mcp-fetch.agentic-chain.svc.cluster.local:8000/mcp",
                        }
                    ],
                }
            }
        ]
    }
    with patch("tools.mcp_client.httpx.get", return_value=_FakeResp(payload)):
        conns = fetch_registry_servers()
    assert conns["fetch"]["transport"] == "streamable_http"
    assert conns["fetch"]["url"].endswith("/mcp")


def test_server_json_descriptions_fit_registry_limit():
    """MCP registry rejects description longer than 100 characters (HTTP 422)."""
    root = Path(__file__).resolve().parents[3] / "kustomize"
    for path in root.glob("**/server.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        desc = data.get("description") or ""
        assert len(desc) <= 100, f"{path} description is {len(desc)} chars"


def test_fetch_health_wrapper_is_probes_only():
    text = (_FETCH_DIR / "health_wrapper.py").read_text(encoding="utf-8")
    assert "/healthz" in text
    assert "/readyz" in text
    assert "from http_app import mcp_app" in text
    assert "async def fetch" not in text
    assert "_abs_url" not in text
    assert "fetch_url" not in text


def test_fetch_http_app_uses_official_server():
    text = (_FETCH_DIR / "http_app.py").read_text(encoding="utf-8")
    assert "mcp_server_fetch" in text
    assert "fetch_mod.serve(" in text
    assert "async def fetch" not in text
    assert "@mcp.tool" not in text
    assert "_abs_url" not in text
    assert "asynccontextmanager" not in text
