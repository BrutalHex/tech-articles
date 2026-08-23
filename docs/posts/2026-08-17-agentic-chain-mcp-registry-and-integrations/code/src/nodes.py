import re
from datetime import datetime
from typing import Any, Callable, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Send
from pydantic import BaseModel, Field

from specialists import MAX_TOOL_ROUNDS, SPECIALIST_PROMPTS, VALID_SPECIALIST_TYPES
from state import OverallState
from tools import (
    StickyMCPSessions,
    filter_sandbox_mcp_tools,
    format_discovered_mcp_tools,
    invoke_tool_sync,
    looks_like_exec_result,
)

EventCallback = Callable[[str, dict], None] | None


def current_date_instruction() -> str:
    """Fresh calendar date for LLM instructions (not a training-cutoff year)."""
    now = datetime.now().astimezone()
    return (
        f"Today's date is {now.strftime('%A, %d %B %Y')} "
        f"({now.date().isoformat()}). "
        "Interpret relative dates (today, yesterday, last night, this week, "
        "last week) against this date. Do not treat a training-cutoff year "
        "as today, and do not call a source from this year 'future' or invented."
    )

# Tasks that require real sandbox execution — specialists must not answer from memory.
_CODE_EXEC_REQUEST = re.compile(
    r"(?is)("
    r"\bcode[_\s-]?interpreter\b|"
    r"\b(execute|run|eval(?:uate)?|interpret)\b.{0,60}\b(code|script|python|program|snippet)\b|"
    r"\b(code|script|python|program|snippet)\b.{0,60}\b(execute|run|eval(?:uate)?|output|result|stdout)\b|"
    r"\b(write|implement|create)\b.{0,60}\b(code|script|function|program|snippet|python)\b|"
    r"\b(get|show|return)\b.{0,40}\b(result|output)\b.{0,40}\b(code|script|program)\b|"
    r"\b(compute|calculate)\b.{0,40}\b(using|with|in)\b.{0,20}\b(code|python|script)\b|"
    r"```(?:python)?\b|"
    r"\bprint\s*\("
    r")"
)


class PlannerOutput(BaseModel):
    plan: List[str] = Field(description="List of clear subtasks")
    specialists_needed: List[str] = Field(
        description=f"List of specialist names needed. Must be one of: {sorted(VALID_SPECIALIST_TYPES)}"
    )


def _emit(on_event: EventCallback, event: str, payload: dict) -> None:
    if on_event:
        on_event(event, payload)


def _normalize_specialist(specialist_type: str) -> str:
    return specialist_type if specialist_type in VALID_SPECIALIST_TYPES else "general"


def _align_specialists_and_plan(
    specialists: List[str],
    plan: List[str],
    fallback_task: str,
) -> list[tuple[str, str]]:
    specialists = [_normalize_specialist(s) for s in specialists]
    n = max(len(specialists), len(plan), 1)

    while len(specialists) < n:
        specialists.append("general")
    while len(plan) < n:
        plan.append(plan[-1] if plan else fallback_task)

    return list(zip(specialists, plan, strict=True))


def _preview(text: str, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _tool_source(tool_name: str, tool: Any | None = None) -> str:
    """Label a tool from live MCP metadata, not a hard-coded name map."""
    if tool is not None:
        meta = getattr(tool, "metadata", None) or {}
        kind = meta.get("mcp_kind")
        if kind:
            return kind
        server = meta.get("mcp_server")
        if server:
            return server
    if tool_name.endswith("_search"):
        return "internal docs"
    return "mcp"


def _run_tool(
    tool_name: str,
    tool: Any,
    args: dict,
    on_event: EventCallback,
    runtime: StickyMCPSessions | None = None,
) -> str:
    source = _tool_source(tool_name, tool)
    _emit(
        on_event,
        "tool_start",
        {
            "tool": tool_name,
            "args": args,
            "source": source,
        },
    )
    _emit(on_event, "working_start", {"message": f"Running {tool_name}..."})
    try:
        result = invoke_tool_sync(tool, args, runtime=runtime)
    except Exception as exc:
        _emit(on_event, "working_done", {})
        _emit(
            on_event,
            "tool_call",
            {
                "tool": tool_name,
                "args": args,
                "preview": _preview(f"Error: {exc}"),
                "source": source,
                "error": True,
            },
        )
        raise
    else:
        _emit(on_event, "working_done", {})
        _emit(
            on_event,
            "tool_call",
            {
                "tool": tool_name,
                "args": args,
                "preview": _preview(result),
                "source": source,
            },
        )
        return result


def _invoke_with_tools(
    bound_llm: Any,
    tools_by_name: dict,
    messages: list,
    on_event: EventCallback = None,
    tools_invoked: list[str] | None = None,
    tool_results: list[tuple[str, str]] | None = None,
    *,
    stop_after_sandbox_exec: bool = False,
    runtime: StickyMCPSessions | None = None,
) -> tuple[Any, list[str], list[tuple[str, str]]]:
    if tools_invoked is None:
        tools_invoked = []
    if tool_results is None:
        tool_results = []

    for _round in range(MAX_TOOL_ROUNDS):
        _emit(on_event, "working_start", {"message": "Specialist thinking..."})
        try:
            response = bound_llm.invoke(messages)
        finally:
            _emit(on_event, "working_done", {})

        if not response.tool_calls:
            return response, tools_invoked, tool_results

        messages.append(response)
        saw_successful_exec = False
        for tool_call in response.tool_calls:
            if isinstance(tool_call, dict):
                name = tool_call["name"]
                args = tool_call["args"]
                tool_call_id = tool_call["id"]
            else:
                name = tool_call.name
                args = tool_call.args
                tool_call_id = tool_call.id

            tool = tools_by_name[name]
            result = _run_tool(name, tool, args, on_event, runtime=runtime)
            tools_invoked.append(name)
            tool_results.append((name, result))
            messages.append(
                ToolMessage(content=result, tool_call_id=tool_call_id)
            )
            if (
                stop_after_sandbox_exec
                and looks_like_exec_result(result)
                and not _sandbox_exec_failed(result)
            ):
                saw_successful_exec = True

        if saw_successful_exec:
            return response, tools_invoked, tool_results

    _emit(on_event, "working_start", {"message": "Specialist thinking..."})
    try:
        response = bound_llm.invoke(messages)
    finally:
        _emit(on_event, "working_done", {})
    return response, tools_invoked, tool_results


def _last_sandbox_exec_result(
    tool_results: list[tuple[str, str]],
) -> str | None:
    last: str | None = None
    for _name, result in tool_results:
        if looks_like_exec_result(result):
            last = result
    return last


def _sandbox_exec_ran(tool_results: list[tuple[str, str]]) -> bool:
    return any(looks_like_exec_result(result) for _name, result in tool_results)


def _sandbox_exec_failed(result: str) -> bool:
    text = (result or "").lower()
    if "error" in text and "exit" in text:
        return True
    if re.search(r'"exit_code"\s*:\s*(?!0\b)\d+', result or ""):
        return True
    return False


def _verbatim_code_specialist_output(tool_result: str) -> str:
    """Specialist payload that preserves exact sandbox stdout."""
    return (
        "### sandbox execution result (verbatim — source of truth)\n\n"
        f"{(tool_result or '').rstrip()}\n"
    )


def _extract_verbatim_code_blocks(text: str) -> list[str]:
    if not text:
        return []
    marked = re.findall(
        r"(### sandbox execution result \(verbatim[^\n]*\)\s*\n+.*?)(?=\n### |\Z)",
        text,
        flags=re.S,
    )
    if marked:
        return [m.strip() for m in marked if m.strip()]
    raw = re.findall(
        r"((?:stdout|exit_code).{0,400})",
        text,
        flags=re.S | re.I,
    )
    return [m.strip() for m in raw if m.strip()]


# ====================== PLANNER NODE ======================

def _clamp_code_plan(task: str, plan: list[str], specialists: list[str]) -> tuple[list[str], list[str]]:
    """Keep the normal planner flow, but collapse redundant code-only fan-out."""
    if not _requires_code_execution(task, task):
        return plan, specialists
    if len(specialists) <= 1 and len(plan) <= 1:
        return plan, specialists
    first = (plan[0] if plan else "").strip() or (
        "Use bound sandbox MCP tools only: create a sandbox, write/upload "
        "the user's Python, execute it, then report stdout/stderr exactly."
    )
    return [first], ["general"]


def planner_node(state: OverallState, llm: Any, on_event: EventCallback = None) -> dict:
    task = state["task"]
    critique_section = ""
    if state.get("critique") and state.get("iteration", 0) > 0:
        critique_section = f"\n\nPrevious critique to address:\n{state['critique']}"

    _emit(on_event, "planner_start", {"task": task})

    prompt = f"""You are a world-class planner.
Break down the following task into clear subtasks and decide which specialists should handle them.
Use only these specialist types: {sorted(VALID_SPECIALIST_TYPES)}.
The number of subtasks must match the number of specialists.

Routing hints:
- Profit, revenue, earnings, margins, growth % → finance + research (max 2 specialists)
- Product performance, growth drivers → research
- Regulations, compliance, legal risk → legal only when the task is about law or compliance
- Sports, match results, news, weather, current events, "last night", "today" → general ONLY (1 subtask, 1 specialist)
- Code execution, run/execute/write Python, compute/calculate with code, get program output/result → general ONLY (exactly 1 subtask, 1 specialist). The specialist MUST use the bound sandbox MCP tools and report stdout; do not invent results.
- Simple factual questions → general ONLY (1 subtask) — do NOT split into multiple research agents
- Never use internal research/finance specialists for sports or unrelated current events
- Prefer finance + research together only for company financial questions
- Never invent 2–3 overlapping subtasks for the same code run
- There is no local interpreter and no code-execution history tool

Task: {task}{critique_section}"""

    structured_llm = llm.with_structured_output(PlannerOutput)
    _emit(on_event, "working_start", {"message": "Planner thinking..."})
    try:
        response: PlannerOutput = structured_llm.invoke([HumanMessage(content=prompt)])
    finally:
        _emit(on_event, "working_done", {})

    plan = list(response.plan or [])
    specialists = [_normalize_specialist(s) for s in (response.specialists_needed or [])]
    plan, specialists = _clamp_code_plan(task, plan, specialists)

    _emit(on_event, "planner_done", {
        "plan": plan,
        "specialists": specialists,
    })

    return {
        "plan": plan,
        "specialists_needed": specialists,
    }


# ====================== ROUTER NODE ======================

def router_node(state: OverallState):
    """Fan out to specialists in parallel using Send."""
    specialists = state.get("specialists_needed") or ["general"]
    plan = state.get("plan") or [state["task"]]
    pairs = _align_specialists_and_plan(specialists, plan, state["task"])
    query_id = state.get("query_id", 0)
    iteration = state.get("iteration", 0)
    task = state["task"]

    return [
        Send(
            "specialist_node",
            {
                "specialist_type": specialist_type,
                "subtask": subtask,
                "task": task,
                "query_id": query_id,
                "iteration": iteration,
            },
        )
        for specialist_type, subtask in pairs
    ]


# ====================== SPECIALIST NODE ======================

def _requires_code_execution(task: str, subtask: str) -> bool:
    blob = f"{task}\n{subtask}"
    return bool(_CODE_EXEC_REQUEST.search(blob))


def _bind_specialist_tools(
    config: dict,
    mcp_tools: list,
    *,
    needs_code: bool,
) -> tuple[Any, dict]:
    """Bind only the MCP-derived tools allowed for this specialist/task."""
    static = dict(config.get("static_tools") or {})

    if needs_code:
        # Code work: MCP sandbox tools only — no local interpreter, no bypass.
        allowed = filter_sandbox_mcp_tools(mcp_tools)
        tools = allowed
    else:
        tools = list(static.values()) + list(mcp_tools)

    tools_by_name = {t.name: t for t in tools}
    bound_llm = config["llm"].bind_tools(tools) if tools else config["llm"]
    return bound_llm, tools_by_name


def specialist_node(
    state: OverallState,
    specialist_config: dict,
    on_event: EventCallback = None,
) -> Dict:
    specialist_type = _normalize_specialist(state["specialist_type"])
    subtask = state["subtask"]
    task = state.get("task") or subtask
    iteration = state.get("iteration", 0)
    query_id = state.get("query_id", 0)

    _emit(on_event, "specialist_start", {
        "specialist": specialist_type,
        "subtask": subtask,
    })

    config = specialist_config.get(specialist_type, specialist_config["general"])
    needs_code = _requires_code_execution(task, subtask)

    human_parts = [
        f"User question: {task}",
        f"Your subtask: {subtask}",
        "Use your tools when they are required to answer the subtask. "
        "After retrieving context, answer from tool results — do not invent facts.",
    ]
    if needs_code:
        human_parts.append(
            "REQUIRED: This request involves code or computation. "
            "All code execution must go through the bound sandbox MCP tools "
            "in this turn's inventory. Never assume a local interpreter. "
            "Omit warmpool and namespace; the sandbox MCP fills cluster "
            "placement. Call get_sandbox_config only if you need to inspect "
            "those values. "
            "Sandbox working directory is /app. Use relative paths. "
            "Follow the bound tool schemas: create a sandbox if needed, "
            "write or upload the program, then run it. A successful write "
            "is not the program result — keep calling bound tools until "
            "one returns the program's stdout. Report only that output."
        )

    with StickyMCPSessions() as runtime:
        bound_llm, tools_by_name = _bind_specialist_tools(
            config, runtime.tools, needs_code=needs_code
        )
        has_sandbox_tools = bool(
            filter_sandbox_mcp_tools(list(tools_by_name.values()))
        )
        inventory = format_discovered_mcp_tools(list(tools_by_name.values()))
        system_prompt = (
            f"{current_date_instruction()}\n\n"
            f"{SPECIALIST_PROMPTS[specialist_type]}\n\n{inventory}"
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content="\n\n".join(human_parts)),
        ]

        response, tools_invoked, tool_results = _invoke_with_tools(
            bound_llm,
            tools_by_name,
            messages,
            on_event=on_event,
            stop_after_sandbox_exec=needs_code,
            runtime=runtime,
        )

        if needs_code and has_sandbox_tools and not _sandbox_exec_ran(tool_results):
            messages.append(response)
            messages.append(
                HumanMessage(
                    content=(
                        "You answered without running the program through the bound "
                        "sandbox MCP tools. Writing the file is not enough. Create a "
                        "sandbox if needed, write or upload the program, then run it "
                        "and answer only from that stdout. There is no local interpreter."
                    )
                )
            )
            response, tools_invoked, tool_results = _invoke_with_tools(
                bound_llm,
                tools_by_name,
                messages,
                on_event=on_event,
                tools_invoked=tools_invoked,
                tool_results=tool_results,
                stop_after_sandbox_exec=True,
                runtime=runtime,
            )

    output = response.content if hasattr(response, "content") else str(response)
    if needs_code:
        last_exec = _last_sandbox_exec_result(tool_results)
        if last_exec:
            output = _verbatim_code_specialist_output(last_exec)

    _emit(on_event, "specialist_done", {
        "specialist": specialist_type,
        "tools": tools_invoked,
    })

    return {
        "specialist_results": [{
            "specialist": specialist_type,
            "subtask": subtask,
            "output": output,
            "tools_used": tools_invoked,
            "iteration": iteration,
            "query_id": query_id,
        }]
    }


# ====================== AGGREGATOR NODE ======================

def aggregator_node(state: OverallState, on_event: EventCallback = None) -> Dict:
    """Combine results from the current query's specialists."""
    current_iteration = state.get("iteration", 0)
    current_query_id = state.get("query_id", 0)
    results = [
        r for r in state.get("specialist_results", [])
        if r.get("iteration") == current_iteration
        and r.get("query_id", 0) == current_query_id
    ]

    sections = []
    for r in results:
        tools = ", ".join(r.get("tools_used", [])) or "none"
        sections.append(
            f"### {r['specialist'].upper()}\n"
            f"**Subtask:** {r['subtask']}\n"
            f"**Tools:** {tools}\n\n"
            f"{r['output']}"
        )

    _emit(on_event, "aggregator_done", {"specialists": len(results)})

    return {"combined_results": "\n\n".join(sections)}


# ====================== SYNTHESIZER NODE ======================

def _has_sandbox_evidence(*texts: str) -> bool:
    blob = "\n".join(t or "" for t in texts)
    if "### sandbox execution result" in blob:
        return True
    if looks_like_exec_result(blob):
        return True
    return False


def synthesizer_node(state: OverallState, llm: Any, on_event: EventCallback = None) -> Dict:
    """Synthesize specialist outputs into a single draft answer."""
    _emit(on_event, "synthesizer_start", {})

    combined = state.get("combined_results", "").strip()
    task = state.get("task") or ""
    if not combined:
        _emit(on_event, "synthesizer_done", {})
        return {
            "final_answer": (
                "Unable to produce an answer: no specialist results were collected. "
                "Please try again."
            )
        }

    if _requires_code_execution(task, task):
        blocks = _extract_verbatim_code_blocks(combined)
        if blocks:
            final = (
                "Sandbox execution output (verbatim from MCP):\n\n"
                f"{blocks[-1]}\n"
            )
            _emit(on_event, "synthesizer_done", {})
            return {"final_answer": final}

    prompt = f"""You are a skilled writer. Synthesize the following specialist outputs into one clear, cohesive answer.

Original Task: {task}

Specialist Outputs:
{combined}

Rules:
- Use ONLY facts present in the specialist outputs above. Do not add information from your own knowledge.
- For company metrics, prefer internal document figures. For sports/news/current events, use web results only.
- Preserve exact scores, dates, percentages, and dollar amounts — do not round or omit them.
- If specialist outputs conflict, state the conflict rather than picking arbitrarily.
- If specialists used sandbox MCP execution: quote the concrete stdout lines
  and exit code. Do not invent, soften, or omit program output. Runtime errors are
  valid sandbox results — report them as-is."""

    _emit(on_event, "working_start", {"message": "Synthesizer writing..."})
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
    finally:
        _emit(on_event, "working_done", {})

    _emit(on_event, "synthesizer_done", {})

    return {"final_answer": response.content}


# ====================== CRITIC NODE ======================

class CriticOutput(BaseModel):
    needs_improvement: bool = Field(description="Whether the output needs improvement")
    critique: str = Field(description="Detailed feedback on quality and completeness")


def critic_node(state: OverallState, llm: Any, on_event: EventCallback = None) -> Dict:
    task = state["task"]
    final_answer = state.get("final_answer", "") or ""
    combined = state.get("combined_results", "") or ""
    code_required = bool(_CODE_EXEC_REQUEST.search(task or ""))

    code_rule = ""
    if code_required:
        code_rule = (
            "\nThe task requires real code execution via sandbox MCP tools.\n"
            "- Set needs_improvement=true if the draft has no sandbox "
            "execution result (no stdout / exit_code evidence) and invents "
            "numbers or admits it did not run code.\n"
            "- If the draft already includes concrete sandbox stdout or an "
            "execution tool result, set needs_improvement=false.\n"
            "- Do NOT reject for style when the actual tool output is present.\n"
            "- Do NOT request a local interpreter — none exists.\n"
        )

    prompt = f"""You are a quality reviewer.

{current_date_instruction()}
When the task is about current events, recency, or "today", judge dates
against that calendar date — not a training cutoff.

Task: {task}

Draft Answer:
{final_answer}

Evaluate if this answer is complete, accurate, and high quality.
The answer must be grounded in the specialist outputs — reject answers that appear invented.
If the task asks for a specific figure and the draft includes that figure, set
needs_improvement to false unless there is a clear factual error or the answer
admits it could not find the information.
Prefer needs_improvement=false when the draft already answers the task with tool-grounded facts.
Do not flag a correctly dated current-events answer as wrong because the year
is after your training data.
{code_rule}"""

    structured_llm = llm.with_structured_output(CriticOutput)
    _emit(on_event, "working_start", {"message": "Critic reviewing..."})
    try:
        response: CriticOutput = structured_llm.invoke([HumanMessage(content=prompt)])
    finally:
        _emit(on_event, "working_done", {})

    needs_improvement = bool(response.needs_improvement)
    critique = response.critique

    if code_required and not _has_sandbox_evidence(final_answer, combined):
        needs_improvement = True
        critique = (
            f"{critique}\n\n"
            "[guard] Code was claimed or required but no sandbox MCP "
            "execution result appears in the tool trace. Rejecting bypass."
        )
    elif (
        needs_improvement
        and code_required
        and _has_sandbox_evidence(final_answer, combined)
    ):
        needs_improvement = False
        critique = (
            f"{critique}\n\n"
            "[override] Sandbox MCP execution evidence already present "
            "— accepting draft without replan."
        )

    _emit(on_event, "critic_done", {
        "needs_improvement": needs_improvement,
        "critique": critique,
    })

    return {
        "critique": critique,
        "needs_improvement": needs_improvement,
        "iteration": state.get("iteration", 0) + 1,
    }
