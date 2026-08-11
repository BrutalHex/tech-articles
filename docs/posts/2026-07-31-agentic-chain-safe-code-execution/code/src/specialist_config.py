from typing import Any

from rag import build_rag_tools
from specialists import SPECIALIST_TOOL_KEYS
from tools import TOOL_REGISTRY


def build_specialist_config(
    llm: Any,
    embedding_function: Any,
    chroma_host: str,
    chroma_port: int,
) -> dict[str, dict]:
    available_tools = {
        **TOOL_REGISTRY,
        **build_rag_tools(embedding_function, chroma_host, chroma_port),
    }

    specialist_config = {}
    for name, tool_keys in SPECIALIST_TOOL_KEYS.items():
        tools = [available_tools[key] for key in tool_keys]
        specialist_config[name] = {
            "llm": llm.bind_tools(tools),
            "tools": {tool.name: tool for tool in tools},
        }

    return specialist_config