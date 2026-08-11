"""Web search tool (DuckDuckGo)."""

from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool

_ddg_search: DuckDuckGoSearchRun | None = None


def _get_ddg_search() -> DuckDuckGoSearchRun:
    global _ddg_search
    if _ddg_search is None:
        _ddg_search = DuckDuckGoSearchRun()
    return _ddg_search


@tool
def web_search(query: str) -> str:
    """Search the web for current information."""
    return _get_ddg_search().run(query)
