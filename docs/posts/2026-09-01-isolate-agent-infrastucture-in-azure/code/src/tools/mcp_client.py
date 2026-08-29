"""Registry-backed MultiServerMCPClient.

Each specialist turn re-fetches the in-cluster MCP registry and opens
one sticky session per published remote.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from contextlib import AsyncExitStack
from typing import Any, Callable, Iterable

import httpx

_logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_URL = "http://mcp-registry:8080"

Fetcher = Callable[[], dict[str, dict[str, Any]]]

# Write dumps often echo the file (redirect syntax, or a long indented listing).
_FILE_REDIRECT = re.compile(r">\s*[\w./-]+\.\w+")
_INDENTED_LINE = re.compile(r"(?m)^\s{4,}\S")


def flatten_mcp_result(result: Any) -> str:
    """Unwrap LangChain/MCP content blocks to the inner tool text."""
    if result is None:
        return ""
    if isinstance(result, str):
        parsed = _loads_json(result)
        if parsed is not None and not isinstance(parsed, (str, int, float, bool)):
            return flatten_mcp_result(parsed)
        return result
    if isinstance(result, list):
        parts = [flatten_mcp_result(item) for item in result]
        parts = [p for p in parts if p]
        if len(parts) == 1:
            return parts[0]
        return "\n".join(parts) if parts else json.dumps(result)
    if isinstance(result, dict):
        if "text" in result and result.get("type") == "text":
            return flatten_mcp_result(result.get("text"))
        return json.dumps(result)
    return str(result)


def _loads_json(text: str) -> Any:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def exec_result_fields(result: str) -> dict[str, str] | None:
    """Find {stdout, stderr, exit_code} inside a flattened tool payload."""
    return _fields_from_value(_loads_json(flatten_mcp_result(result)))


def _fields_from_value(value: Any) -> dict[str, str] | None:
    if isinstance(value, list):
        for item in value:
            found = _fields_from_value(item)
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None
    if "stdout" in value or "exit_code" in value:
        exit_code = value.get("exit_code")
        return {
            "stdout": str(value.get("stdout") or ""),
            "stderr": str(value.get("stderr") or ""),
            "exit_code": "" if exit_code is None else str(exit_code),
        }
    text = value.get("text")
    if isinstance(text, str):
        inner = _loads_json(text)
        if inner is not None:
            return _fields_from_value(inner)
    return None


def _stdout_is_source_listing(stdout: str) -> bool:
    """True when stdout is the written program, not the program's output."""
    text = stdout or ""
    if _FILE_REDIRECT.search(text):
        return True
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return len(lines) >= 4 and bool(_INDENTED_LINE.search(text))


def looks_like_exec_result(result: str) -> bool:
    """True when a bound tool returned command output, not a file-write dump.

    Create/write/upload payloads that echo source still contain ``stdout``
    and ``exit_code``. Those must not count as the program having run.
    """
    text = flatten_mcp_result(result)
    fields = exec_result_fields(text)
    has_shape = bool(
        fields is not None
        or (
            re.search(r"\bexit_code\b", text)
            and re.search(r"\bstdout\b", text, re.I)
        )
    )
    if not has_shape:
        return False
    stdout = fields["stdout"] if fields else text
    return not _stdout_is_source_listing(stdout)


def classify_mcp_kind(server_key: str) -> str:
    """Classify a registry server from its published catalog key."""
    key = (server_key or "").lower()
    if "sandbox" in key:
        return "sandbox-mcp"
    if "fetch" in key:
        return "web"
    return "mcp"


def _set_tool_metadata(tool: Any, extra: dict[str, Any]) -> None:
    current = getattr(tool, "metadata", None)
    merged = dict(current or {})
    merged.update(extra)
    try:
        tool.metadata = merged
        return
    except Exception:
        pass
    try:
        object.__setattr__(tool, "metadata", merged)
    except Exception:
        pass


def tag_mcp_tools(tools: Iterable[Any], server_key: str) -> list[Any]:
    """Stamp each LangChain tool with the registry server it came from."""
    tagged = list(tools or [])
    kind = classify_mcp_kind(server_key)
    for tool in tagged:
        _set_tool_metadata(
            tool,
            {"mcp_server": server_key, "mcp_kind": kind},
        )
    return tagged


def format_discovered_mcp_tools(tools: Iterable[Any]) -> str:
    """Prompt appendix: live tools/list from this turn's registry session."""
    rows: list[str] = []
    for tool in tools or []:
        name = getattr(tool, "name", "") or ""
        if not name:
            continue
        desc = (getattr(tool, "description", None) or "").strip()
        if desc:
            desc = desc.split("\n")[0].strip()
        meta = getattr(tool, "metadata", None) or {}
        server = meta.get("mcp_server") or "mcp"
        kind = meta.get("mcp_kind") or ""
        origin = server if not kind else f"{server}, {kind}"
        if desc:
            rows.append(f"- `{name}` [{origin}]: {desc}")
        else:
            rows.append(f"- `{name}` [{origin}]")
    if not rows:
        return (
            "No MCP tools are currently available from the registry. "
            "Do not invent tool names or results."
        )
    return (
        "MCP tools discovered from the live registry (authoritative; "
        "use only these names and argument schemas):\n" + "\n".join(rows)
    )


def _safe_server_key(name: str) -> str:
    tail = name.rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", tail).strip("-")
    return cleaned or "mcp"


def _incluster_http(url: str) -> str:
    """Registry remotes must be https://; in-cluster MCP servers speak HTTP."""
    if url.startswith("https://") and ".svc.cluster.local" in url:
        return "http://" + url[len("https://") :]
    return url


def _transport_for(remote_type: str) -> str:
    kind = (remote_type or "streamable-http").strip().lower()
    if kind in {"streamable-http", "streamable_http", "http"}:
        return "streamable_http"
    if kind in {"sse", "server-sent-events"}:
        return "sse"
    return "streamable_http"


def _extract_servers(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    servers = payload.get("servers")
    if isinstance(servers, list):
        return servers
    return []


def _server_detail(item: Any) -> dict:
    if not isinstance(item, dict):
        return {}
    inner = item.get("server")
    if isinstance(inner, dict):
        return inner
    return item


def fetch_registry_servers() -> dict[str, dict[str, Any]]:
    """GET the registry and return MultiServerMCPClient connection entries."""
    base = os.getenv("MCP_REGISTRY_URL", DEFAULT_REGISTRY_URL).rstrip("/")
    urls = [
        f"{base}/v0.1/servers?version=latest",
        f"{base}/v0.1/servers",
        f"{base}/v0/servers",
    ]
    last_error: Exception | None = None
    payload: Any = None
    for url in urls:
        try:
            resp = httpx.get(url, timeout=8.0)
            resp.raise_for_status()
            payload = resp.json()
            last_error = None
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            _logger.info("registry list failed for %s: %s", url, exc)
    if last_error is not None and payload is None:
        _logger.warning("MCP registry unreachable at %s: %s", base, last_error)
        return {}

    connections: dict[str, dict[str, Any]] = {}
    for item in _extract_servers(payload):
        detail = _server_detail(item)
        name = str(detail.get("name") or "").strip()
        rems = detail.get("remotes") or []
        if not name or not isinstance(rems, list):
            continue
        for remote in rems:
            if not isinstance(remote, dict):
                continue
            url = _incluster_http(str(remote.get("url") or "").strip())
            if not url:
                continue
            key = _safe_server_key(name)
            if key in connections:
                key = f"{key}-{len(connections)}"
            connections[key] = {
                "url": url,
                "transport": _transport_for(str(remote.get("type") or "")),
            }
            break
    return connections


def make_multiserver_client(*fetchers: Fetcher):
    """Build a MultiServerMCPClient from live registry (or extra) fetchers."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    connections: dict[str, dict[str, Any]] = {}
    used = fetchers or (fetch_registry_servers,)
    for fn in used:
        try:
            connections.update(fn() or {})
        except Exception as exc:  # noqa: BLE001
            _logger.warning("MCP server fetcher %s failed: %s", getattr(fn, "__name__", fn), exc)
    return MultiServerMCPClient(connections)


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def _runner() -> None:
        result["value"] = asyncio.run(coro)

    thread = threading.Thread(target=_runner, name="mcp-get-tools", daemon=True)
    thread.start()
    thread.join()
    if "value" not in result:
        raise RuntimeError("MCP async invoke failed in worker thread")
    return result["value"]


class StickyMCPSessions:
    """One streamable-HTTP MCP session per registry server, held for a specialist turn.

    Agent Sandbox MCP labels claims with the session id, so create and
    execute must share a session. Fetchers run on enter so each graph call
    sees the live registry.
    """

    def __init__(self, *fetchers: Fetcher) -> None:
        self._fetchers = fetchers or (fetch_registry_servers,)
        self.tools: list[Any] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._error: BaseException | None = None

    def __enter__(self) -> "StickyMCPSessions":
        self._thread = threading.Thread(
            target=self._thread_main, name="mcp-sticky-sessions", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=60):
            self._closed.set()
            raise TimeoutError("timed out opening sticky MCP sessions")
        if self._error is not None:
            raise self._error
        return self

    def __exit__(self, *exc: object) -> None:
        self._closed.set()
        if self._thread is not None:
            self._thread.join(timeout=20)

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._hold())
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
            self._ready.set()
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _hold(self) -> None:
        from langchain_mcp_adapters.tools import load_mcp_tools as load_from_session

        client = make_multiserver_client(*self._fetchers)
        async with AsyncExitStack() as stack:
            loaded: list[Any] = []
            for name in list(client.connections):
                try:
                    session = await stack.enter_async_context(client.session(name))
                    session_tools = await load_from_session(session)
                    loaded.extend(tag_mcp_tools(session_tools or [], name))
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("sticky session for %s failed: %s", name, exc)
            self.tools = loaded
            _logger.info(
                "sticky MCP tools from registry: %s",
                [getattr(t, "name", "") for t in loaded] or "(none)",
            )
            self._ready.set()
            await self._loop.run_in_executor(None, self._closed.wait)  # type: ignore[union-attr]

    def invoke(self, tool: Any, args: dict) -> str:
        if self._loop is None:
            raise RuntimeError("sticky MCP sessions are not running")
        fut = asyncio.run_coroutine_threadsafe(tool.ainvoke(args), self._loop)
        result = fut.result(timeout=int(os.getenv("SANDBOX_EXEC_TIMEOUT", "180")))
        return flatten_mcp_result(result)


def filter_sandbox_mcp_tools(tools: Iterable[Any]) -> list[Any]:
    """Keep tools tagged as sandbox-mcp from the live registry session."""
    return [
        t
        for t in (tools or [])
        if (getattr(t, "metadata", None) or {}).get("mcp_kind") == "sandbox-mcp"
    ]


def invoke_tool_sync(tool: Any, args: dict, runtime: StickyMCPSessions | None = None) -> str:
    """Invoke an MCP/LangChain tool from the sync graph worker."""
    if runtime is not None:
        return runtime.invoke(tool, args)
    try:
        result = tool.invoke(args)
    except NotImplementedError:
        result = _run_async(tool.ainvoke(args))
    return flatten_mcp_result(result)


__all__ = [
    "StickyMCPSessions",
    "classify_mcp_kind",
    "exec_result_fields",
    "fetch_registry_servers",
    "filter_sandbox_mcp_tools",
    "flatten_mcp_result",
    "format_discovered_mcp_tools",
    "invoke_tool_sync",
    "looks_like_exec_result",
    "make_multiserver_client",
    "tag_mcp_tools",
]
