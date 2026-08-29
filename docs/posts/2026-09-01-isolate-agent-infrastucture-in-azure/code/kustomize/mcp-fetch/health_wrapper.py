"""Add /healthz and /readyz in front of official fetch MCP over HTTP.

The Fetch tool itself is upstream ``mcp_server_fetch.server.serve``.

"""

from __future__ import annotations


def _attach_probes(starlette_app):
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def healthz(_request):
        return PlainTextResponse("ok")

    async def readyz(_request):
        return PlainTextResponse("ok")

    starlette_app.router.routes.insert(0, Route("/healthz", healthz, methods=["GET"]))
    starlette_app.router.routes.insert(0, Route("/readyz", readyz, methods=["GET"]))
    return starlette_app


try:
    from http_app import mcp_app

    app = _attach_probes(mcp_app)
except ImportError:
    # Unit tests import this module without mcp-server-fetch installed.
    mcp_app = None
    app = None
