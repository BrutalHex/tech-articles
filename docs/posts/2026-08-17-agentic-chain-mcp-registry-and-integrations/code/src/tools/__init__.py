"""Agent tools package — one module per tool, shared sandbox helpers."""

from tools.code_execution_history import code_execution_history
from tools.code_interpreter import code_interpreter
from tools.sandbox import (
    claim_sandbox,
    fetch_code_execution_history,
    list_code_execution_history,
    use_agent_sandbox,
)
from tools.web_search import web_search

TOOL_REGISTRY = {
    "web_search": web_search,
    "code_interpreter": code_interpreter,
    "code_execution_history": code_execution_history,
}

# Back-compat aliases used by older tests / docs.
_claim_sandbox = claim_sandbox
_use_agent_sandbox = use_agent_sandbox

__all__ = [
    "TOOL_REGISTRY",
    "code_execution_history",
    "code_interpreter",
    "fetch_code_execution_history",
    "list_code_execution_history",
    "web_search",
    "claim_sandbox",
    "use_agent_sandbox",
    "_claim_sandbox",
    "_use_agent_sandbox",
]
