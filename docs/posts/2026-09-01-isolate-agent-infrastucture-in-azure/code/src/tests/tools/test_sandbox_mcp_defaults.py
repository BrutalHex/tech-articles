"""Sandbox MCP placement defaults live on the MCP server, keyed by schema."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

_WRAPPER_DIR = Path(__file__).resolve().parents[3] / "kustomize" / "agent-sandbox-mcp"
sys.path.insert(0, str(_WRAPPER_DIR))
from placement import (  # noqa: E402
    apply_sandbox_defaults,
    get_sandbox_config,
    optionalize_placement_schema,
    sandbox_defaults,
)

_CREATE_SCHEMA = {
    "type": "object",
    "properties": {
        "warmpool": {"type": "string"},
        "namespace": {"type": "string"},
        "shutdown_after_seconds": {"type": "integer"},
        "labels": {"type": "object"},
    },
    "required": ["warmpool", "namespace"],
}

_EXECUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "sandbox_claim_name": {"type": "string"},
        "namespace": {"type": "string"},
        "command": {"type": "string"},
    },
    "required": ["sandbox_claim_name", "namespace", "command"],
}

_FETCH_SCHEMA = {
    "type": "object",
    "properties": {"url": {"type": "string"}, "max_length": {"type": "integer"}},
    "required": ["url"],
}


def test_sandbox_defaults_come_from_mcp_env():
    env = {
        "SANDBOX_WARMPOOL": "custom-pool",
        "SANDBOX_NAMESPACE": "sandboxes",
        "SANDBOX_SHUTDOWN_AFTER_SECONDS": "90",
    }
    with patch.dict(os.environ, env, clear=False):
        assert sandbox_defaults() == {
            "warmpool": "custom-pool",
            "namespace": "sandboxes",
            "shutdown_after_seconds": 90,
        }


def test_sandbox_defaults_namespace_falls_back_to_pod_namespace():
    env = {"POD_NAMESPACE": "from-pod"}
    with patch.dict(os.environ, env, clear=True):
        os.environ.pop("SANDBOX_NAMESPACE", None)
        os.environ.pop("SANDBOX_WARMPOOL", None)
        os.environ.pop("SANDBOX_SHUTDOWN_AFTER_SECONDS", None)
        defaults = sandbox_defaults()
    assert defaults["namespace"] == "from-pod"
    assert defaults["warmpool"] == "python-sandbox-warmpool"
    assert defaults["shutdown_after_seconds"] == 180


def test_apply_sandbox_defaults_fills_from_schema_not_tool_name():
    with patch.dict(
        os.environ,
        {
            "SANDBOX_WARMPOOL": "python-sandbox-warmpool",
            "SANDBOX_NAMESPACE": "agentic-chain",
            "SANDBOX_SHUTDOWN_AFTER_SECONDS": "180",
        },
        clear=False,
    ):
        filled = apply_sandbox_defaults({}, _CREATE_SCHEMA)
    assert filled["warmpool"] == "python-sandbox-warmpool"
    assert filled["namespace"] == "agentic-chain"
    assert filled["shutdown_after_seconds"] == 180


def test_apply_sandbox_defaults_does_not_override_caller_values():
    filled = apply_sandbox_defaults(
        {
            "warmpool": "other-pool",
            "namespace": "other-ns",
            "shutdown_after_seconds": 10,
        },
        _CREATE_SCHEMA,
    )
    assert filled["warmpool"] == "other-pool"
    assert filled["namespace"] == "other-ns"
    assert filled["shutdown_after_seconds"] == 10


def test_apply_sandbox_defaults_fills_only_schema_fields():
    with patch.dict(os.environ, {"SANDBOX_NAMESPACE": "agentic-chain"}, clear=False):
        filled = apply_sandbox_defaults(
            {"sandbox_claim_name": "claim-1", "command": "python3 script.py"},
            _EXECUTE_SCHEMA,
        )
    assert filled["namespace"] == "agentic-chain"
    assert filled["command"] == "python3 script.py"
    assert "warmpool" not in filled


def test_apply_sandbox_defaults_ignores_tools_without_placement_fields():
    filled = apply_sandbox_defaults({"url": "https://example.com"}, _FETCH_SCHEMA)
    assert filled == {"url": "https://example.com"}


def test_apply_sandbox_defaults_without_schema_fills_nothing():
    assert apply_sandbox_defaults({}, None) == {}
    assert apply_sandbox_defaults({"command": "ls"}, {}) == {"command": "ls"}


def test_optionalize_placement_schema_drops_required_placement_fields():
    with patch.dict(
        os.environ,
        {
            "SANDBOX_WARMPOOL": "python-sandbox-warmpool",
            "SANDBOX_NAMESPACE": "agentic-chain",
        },
        clear=False,
    ):
        patched = optionalize_placement_schema(_CREATE_SCHEMA)
    assert "warmpool" not in (patched.get("required") or [])
    assert "namespace" not in (patched.get("required") or [])
    assert patched["properties"]["warmpool"]["default"] == "python-sandbox-warmpool"
    assert patched["properties"]["namespace"]["default"] == "agentic-chain"
    assert "Optional" in patched["properties"]["warmpool"]["description"]


def test_get_sandbox_config_matches_defaults():
    with patch.dict(
        os.environ,
        {
            "SANDBOX_WARMPOOL": "python-sandbox-warmpool",
            "SANDBOX_NAMESPACE": "agentic-chain",
            "SANDBOX_SHUTDOWN_AFTER_SECONDS": "180",
        },
        clear=False,
    ):
        assert get_sandbox_config() == sandbox_defaults()


def test_agent_no_longer_exports_sandbox_placement():
    import env_setup

    assert not hasattr(env_setup, "SANDBOX_WARMPOOL")
    assert not hasattr(env_setup, "SANDBOX_NAMESPACE")


def test_specialist_policy_does_not_hardcode_upstream_tool_roster():
    from specialists import _SANDBOX_MCP_POLICY

    assert "get_sandbox_config" in _SANDBOX_MCP_POLICY
    assert "bound sandbox MCP tools" in _SANDBOX_MCP_POLICY
    assert "this turn's inventory" in _SANDBOX_MCP_POLICY
    assert "Omit warmpool/namespace" in _SANDBOX_MCP_POLICY


def test_health_wrapper_is_probes_only():
    text = (_WRAPPER_DIR / "health_wrapper.py").read_text(encoding="utf-8")
    assert "install_placement_defaults" in text
    assert "/healthz" in text
    assert "/readyz" in text
    assert "_NS_TOOLS" not in text
    assert "apply_sandbox_defaults" not in text


def test_placement_module_has_no_tool_name_allowlist():
    text = (_WRAPPER_DIR / "placement.py").read_text(encoding="utf-8")
    assert "_NS_TOOLS" not in text
    assert "tools/list" in text
    assert "apply_sandbox_defaults" in text
    assert "_PLACEMENT_KEYS" in text
