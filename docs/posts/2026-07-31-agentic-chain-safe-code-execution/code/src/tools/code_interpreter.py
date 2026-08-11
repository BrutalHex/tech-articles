"""Safe Python code execution via agent-sandbox only (no in-process exec)."""

from __future__ import annotations

import ast
import os
import shlex

from langchain_core.tools import tool

from tools.sandbox import (
    _logger,
    claim_sandbox,
    write_history,
    write_history_result,
)

# Prepended to every executed script (audit trail + model-facing reminder).
_STDOUT_INSTRUCTION = (
    "# [code_interpreter] Results must be visible on stdout (print / display).\n"
    "# Scripts are not a REPL: bare expressions do not show unless printed.\n"
    "# This runner auto-prints a trailing expression or final assignment value\n"
    "# when the source does not already print it.\n"
)


def _is_print_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    )


def _print_expr(value: ast.expr) -> ast.Expr:
    return ast.Expr(
        value=ast.Call(
            func=ast.Name(id="print", ctx=ast.Load()),
            args=[value],
            keywords=[],
        )
    )


def ensure_stdout_visibility(code: str) -> str:
    """
    Prepare user code so meaningful results appear on stdout.

    - Injects a short instruction comment.
    - If the last statement is a non-print expression (e.g. `fibonacci(15)` or
      a bare name), wrap/replace it with `print(...)`.
    - If the last statement is a simple assignment (`x = ...`), append
      `print(x)` so computed values are not silent.
    Syntax errors are left for the runtime so diagnostics stay accurate.
    """
    raw = code if code.endswith("\n") else code + "\n"
    try:
        tree = ast.parse(raw)
    except SyntaxError:
        return _STDOUT_INSTRUCTION + raw

    if not tree.body:
        return _STDOUT_INSTRUCTION + raw

    last = tree.body[-1]
    changed = False

    if isinstance(last, ast.Expr) and not _is_print_call(last.value):
        tree.body[-1] = _print_expr(last.value)
        changed = True
    elif (
        isinstance(last, ast.Assign)
        and len(last.targets) == 1
        and isinstance(last.targets[0], ast.Name)
    ):
        tree.body.append(_print_expr(ast.Name(id=last.targets[0].id, ctx=ast.Load())))
        changed = True
    elif (
        isinstance(last, ast.AnnAssign)
        and isinstance(last.target, ast.Name)
        and last.value is not None
    ):
        tree.body.append(_print_expr(ast.Name(id=last.target.id, ctx=ast.Load())))
        changed = True

    if changed:
        try:
            ast.fix_missing_locations(tree)
            raw = ast.unparse(tree) + "\n"
        except Exception as exc:
            _logger.warning("ensure_stdout_visibility unparse failed: %s", exc)
            # Fall through with original source + instruction only.

    if raw.lstrip().startswith("# [code_interpreter]"):
        return raw
    return _STDOUT_INSTRUCTION + raw


def _agent_sandbox_exec(code: str) -> str:
    prepared = ensure_stdout_visibility(code)
    sandbox = claim_sandbox()
    # Persist the prepared source so history/.result.json match what ran.
    history = write_history(sandbox, prepared)
    history_path = history["code_path"]

    # Run the saved history file so stdout matches what is on disk for audit.
    quoted = shlex.quote(history_path)
    result = sandbox.commands.run(
        f"python3 {quoted}",
        timeout=int(os.getenv("SANDBOX_EXEC_TIMEOUT", "60")),
    )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    raw_exit = getattr(result, "exit_code", None)
    try:
        exit_code = 0 if raw_exit is None else int(raw_exit)
    except (TypeError, ValueError):
        exit_code = 1

    # Persist stdout/stderr/exit_code as a separate history artifact.
    try:
        result_path = write_history_result(
            sandbox,
            history,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )
    except Exception as exc:
        _logger.warning("write_history_result failed: %s", exc)
        result_path = history.get("result_path", "")

    header = (
        f"[agent-sandbox claim={sandbox.claim_name} "
        f"sandbox={sandbox.sandbox_id} history={history_path} "
        f"result={result_path}]"
    )

    if exit_code != 0:
        detail = stderr or stdout or f"exit_code={exit_code}"
        return f"{header}\nError executing code: {detail}"

    body = stdout if stdout else "Code executed successfully."
    if stderr:
        body = f"{body}\n[stderr]\n{stderr}"
    return f"{header}\n{body}"


@tool
def code_interpreter(code: str) -> str:
    """Execute Python code in the isolated sandbox and return real stdout/stderr.

    MANDATORY for any request that involves writing, running, evaluating, or
    getting results from code/scripts/calculations/data transforms. Do NOT
    answer those from model memory — call this tool and report its output.

    Prefer print(...) for values the user must see. The runner also auto-prints
    a trailing expression or final assignment so bare REPL-style code still
    produces stdout.

    Always runs inside an agent-sandbox claimed from a warm pool (isolated pod).
    There is no in-process exec fallback. Artifacts under /app/history:
    - *.py source (with stdout-visibility prep)
    - *.meta.json metadata
    - *.result.json stdout/stderr/exit_code
    """
    try:
        return _agent_sandbox_exec(code)
    except Exception as exc:
        _logger.exception("agent-sandbox execution failed")
        return f"Error executing code in agent-sandbox: {exc}"
