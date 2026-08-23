"""Unit tests for registry-backed MCP client helpers (HTTP mocked)."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tools.mcp_client import (
    classify_mcp_kind,
    fetch_registry_servers,
    filter_sandbox_mcp_tools,
    flatten_mcp_result,
    format_discovered_mcp_tools,
    invoke_tool_sync,
    looks_like_exec_result,
    tag_mcp_tools,
)
from nodes import (
    _bind_specialist_tools,
    _clamp_code_plan,
    _has_sandbox_evidence,
    _invoke_with_tools,
    _requires_code_execution,
    _sandbox_exec_ran,
    _tool_source,
    _verbatim_code_specialist_output,
    critic_node,
    current_date_instruction,
    specialist_node,
)
from specialist_config import build_specialist_config
from specialists import SPECIALIST_TOOL_KEYS


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_registry_servers_parses_remotes():
    payload = {
        "servers": [
            {
                "server": {
                    "name": "io.modelcontextprotocol.anonymous/fetch",
                    "remotes": [
                        {
                            "type": "streamable-http",
                            "url": "http://mcp-fetch:8000/mcp",
                        }
                    ],
                }
            },
            {
                "server": {
                    "name": "io.modelcontextprotocol.anonymous/agent-sandbox",
                    "remotes": [
                        {
                            "type": "streamable-http",
                            "url": "http://agent-sandbox-mcp:8000/mcp",
                        }
                    ],
                }
            },
        ]
    }
    with patch("tools.mcp_client.httpx.get", return_value=_FakeResp(payload)):
        conns = fetch_registry_servers()
    assert "fetch" in conns
    assert conns["fetch"]["url"] == "http://mcp-fetch:8000/mcp"
    assert conns["fetch"]["transport"] == "streamable_http"
    assert "agent-sandbox" in conns


def test_fetch_registry_servers_empty_on_error():
    with patch("tools.mcp_client.httpx.get", side_effect=RuntimeError("down")):
        assert fetch_registry_servers() == {}


def test_filter_sandbox_mcp_tools_uses_registry_kind():
    sandbox = SimpleNamespace(
        name="custom_exec",
        metadata={"mcp_server": "agent-sandbox", "mcp_kind": "sandbox-mcp"},
    )
    web = SimpleNamespace(
        name="fetch",
        metadata={"mcp_server": "fetch", "mcp_kind": "web"},
    )
    names = [t.name for t in filter_sandbox_mcp_tools([sandbox, web])]
    assert names == ["custom_exec"]


def test_tag_mcp_tools_classifies_by_catalog_key():
    create = SimpleNamespace(name="claim_pool", metadata=None)
    exec_ = SimpleNamespace(name="run", metadata=None)
    tagged = tag_mcp_tools([create, exec_], "agent-sandbox")
    assert tagged[0].metadata["mcp_server"] == "agent-sandbox"
    assert tagged[0].metadata["mcp_kind"] == "sandbox-mcp"
    assert classify_mcp_kind("agent-sandbox") == "sandbox-mcp"
    assert classify_mcp_kind("runtime") == "mcp"

    fetch_tool = SimpleNamespace(
        name="fetch",
        args={"url": {"type": "string"}},
        description="Fetches a URL from the internet as markdown",
        metadata=None,
    )
    tagged_web = tag_mcp_tools([fetch_tool], "fetch")
    assert tagged_web[0].metadata["mcp_kind"] == "web"
    assert tagged_web[0].metadata["mcp_server"] == "fetch"


def test_format_discovered_mcp_tools_lists_live_inventory():
    tool = SimpleNamespace(
        name="fetch",
        description="Fetches a URL from the internet and extracts markdown.",
        metadata={"mcp_server": "fetch", "mcp_kind": "web"},
    )
    text = format_discovered_mcp_tools([tool])
    assert "`fetch`" in text
    assert "fetch, web" in text
    assert "live registry" in text.lower()


def test_tool_source_uses_mcp_metadata_not_hardcoded_fetch():
    fetch_tool = SimpleNamespace(
        name="fetch",
        metadata={"mcp_server": "fetch", "mcp_kind": "web"},
    )
    sandbox_tool = SimpleNamespace(
        name="run",
        metadata={"mcp_server": "agent-sandbox", "mcp_kind": "sandbox-mcp"},
    )
    other = SimpleNamespace(
        name="lookup",
        metadata={"mcp_server": "records", "mcp_kind": "mcp"},
    )
    assert _tool_source("fetch", fetch_tool) == "web"
    assert _tool_source("run", sandbox_tool) == "sandbox-mcp"
    assert _tool_source("lookup", other) == "mcp"
    assert _tool_source("research_search") == "internal docs"
    assert _tool_source("fetch") == "mcp"


def test_specialist_prompts_do_not_hardcode_fetch_tool_name():
    from specialists import SPECIALIST_PROMPTS

    for prompt in SPECIALIST_PROMPTS.values():
        assert "Call fetch (MCP)" not in prompt
        assert "live registry" in prompt.lower() or "bound" in prompt.lower()


def test_specialist_config_defers_mcp_to_live_registry():
    """Static specialist config never bakes in fetch; MCP is a live placeholder."""
    for keys in SPECIALIST_TOOL_KEYS.values():
        assert "mcp" in keys
        assert "fetch" not in keys
        assert "web_search" not in keys

    with patch("specialist_config.build_rag_tools", return_value={}):
        cfg = build_specialist_config(object(), None, "unused", 0)
    assert set(cfg) == set(SPECIALIST_TOOL_KEYS)
    for spec in cfg.values():
        assert "fetch" not in spec["static_tools"]
        assert "mcp" not in spec["static_tools"]


def _mcp_fetch_and_sandbox():
    fetch = SimpleNamespace(
        name="fetch",
        description="Fetches a URL from the internet as markdown",
        metadata={"mcp_server": "fetch", "mcp_kind": "web"},
    )
    create = SimpleNamespace(
        name="claim_pool",
        description="Claim a sandbox from the warm pool",
        args={"warmpool": {}, "namespace": {}},
        metadata={"mcp_server": "agent-sandbox", "mcp_kind": "sandbox-mcp"},
    )
    exec_ = SimpleNamespace(
        name="run",
        description="Run a command in the sandbox",
        args={"command": {}, "sandbox_claim_name": {}, "namespace": {}},
        metadata={"mcp_server": "agent-sandbox", "mcp_kind": "sandbox-mcp"},
    )
    return fetch, create, exec_


def test_bind_specialist_tools_uses_live_mcp_inventory():
    """LangGraph specialist binding expands registry MCP tools at invoke time."""
    fetch, create, exec_ = _mcp_fetch_and_sandbox()
    llm = MagicMock()
    bound = MagicMock()
    llm.bind_tools.return_value = bound
    research = SimpleNamespace(name="research_search")
    config = {"llm": llm, "static_tools": {"research_search": research}}

    bound_llm, by_name = _bind_specialist_tools(
        config, [fetch, create, exec_], needs_code=False
    )
    assert bound_llm is bound
    assert set(by_name) >= {"fetch", "claim_pool", "run", "research_search"}
    bound_names = {t.name for t in llm.bind_tools.call_args[0][0]}
    assert bound_names == set(by_name)

    llm.bind_tools.reset_mock()
    bound_llm, by_name = _bind_specialist_tools(
        config, [fetch, create, exec_], needs_code=True
    )
    assert "fetch" not in by_name
    assert "research_search" not in by_name
    assert set(by_name) == {"claim_pool", "run"}


def test_specialist_node_invokes_dynamic_mcp_fetch():
    """The specialist LangGraph node calls a registry-discovered fetch tool."""
    fetch, create, exec_ = _mcp_fetch_and_sandbox()

    class _Runtime:
        def __init__(self, *args, **kwargs):
            self.tools = [fetch, create, exec_]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def invoke(self, tool, args):
            assert tool is fetch
            assert "dw.com" in str(args.get("url", ""))
            return "Contents of https://www.dw.com/en/top-stories/s-9097:\n# Example headline"

    class _LLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            names = {getattr(t, "name", "") for t in tools}
            assert "fetch" in names
            return self

        def invoke(self, _messages):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content="",
                    tool_calls=[
                        {
                            "name": "fetch",
                            "args": {"url": "https://www.dw.com/en/top-stories/s-9097"},
                            "id": "call-1",
                        }
                    ],
                )
            return SimpleNamespace(
                content="Top headline: Example headline",
                tool_calls=[],
            )

    llm = _LLM()
    specialist_config = {
        "general": {"llm": llm, "static_tools": {}},
    }
    with patch("nodes.StickyMCPSessions", _Runtime):
        out = specialist_node(
            {
                "specialist_type": "general",
                "subtask": "Fetch the DW top stories page and quote the headline",
                "task": "Fetch https://www.dw.com/en/top-stories/s-9097 and quote the top headline.",
                "query_id": 0,
                "iteration": 0,
            },
            specialist_config,
        )

    result = out["specialist_results"][0]
    assert result["tools_used"] == ["fetch"]
    assert "Example headline" in result["output"]


def test_invoke_tool_sync_json():
    tool = MagicMock()
    tool.invoke.return_value = {"stdout": "42", "exit_code": 0}
    assert '"stdout": "42"' in invoke_tool_sync(tool, {})


def test_no_legacy_code_tools_exported():
    import tools

    assert "code_interpreter" not in tools.TOOL_REGISTRY
    assert "code_execution_history" not in tools.TOOL_REGISTRY
    assert "web_search" not in tools.TOOL_REGISTRY
    assert "fetch" not in tools.TOOL_REGISTRY
    assert not hasattr(tools, "code_interpreter")
    assert not hasattr(tools, "code_execution_history")


def test_requires_code_execution_detector():
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
    plan, specs = _clamp_code_plan(
        "execute this code: print(1)",
        [
            "Execute the code",
            "Run the script again",
            "Check history",
        ],
        ["general", "general", "general"],
    )
    assert plan == ["Execute the code"]
    assert specs == ["general"]


def _mcp_content_payload(stdout: str, exit_code: int = 0) -> list:
    inner = json.dumps(
        {"exit_code": exit_code, "stdout": stdout, "stderr": ""},
        separators=(",", ":"),
    )
    return [{"type": "text", "text": inner, "id": "lc_test"}]


def test_flatten_mcp_result_unwraps_content_blocks():
    payload = _mcp_content_payload("610\n")
    flat = flatten_mcp_result(payload)
    parsed = json.loads(flat)
    assert parsed["stdout"] == "610\n"
    assert parsed["exit_code"] == 0
    assert "type" not in parsed


def test_looks_like_exec_result_rejects_source_write():
    write = flatten_mcp_result(
        _mcp_content_payload(
            "def fibonacci(n):\n    if n <= 0:\n        return 0\n"
            "    elif n == 1:\n        return 1\n    else:\n"
            "        return fibonacci(n - 1) + fibonacci(n - 2)\n\n"
            "result = fibonacci(15)\nprint(result) > script.py\n"
        )
    )
    assert looks_like_exec_result(write) is False
    assert _sandbox_exec_ran([("execute_command", write)]) is False


def test_looks_like_exec_result_accepts_program_output():
    ran = flatten_mcp_result(_mcp_content_payload("610\n"))
    assert looks_like_exec_result(ran) is True
    assert looks_like_exec_result("stdout: 42\nexit_code: 0") is True
    assert _sandbox_exec_ran([("execute_command", ran)]) is True


def test_invoke_with_tools_does_not_stop_on_file_write():
    write = flatten_mcp_result(
        _mcp_content_payload(
            "def fibonacci(n):\n    return n\nprint(result) > script.py\n"
        )
    )
    ran = flatten_mcp_result(_mcp_content_payload("610\n"))

    class _LLM:
        def __init__(self):
            self.calls = 0

        def invoke(self, _messages):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content="",
                    tool_calls=[
                        {
                            "name": "run",
                            "args": {"command": "write the file"},
                            "id": "c1",
                        }
                    ],
                )
            if self.calls == 2:
                return SimpleNamespace(
                    content="",
                    tool_calls=[
                        {
                            "name": "run",
                            "args": {"command": "run the program"},
                            "id": "c2",
                        }
                    ],
                )
            return SimpleNamespace(content="done", tool_calls=[])

    class _Runtime:
        def invoke(self, _tool, args):
            if "run the program" in str(args.get("command") or ""):
                return ran
            return write

    tool = SimpleNamespace(name="run", metadata={"mcp_kind": "sandbox-mcp"})
    _response, names, results = _invoke_with_tools(
        _LLM(),
        {"run": tool},
        [],
        stop_after_sandbox_exec=True,
        runtime=_Runtime(),
    )
    assert names == ["run", "run"]
    assert results[0][1] == write
    assert results[1][1] == ran
    assert _sandbox_exec_ran(results) is True
    assert looks_like_exec_result(results[0][1]) is False
    assert looks_like_exec_result(results[1][1]) is True


def test_has_sandbox_evidence():
    assert _has_sandbox_evidence(
        "### sandbox execution result (verbatim)\n42",
    )
    assert _has_sandbox_evidence("stdout: 42\nexit_code: 0")
    assert not _has_sandbox_evidence("I think the answer is 42")


def test_verbatim_code_output_preserves_stdout():
    from nodes import _extract_verbatim_code_blocks

    tool = '{"stdout": "610\\n", "stderr": "", "exit_code": 0}'
    specialist = _verbatim_code_specialist_output(tool)
    blocks = _extract_verbatim_code_blocks(specialist)
    assert blocks
    assert "610" in blocks[-1]


def test_current_date_instruction_uses_today():
    from datetime import date

    text = current_date_instruction()
    assert date.today().isoformat() in text
    assert "Today's date is" in text
    assert "training-cutoff" in text


def test_specialist_system_prompt_includes_today():
    from datetime import date

    captured: dict[str, str] = {}

    class _Runtime:
        def __init__(self, *args, **kwargs):
            self.tools = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class _LLM:
        def bind_tools(self, _tools):
            return self

        def invoke(self, messages):
            captured["system"] = messages[0].content
            return SimpleNamespace(content="ok", tool_calls=[])

    with patch("nodes.StickyMCPSessions", _Runtime):
        specialist_node(
            {
                "specialist_type": "general",
                "subtask": "Who won last night?",
                "task": "Who won last night?",
                "query_id": 0,
                "iteration": 0,
            },
            {"general": {"llm": _LLM(), "static_tools": {}}},
        )

    assert date.today().isoformat() in captured["system"]
    assert captured["system"].startswith("Today's date is")


def test_critic_prompt_includes_today():
    from datetime import date

    captured: dict[str, str] = {}

    class _LLM:
        def with_structured_output(self, _cls):
            class _Bound:
                def invoke(self, msgs):
                    captured["text"] = msgs[0].content
                    return SimpleNamespace(
                        needs_improvement=False,
                        critique="ok",
                    )

            return _Bound()

    critic_node(
        {
            "task": "Who won last night?",
            "final_answer": "Team A won 2-1.",
            "combined_results": "Team A won 2-1.",
            "iteration": 0,
        },
        _LLM(),
    )
    assert date.today().isoformat() in captured["text"]
    assert "training cutoff" in captured["text"]


def test_critic_rejects_code_without_sandbox_execution():
    class _LLM:
        def with_structured_output(self, _cls):
            class _Bound:
                def invoke(self, _msgs):
                    return SimpleNamespace(
                        needs_improvement=False,
                        critique="looks fine",
                    )

            return _Bound()

    state = {
        "task": "execute this code: print(1)",
        "final_answer": "The result is 1 (I ran it locally).",
        "combined_results": "The result is 1",
        "specialist_results": [
            {
                "iteration": 0,
                "query_id": 0,
                "tools_used": ["fetch"],
            }
        ],
        "iteration": 0,
        "query_id": 0,
    }
    out = critic_node(state, _LLM())
    assert out["needs_improvement"] is True
    assert "execution" in out["critique"]
