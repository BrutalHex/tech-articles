"""Smoke tests for the code_interpreter tool (agent-sandbox mocks only)."""

import contextlib
import io
import os
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Force agent-sandbox backend; execution is always mocked below.
os.environ["SANDBOX_BACKEND"] = "agent-sandbox"

from tools import code_execution_history, code_interpreter, list_code_execution_history
from tools.sandbox import reset_sandbox_handle_for_tests


def _make_executing_fake_sandbox():
    """Fake sandbox: files.write stores source; python3 path execs it and captures stdout."""
    store: dict[str, str] = {}

    fake_files = MagicMock()

    def _write(path, body, **_kwargs):
        store[str(path)] = body if isinstance(body, str) else body.decode("utf-8")

    fake_files.write.side_effect = _write

    def _run(cmd, timeout=None, **_kwargs):
        text = str(cmd)
        if "mkdir" in text:
            return SimpleNamespace(stdout="", stderr="", exit_code=0)
        if "python3" in text:
            match = re.search(r"(history/\S+\.py)", text)
            if not match:
                return SimpleNamespace(
                    stdout="", stderr="no history path", exit_code=1
                )
            path = match.group(1)
            code = store.get(path, "")
            out = io.StringIO()
            err = io.StringIO()
            ns: dict = {"__builtins__": __builtins__}
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    exec(code, ns, ns)
                return SimpleNamespace(
                    stdout=out.getvalue(),
                    stderr=err.getvalue(),
                    exit_code=0,
                )
            except Exception as exc:
                return SimpleNamespace(
                    stdout=out.getvalue(),
                    stderr=f"{type(exc).__name__}: {exc}",
                    exit_code=1,
                )
        return SimpleNamespace(stdout="", stderr="", exit_code=0)

    fake_commands = MagicMock()
    fake_commands.run.side_effect = _run

    fake_sandbox = MagicMock()
    fake_sandbox.commands = fake_commands
    fake_sandbox.files = fake_files
    fake_sandbox.claim_name = "sandbox-claim-test"
    fake_sandbox.sandbox_id = "sandbox-test"
    fake_sandbox.is_active = True
    fake_sandbox.status.return_value = ("SandboxReady", "ok")
    return fake_sandbox, store


def _invoke_with_fake_sandbox(code: str) -> str:
    reset_sandbox_handle_for_tests()
    fake_sandbox, _store = _make_executing_fake_sandbox()
    with patch("tools.code_interpreter.claim_sandbox", return_value=fake_sandbox):
        return code_interpreter.invoke({"code": code})


def test_code_interpreter_prints_output():
    result = _invoke_with_fake_sandbox("print('hello from tool')")
    assert "hello from tool" in result
    assert "agent-sandbox" in result


def test_code_interpreter_computes():
    result = _invoke_with_fake_sandbox("print(2 + 2)")
    assert "4" in result


def test_code_interpreter_handles_syntax_error():
    result = _invoke_with_fake_sandbox("print(")
    assert "Error executing code" in result


def test_code_interpreter_assignment_auto_prints():
    result = _invoke_with_fake_sandbox("x = 1")
    assert "1" in result


def test_code_interpreter_auto_prints_trailing_expression():
    code = """
def fibonacci(n):
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    else:
        return fibonacci(n - 1) + fibonacci(n - 2)

fibonacci_15 = fibonacci(15)
fibonacci_15
"""
    result = _invoke_with_fake_sandbox(code)
    assert "610" in result


def test_code_interpreter_auto_prints_final_assignment():
    code = """
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

fibonacci_15 = fibonacci(15)
"""
    result = _invoke_with_fake_sandbox(code)
    assert "610" in result


def test_ensure_stdout_visibility_idempotent_print():
    from tools.code_interpreter import ensure_stdout_visibility

    prepared = ensure_stdout_visibility("print(2 + 2)\n")
    assert prepared.count("print(") == 1
    assert "print(2 + 2)" in prepared or "print(2+2)" in prepared.replace(" ", "")


def test_code_interpreter_uses_agent_sandbox(monkeypatch):
    monkeypatch.setenv("SANDBOX_BACKEND", "agent-sandbox")
    monkeypatch.setenv("SANDBOX_WARMPOOL", "python-sandbox-warmpool")
    monkeypatch.setenv("SANDBOX_NAMESPACE", "agentic-chain")
    monkeypatch.setenv("SANDBOX_SHUTDOWN_AFTER_SECONDS", "60")

    fake_result = SimpleNamespace(stdout="42\n", stderr="", exit_code=0)
    fake_commands = MagicMock()
    fake_commands.run.side_effect = [
        SimpleNamespace(stdout="", stderr="", exit_code=0),  # mkdir (write code/meta)
        fake_result,  # python3 history file
        SimpleNamespace(stdout="", stderr="", exit_code=0),  # mkdir (write result/meta)
    ]
    fake_files = MagicMock()
    fake_sandbox = MagicMock()
    fake_sandbox.commands = fake_commands
    fake_sandbox.files = fake_files
    fake_sandbox.claim_name = "sandbox-claim-test"
    fake_sandbox.sandbox_id = "sandbox-test"
    fake_sandbox.is_active = True
    fake_sandbox.status.return_value = ("SandboxReady", "ok")

    reset_sandbox_handle_for_tests()
    with patch("tools.code_interpreter.claim_sandbox", return_value=fake_sandbox):
        result = code_interpreter.invoke({"code": "print(42)"})

    assert "42" in result
    assert "agent-sandbox" in result
    assert "sandbox-claim-test" in result
    assert "result=" in result
    assert fake_files.write.called
    written_paths = [str(c.args[0]) for c in fake_files.write.call_args_list]
    assert any(p.endswith(".py") for p in written_paths)
    assert any(p.endswith(".meta.json") for p in written_paths)
    assert any(p.endswith(".result.json") for p in written_paths)
    result_writes = [
        c.args[1]
        for c in fake_files.write.call_args_list
        if str(c.args[0]).endswith(".result.json")
    ]
    assert result_writes
    assert "42" in result_writes[0]
    assert any("python3" in str(c) for c in fake_commands.run.call_args_list)


def test_list_code_execution_history(monkeypatch):
    monkeypatch.setenv("SANDBOX_BACKEND", "agent-sandbox")

    entry = SimpleNamespace(name="20260801T120000_abcd1234.py", size=12, mod_time=1.0)
    fake_files = MagicMock()
    fake_files.list.return_value = [entry]

    def _read(path, **_kwargs):
        path = str(path)
        if path.endswith(".meta.json"):
            return (
                b'{"path": "history/20260801T120000_abcd1234.py",'
                b' "result_path": "history/20260801T120000_abcd1234.result.json"}\n'
            )
        if path.endswith(".result.json"):
            return (
                b'{"stdout": "42", "stderr": "", "exit_code": 0,'
                b' "code_path": "history/20260801T120000_abcd1234.py"}\n'
            )
        return b"print(42)\n"

    fake_files.read.side_effect = _read
    fake_commands = MagicMock()
    fake_commands.run.return_value = SimpleNamespace(stdout="", stderr="", exit_code=0)
    fake_sandbox = MagicMock()
    fake_sandbox.files = fake_files
    fake_sandbox.commands = fake_commands
    fake_sandbox.claim_name = "sandbox-claim-test"
    fake_sandbox.sandbox_id = "sandbox-test"
    fake_sandbox.is_active = True
    fake_sandbox.status.return_value = ("SandboxReady", "ok")

    reset_sandbox_handle_for_tests()
    with patch("tools.sandbox.claim_sandbox", return_value=fake_sandbox):
        out = list_code_execution_history(limit=5)

    assert "20260801T120000_abcd1234.py" in out
    assert "sandbox-claim-test" in out
    assert "print(42)" in out
    assert "result_name" in out
    assert '"stdout": "42"' in out or '"stdout": "42"' in out.replace(" ", "")


def test_list_code_execution_history_missing_dir(monkeypatch):
    """Missing history/ returns empty success, not a communication error."""
    monkeypatch.setenv("SANDBOX_BACKEND", "agent-sandbox")

    fake_files = MagicMock()
    fake_files.list.side_effect = RuntimeError(
        "Failed to communicate with the sandbox at "
        "http://10.244.0.18:8888/list/history"
    )
    fake_commands = MagicMock()
    fake_commands.run.return_value = SimpleNamespace(stdout="", stderr="", exit_code=0)
    fake_sandbox = MagicMock()
    fake_sandbox.files = fake_files
    fake_sandbox.commands = fake_commands
    fake_sandbox.claim_name = "sandbox-claim-test"
    fake_sandbox.sandbox_id = "sandbox-test"
    fake_sandbox.is_active = True
    fake_sandbox.status.return_value = ("SandboxReady", "ok")

    reset_sandbox_handle_for_tests()
    with patch("tools.sandbox.claim_sandbox", return_value=fake_sandbox):
        out = list_code_execution_history(limit=5)

    assert "No code-execution history" in out


def test_code_execution_history_without_sandbox_backend(monkeypatch):
    """History still requires agent-sandbox backend (not an in-process exec path)."""
    monkeypatch.setenv("SANDBOX_BACKEND", "local")
    result = code_execution_history.invoke({"limit": 5})
    assert "only available" in result.lower() or "History" in result


def test_requires_code_execution_detector():
    from nodes import _requires_code_execution

    assert _requires_code_execution("execute this code: print(1)", "run it")
    assert _requires_code_execution("Write a python function for fibonacci", "code")
    assert _requires_code_execution(
        "compute the sum of 1..100 using python", "math"
    )
    assert _requires_code_execution(
        "get the result of this code:\n```python\nprint(2+2)\n```", "run"
    )
    assert not _requires_code_execution("Who won the match last night?", "sports")
    assert not _requires_code_execution(
        "Calculate Q3 revenue growth from internal docs", "finance"
    )


def test_clamp_code_plan_collapses_fanout():
    from nodes import _clamp_code_plan

    plan, specs = _clamp_code_plan(
        "execute this code: print(1)",
        [
            "Execute the code",
            "Call code_interpreter again",
            "Check code execution history",
        ],
        ["general", "general", "general"],
    )
    assert plan == ["Execute the code"]
    assert specs == ["general"]


def test_has_sandbox_evidence():
    from nodes import _has_sandbox_evidence

    assert _has_sandbox_evidence(
        "[agent-sandbox claim=c sandbox=s history=history/a.py result=history/a.result.json]\n42"
    )
    assert not _has_sandbox_evidence("I think the answer is 42")


def test_verbatim_code_output_preserves_stdout():
    from nodes import (
        _extract_verbatim_code_blocks,
        _verbatim_code_specialist_output,
    )

    tool = (
        "[agent-sandbox claim=c sandbox=s history=history/a.py "
        "result=history/a.result.json]\n"
        "python-sandbox-warmpool-5m8pd\n"
        "3\n"
        "python-sandbox-warmpool-5m8pd\n"
        "python-sandbox-warmpool-5m8pd"
    )
    specialist = _verbatim_code_specialist_output(tool)
    blocks = _extract_verbatim_code_blocks(specialist)
    assert blocks
    assert "python-sandbox-warmpool-5m8pd\n3\npython-sandbox-warmpool-5m8pd" in blocks[-1]
    assert "9" not in blocks[-1].splitlines()
