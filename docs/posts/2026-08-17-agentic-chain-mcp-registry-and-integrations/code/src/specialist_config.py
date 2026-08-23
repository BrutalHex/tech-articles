from typing import Any

from rag import build_rag_tools
from specialists import SPECIALIST_TOOL_KEYS


def build_specialist_config(
    llm: Any,
    embedding_function: Any,
    chroma_host: str,
    chroma_port: int,
) -> dict[str, dict]:
    rag_tools = build_rag_tools(embedding_function, chroma_host, chroma_port)

    specialist_config = {}
    for name, tool_keys in SPECIALIST_TOOL_KEYS.items():
        static = {}
        for key in tool_keys:
            if key == "mcp":
                continue
            if key in rag_tools:
                static[key] = rag_tools[key]
        specialist_config[name] = {
            "llm": llm,
            "static_tools": static,
        }

    return specialist_config
