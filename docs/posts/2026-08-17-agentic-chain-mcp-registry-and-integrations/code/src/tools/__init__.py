"""Agent tools package.

Code execution and web fetch come from MCP servers discovered via the
in-cluster registry. RAG tools stay in-process (Chroma). There is no
local interpreter and no code-execution history surface.
"""

from tools import mcp_client
from tools.mcp_client import *  # noqa: F403

# Static in-process tools only. MCP tools are loaded per call from the registry.
TOOL_REGISTRY: dict = {}

__all__ = [*mcp_client.__all__, "TOOL_REGISTRY"]
