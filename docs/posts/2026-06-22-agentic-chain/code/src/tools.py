import contextlib
import io

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


@tool
def code_interpreter(code: str) -> str:
    """Execute Python code and return stdout or errors."""
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            exec(code, {"__builtins__": __builtins__}, {})
        output = buffer.getvalue().strip()
        return output or "Code executed successfully."
    except Exception as e:
        return f"Error executing code: {e}"


TOOL_REGISTRY = {
    "web_search": web_search,
    "code_interpreter": code_interpreter,
}