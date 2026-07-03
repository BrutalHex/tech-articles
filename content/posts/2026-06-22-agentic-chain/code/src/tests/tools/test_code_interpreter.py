"""Smoke tests for the code_interpreter tool (no external services)."""

from tools import code_interpreter


def test_code_interpreter_prints_output():
    result = code_interpreter.invoke({"code": "print('hello from tool')"})
    assert "hello from tool" in result


def test_code_interpreter_computes():
    result = code_interpreter.invoke({"code": "print(2 + 2)"})
    assert "4" in result


def test_code_interpreter_handles_syntax_error():
    result = code_interpreter.invoke({"code": "print("})
    assert "Error executing code" in result


def test_code_interpreter_silent_success():
    result = code_interpreter.invoke({"code": "x = 1"})
    assert result == "Code executed successfully."