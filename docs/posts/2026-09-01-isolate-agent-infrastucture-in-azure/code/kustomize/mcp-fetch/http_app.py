"""Official mcp-server-fetch Server over streamable HTTP.

Upstream ``serve()`` registers ``fetch`` (and the fetch prompt) on a
low-level MCP ``Server``, then binds stdio. This cluster speaks
streamable-HTTP, so we let ``serve()`` register those handlers and stop
before stdin, then mount the same Server at ``/mcp``.
"""

from __future__ import annotations

import asyncio
import os

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send


def _truthy(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class _StdioNotUsed(RuntimeError):
    """Stop official serve() after tools are registered, before stdin."""


class _NoStdio:
    """Stand-in for ``stdio_server()`` that never opens stdin/stdout."""

    async def __aenter__(self):
        raise _StdioNotUsed()

    async def __aexit__(self, *exc):
        return False


def _no_stdio(*_args, **_kwargs):
    return _NoStdio()


def official_fetch_server():
    """The Server ``python -m mcp_server_fetch`` would have run on stdio."""
    import mcp_server_fetch.server as fetch_mod

    captured: dict = {}
    orig_server = fetch_mod.Server
    orig_stdio = fetch_mod.stdio_server

    def _capture(*args, **kwargs):
        server = orig_server(*args, **kwargs)
        captured["server"] = server
        return server

    fetch_mod.Server = _capture  # type: ignore[misc]
    fetch_mod.stdio_server = _no_stdio  # type: ignore[misc]
    try:
        try:
            asyncio.run(
                fetch_mod.serve(
                    os.getenv("FETCH_USER_AGENT") or None,
                    _truthy("IGNORE_ROBOTS_TXT", "true"),
                    os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None,
                )
            )
        except _StdioNotUsed:
            pass
    finally:
        fetch_mod.Server = orig_server
        fetch_mod.stdio_server = orig_stdio

    server = captured.get("server")
    if server is None:
        raise RuntimeError("official mcp-server-fetch did not construct a Server")
    return server


def streamable_http_app(server) -> Starlette:
    session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=False,
        stateless=True,
    )

    async def handle_streamable_http(
        scope: Scope, receive: Receive, send: Send
    ) -> None:
        await session_manager.handle_request(scope, receive, send)

    def lifespan(_app: Starlette):
        return session_manager.run()

    return Starlette(
        routes=[Mount("/mcp", app=handle_streamable_http)],
        lifespan=lifespan,
    )


mcp_app = streamable_http_app(official_fetch_server())
