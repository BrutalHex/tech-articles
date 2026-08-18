"""Tool to list code-execution history stored in agent-sandbox."""

from langchain_core.tools import tool

from tools.sandbox import list_code_execution_history


@tool
def code_execution_history(limit: int = 20) -> str:
    """List recent Python scripts executed via agent-sandbox (audit trail).

    Call this whenever the user asks for code execution history, what code ran,
    sandbox history, or an audit of prior interpreter runs.

    Returns JSON with claim/sandbox ids and each file's full source code, meta,
    and result (stdout/stderr/exit_code). You MUST paste that tool output to the
    user. Never invent business metrics, revenue, or regulations in place of the
    tool result.
    """
    return list_code_execution_history(limit=limit)
