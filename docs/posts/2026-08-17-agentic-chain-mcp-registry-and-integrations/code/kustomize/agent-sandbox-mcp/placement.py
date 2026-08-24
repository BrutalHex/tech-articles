"""Cluster placement defaults for whatever tools this MCP process advertises.

This module inspects each tool's JSON schema: if a property is named
``namespace``, ``warmpool``, or ``shutdown_after_seconds``, omitted args
are filled from this pod's env and the schema is marked optional.
"""

from __future__ import annotations

import json
import os
from typing import Any

_PLACEMENT_KEYS = ("namespace", "warmpool", "shutdown_after_seconds")

_GET_SANDBOX_CONFIG_DESCRIPTION = (
    "Return this MCP server's default sandbox placement: warmpool name, "
    "Kubernetes namespace, and claim TTL. Callers can omit those arguments "
    "on any advertised tool that accepts them; this server fills blanks. "
    "Use this tool only when you need to inspect the values."
)


def sandbox_defaults() -> dict[str, Any]:
    """Placement configured on this MCP Deployment, not on the agent."""
    shutdown_raw = os.getenv("SANDBOX_SHUTDOWN_AFTER_SECONDS", "180").strip()
    try:
        shutdown = int(shutdown_raw)
    except ValueError:
        shutdown = 180
    namespace = (
        os.getenv("SANDBOX_NAMESPACE", "").strip()
        or os.getenv("POD_NAMESPACE", "").strip()
        or "agentic-chain"
    )
    return {
        "warmpool": os.getenv("SANDBOX_WARMPOOL", "python-sandbox-warmpool").strip()
        or "python-sandbox-warmpool",
        "namespace": namespace,
        "shutdown_after_seconds": shutdown,
    }


def get_sandbox_config() -> dict[str, Any]:
    return sandbox_defaults()


def tool_input_schema(tool: Any) -> dict:
    """JSON Schema for a FastMCP / MCP tool, if one is attached."""
    for attr in ("parameters", "inputSchema", "input_schema"):
        schema = getattr(tool, attr, None)
        if isinstance(schema, dict):
            return schema
    return {}


def apply_sandbox_defaults(args: dict | None, schema: dict | None = None) -> dict:
    """Fill blank placement args that this tool's schema actually accepts.

    No tool-name allow-list. A future write tool that takes ``namespace``
    is filled the same way as today's command runner.
    """
    out = dict(args or {})
    defaults = sandbox_defaults()
    props = (schema or {}).get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        props = {}
    for key in _PLACEMENT_KEYS:
        if key not in props:
            continue
        if out.get(key) in (None, ""):
            out[key] = defaults[key]
    return out


def optionalize_placement_schema(schema: dict, defaults: dict[str, Any] | None = None) -> dict:
    """Mark placement properties optional and stamp server defaults into the schema."""
    defaults = defaults or sandbox_defaults()
    schema = json.loads(json.dumps(schema))
    props = schema.get("properties") or {}
    drop = {key for key in _PLACEMENT_KEYS if key in props}
    required = [r for r in (schema.get("required") or []) if r not in drop]
    for key in _PLACEMENT_KEYS:
        spec = props.get(key)
        if not isinstance(spec, dict):
            continue
        spec["default"] = defaults[key]
        desc = (spec.get("description") or "").rstrip()
        extra = f" Optional. This server defaults to {defaults[key]!r} if omitted."
        if extra.strip() not in desc:
            spec["description"] = f"{desc}{extra}".strip()
        props[key] = spec
    schema["properties"] = props
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)
    return schema


def _patch_tool_schema(tool: Any) -> Any:
    schema = tool_input_schema(tool)
    props = schema.get("properties") or {}
    if not any(key in props for key in _PLACEMENT_KEYS):
        return tool
    patched = optionalize_placement_schema(schema)
    for attr in ("parameters", "inputSchema", "input_schema"):
        if not isinstance(getattr(tool, attr, None), dict):
            continue
        if hasattr(tool, "model_copy"):
            try:
                return tool.model_copy(update={attr: patched})
            except Exception:
                pass
        try:
            setattr(tool, attr, patched)
            return tool
        except Exception:
            try:
                object.__setattr__(tool, attr, patched)
                return tool
            except Exception:
                pass
    return tool


async def _schema_from_call_context(context: Any) -> dict:
    name = getattr(getattr(context, "message", None), "name", "") or ""
    ctx = getattr(context, "fastmcp_context", None)
    if ctx is None:
        return {}
    mcp = getattr(ctx, "fastmcp", None)
    if mcp is None or not hasattr(mcp, "get_tool"):
        return {}
    try:
        tool = await mcp.get_tool(name)
    except Exception:
        return {}
    return tool_input_schema(tool)


def install_placement_defaults(mcp_server: Any) -> None:
    """Middleware + get_sandbox_config on an existing FastMCP server."""
    from fastmcp.server.middleware import Middleware, MiddlewareContext

    class PlacementDefaultsMiddleware(Middleware):
        async def on_call_tool(self, context: MiddlewareContext, call_next):
            current = getattr(context.message, "arguments", None)
            schema = await _schema_from_call_context(context)
            filled = apply_sandbox_defaults(
                current if isinstance(current, dict) else {},
                schema,
            )
            if filled != (current or {}):
                try:
                    context.message.arguments = filled
                except Exception:
                    object.__setattr__(context.message, "arguments", filled)
            return await call_next(context)

        async def on_list_tools(self, context: MiddlewareContext, call_next):
            tools = await call_next(context)
            return [_patch_tool_schema(tool) for tool in (tools or [])]

    mcp_server.add_middleware(PlacementDefaultsMiddleware())
    mcp_server.tool(
        name="get_sandbox_config",
        description=_GET_SANDBOX_CONFIG_DESCRIPTION,
    )(get_sandbox_config)
