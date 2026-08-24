"""Add /healthz and /readyz in front of the official FastMCP HTTP app.

/readyz succeeds only when the in-cluster Kubernetes API is reachable so
the Deployment is not Ready until the MCP process can actually claim
sandboxes. Placement defaults live in ``placement.py``.
"""

from __future__ import annotations


def _attach_probes(starlette_app):
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def healthz(_request):
        return PlainTextResponse("ok")

    async def readyz(_request):
        try:
            from kubernetes import client, config

            config.load_incluster_config()
            client.VersionApi().get_code()
        except Exception as exc:  # noqa: BLE001 — probe must surface API errors
            return PlainTextResponse(f"not ready: {exc}", status_code=503)
        return PlainTextResponse("ok")

    starlette_app.router.routes.insert(0, Route("/healthz", healthz, methods=["GET"]))
    starlette_app.router.routes.insert(0, Route("/readyz", readyz, methods=["GET"]))
    return starlette_app


try:
    from k8s_agent_sandbox_mcp_server.app import mcp, app as mcp_app
    from placement import install_placement_defaults

    install_placement_defaults(mcp)
    app = _attach_probes(mcp_app)
except ImportError:
    # Unit tests import placement helpers without the official MCP image.
    mcp = None
    app = None
