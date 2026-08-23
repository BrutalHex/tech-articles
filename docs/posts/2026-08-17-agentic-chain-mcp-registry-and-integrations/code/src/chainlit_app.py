"""Chainlit UI for the multi-agent workflow.

Keeps main.py (CLI) unchanged. Reuses GraphConfig + graph_session and maps
on_event payloads into nested cl.Steps. Uses cl.context.session.id as the
LangGraph thread_id so chat sessions get durable checkpoints.

Progress is streamed live via a thread-safe queue.
"""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
from pathlib import Path
from typing import Any

# Chainlit may change process cwd; keep sibling modules (graph.py, …) importable.
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import chainlit as cl

import env_setup  # noqa: F401 — load .env / endpoints first
from config import GraphConfig, graph_session
from env_setup import CHECKPOINTS_DB_URI, CHROMA_HOST, CHROMA_PORT
from openai_config import create_chat_llm, create_embeddings, verify_openai_connectivity

# Built once per process; LLM clients are thread-safe enough for POC use.
_LLM = None
_EMBEDDINGS = None

_SENTINEL = object()


def _llm():
    global _LLM
    if _LLM is None:
        _LLM = create_chat_llm()
    return _LLM


def _embeddings():
    global _EMBEDDINGS
    if _EMBEDDINGS is None:
        _EMBEDDINGS = create_embeddings()
    return _EMBEDDINGS


def _fmt_args(args: dict | None, limit: int = 240) -> str:
    if not args:
        return ""
    for key in ("code", "query", "command", "path", "url", "content"):
        if key in args and args[key] is not None:
            text = str(args[key]).strip()
            if len(text) > limit:
                text = text[: limit - 3] + "..."
            return f"{key}={text!r}"
    text = repr(args)
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


class EventQueueBridge:
    """Worker-thread → main-loop bridge. Only puts events; never touches Chainlit."""

    def __init__(self) -> None:
        self.q: queue.Queue[tuple[str, dict] | object] = queue.Queue()

    def __call__(self, event: str, payload: dict) -> None:
        self.q.put((event, payload or {}))

    def close(self) -> None:
        self.q.put(_SENTINEL)


class LiveProgressUI:
    """Consume EventQueueBridge on the async loop and render status + Steps."""

    def __init__(self, status: cl.Message) -> None:
        self.status = status
        self._steps: dict[str, Any] = {}
        self._open_tools: dict[str, list[str]] = {}
        self._log: list[str] = []

    async def _set_status(self, line: str) -> None:
        self._log.append(line)
        tail = self._log[-12:]
        self.status.content = "**Running multi-agent graph…**\n\n" + "\n".join(
            f"- {item}" for item in tail
        )
        await self.status.update()

    async def _open_step(self, key: str, name: str, type_: str = "tool") -> Any:
        if key in self._steps:
            return self._steps[key]
        step = cl.Step(name=name, type=type_)
        await step.__aenter__()
        self._steps[key] = step
        return step

    async def _close_step(self, key: str, output: str | None = None) -> None:
        step = self._steps.pop(key, None)
        if step is None:
            return
        if output is not None:
            step.output = output
        await step.__aexit__(None, None, None)

    async def _set_output(self, key: str, output: str) -> None:
        step = self._steps.get(key)
        if step is not None:
            step.output = output

    async def handle(self, event: str, payload: dict) -> None:
        if event == "planner_start":
            await self._set_status("Planner started")
            await self._open_step("planner", "Planner", type_="llm")
            await self._set_output("planner", f"Task: {payload.get('task', '')}")
        elif event == "planner_done":
            lines = ["Plan created:"]
            for i, (specialist, step) in enumerate(
                zip(
                    payload.get("specialists", []),
                    payload.get("plan", []),
                    strict=False,
                ),
                start=1,
            ):
                lines.append(f"{i}. **{specialist}** → {step}")
            plan_text = "\n".join(lines)
            await self._set_status(
                "Plan: " + ", ".join(payload.get("specialists", []) or ["(none)"])
            )
            await self._close_step("planner", plan_text)
        elif event == "specialist_start":
            specialist = str(payload.get("specialist", "unknown"))
            key = f"specialist:{specialist}"
            await self._set_status(f"Specialist **{specialist}** working…")
            await self._open_step(key, specialist.upper(), type_="llm")
            await self._set_output(key, f"Subtask: {payload.get('subtask', '')}")
        elif event == "tool_start":
            tool_name = str(payload.get("tool", "tool"))
            source = payload.get("source", "agent")
            args_txt = _fmt_args(payload.get("args") or {})
            key = f"tool:{tool_name}:{len(self._steps)}:{id(payload)}"
            self._open_tools.setdefault(tool_name, []).append(key)
            await self._set_status(f"Calling tool **{tool_name}**…")
            step = await self._open_step(key, f"Tool: {tool_name}", type_="tool")
            step.input = args_txt or f"source={source}"
            await self._set_output(
                key,
                f"Running…\nsource={source}\n{args_txt}",
            )
        elif event == "tool_call":
            tool_name = str(payload.get("tool", "tool"))
            source = payload.get("source", "agent")
            args_txt = _fmt_args(payload.get("args") or {})
            preview = payload.get("preview") or ""
            stack = self._open_tools.get(tool_name) or []
            if stack:
                key = stack.pop()
            else:
                key = f"tool:{tool_name}:{id(payload)}"
                await self._open_step(key, f"Tool: {tool_name}", type_="tool")
            err = payload.get("error")
            label = "failed" if err else "done"
            await self._set_status(f"Tool **{tool_name}** {label}")
            body = f"source={source}\n{args_txt}\n\n{preview}".strip()
            await self._close_step(key, body)
        elif event == "specialist_done":
            specialist = str(payload.get("specialist", "unknown"))
            key = f"specialist:{specialist}"
            tools = ", ".join(payload.get("tools", [])) or "none"
            await self._set_status(f"Specialist **{specialist}** done (tools: {tools})")
            await self._close_step(key, f"Done — tools used: {tools}")
        elif event == "aggregator_done":
            n = payload.get("specialists", 0)
            await self._set_status(f"Aggregator combined {n} result(s)")
            await self._open_step("aggregator", "Aggregator", type_="tool")
            await self._close_step("aggregator", f"Combined {n} specialist result(s)")
        elif event == "synthesizer_start":
            await self._set_status("Synthesizer writing draft…")
            await self._open_step("synthesizer", "Synthesizer", type_="llm")
        elif event == "synthesizer_done":
            await self._set_status("Synthesizer finished draft")
            await self._close_step("synthesizer", "Draft answer written")
        elif event == "critic_done":
            await self._open_step("critic", "Critic", type_="llm")
            if payload.get("needs_improvement"):
                text = f"Needs improvement — replanning\n{payload.get('critique', '')}"
                await self._set_status("Critic: needs improvement → replan")
            else:
                text = f"Quality check passed\n{payload.get('critique', '')}"
                await self._set_status("Critic: quality check passed")
            await self._close_step("critic", text)
        elif event == "working_start":
            msg = payload.get("message") or "Working…"
            await self._set_status(str(msg))
        elif event == "working_done":
            pass

    async def close_all(self) -> None:
        for key in list(self._steps.keys()):
            await self._close_step(key)


def _next_query_id(graph, invoke_config: dict) -> int:
    snapshot = graph.get_state(invoke_config)
    return snapshot.values.get("query_id", 0) + 1


def _run_graph_sync(
    task: str,
    thread_id: str,
    bridge: EventQueueBridge,
    result_box: dict,
    error_box: dict,
) -> None:
    try:
        verify_openai_connectivity()
        graph_config = GraphConfig(
            db_connection=CHECKPOINTS_DB_URI,
            embedding_function=_embeddings(),
            llm=_llm(),
            chroma_host=CHROMA_HOST,
            chroma_port=CHROMA_PORT,
            on_event=bridge,
        )
        invoke_config = {"configurable": {"thread_id": thread_id}}
        with graph_session(graph_config) as graph:
            query_id = _next_query_id(graph, invoke_config)
            for _update in graph.stream(
                {"task": task, "iteration": 0, "query_id": query_id},
                config=invoke_config,
                stream_mode="updates",
            ):
                pass
            snapshot = graph.get_state(invoke_config)
            result_box["values"] = snapshot.values
    except Exception as exc:
        error_box["error"] = exc
    finally:
        bridge.close()


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("thread_id", cl.context.session.id)
    await cl.Message(
        content=(
            "Multi-agent workflow ready.\n\n"
            f"Session thread: `{cl.context.session.id}`\n\n"
            "Ask a research/finance/legal/general question. "
            "Specialists discover MCP tools from the in-cluster **MCP registry** "
            "on every turn (`tools/list` on each published remote). "
            "This POC publishes Agent Sandbox MCP (gVisor code execution) and "
            "Fetch MCP (`@modelcontextprotocol/server-fetch`)."
        ),
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    task = (message.content or "").strip()
    if not task:
        await cl.Message(content="Please enter a non-empty task.").send()
        return

    thread_id = cl.user_session.get("thread_id") or cl.context.session.id
    bridge = EventQueueBridge()
    result_box: dict[str, Any] = {}
    error_box: dict[str, Any] = {}

    status = cl.Message(content="**Running multi-agent graph…**")
    await status.send()
    ui = LiveProgressUI(status)

    worker = threading.Thread(
        target=_run_graph_sync,
        args=(task, thread_id, bridge, result_box, error_box),
        daemon=True,
    )
    worker.start()

    while True:
        try:
            item = bridge.q.get_nowait()
        except queue.Empty:
            if not worker.is_alive():
                try:
                    item = bridge.q.get_nowait()
                except queue.Empty:
                    break
            else:
                await asyncio.sleep(0.05)
                continue

        if item is _SENTINEL:
            break
        event, payload = item  # type: ignore[misc]
        try:
            await ui.handle(event, payload)
        except Exception:
            pass

    worker.join(timeout=1)
    await ui.close_all()

    if error_box.get("error") is not None:
        status.content = f"**Error:** {error_box['error']}"
        await status.update()
        return

    status.content = "**Done.**"
    await status.update()

    values = result_box.get("values") or {}
    answer = values.get("final_answer") or "No final answer generated."
    await cl.Message(content=answer).send()

    critique = values.get("critique")
    if critique and not values.get("needs_improvement"):
        async with cl.Step(name="Final Critique", type="llm") as step:
            step.output = critique
