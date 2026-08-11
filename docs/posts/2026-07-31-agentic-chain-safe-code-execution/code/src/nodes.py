import re
from typing import Any, Callable, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Send
from pydantic import BaseModel, Field

from specialists import MAX_TOOL_ROUNDS, SPECIALIST_PROMPTS, VALID_SPECIALIST_TYPES
from state import OverallState

EventCallback = Callable[[str, dict], None] | None

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


def _tool_source(tool_name: str) -> str:
    if tool_name == "web_search":
        return "web"
    if tool_name.endswith("_search"):
        return "internal docs"
    return "agent"


def _run_tool(
    tool_name: str,
    tool: Any,
    args: dict,
    on_event: EventCallback,
) -> str:
    source = _tool_source(tool_name)
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
        result = str(tool.invoke(args))
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
    stop_after_code_interpreter: bool = False,
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
        saw_successful_code = False
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
            result = _run_tool(name, tool, args, on_event)
            tools_invoked.append(name)
            tool_results.append((name, result))
            messages.append(
                ToolMessage(content=result, tool_call_id=tool_call_id)
            )
            if (
                stop_after_code_interpreter
                and name == "code_interpreter"
                and "Error executing code" not in result
            ):
                saw_successful_code = True

        # Pure execute tasks: one successful sandbox run is enough — do not let
        # the model re-run, call history, or fan out extra tool rounds.
        if saw_successful_code:
            # Do not ask the model to rephrase stdout (it invents PIDs). Callers
            # pin the specialist output to the last code_interpreter payload.
            return response, tools_invoked, tool_results

    # Agentic RAG safety: stop after MAX_TOOL_ROUNDS even if the model keeps calling tools.
    _emit(on_event, "working_start", {"message": "Specialist thinking..."})
    try:
        response = bound_llm.invoke(messages)
    finally:
        _emit(on_event, "working_done", {})
    return response, tools_invoked, tool_results


def _last_tool_result(
    tool_results: list[tuple[str, str]],
    tool_name: str,
) -> str | None:
    last: str | None = None
    for name, result in tool_results:
        if name == tool_name:
            last = result
    return last


def _verbatim_code_specialist_output(tool_result: str) -> str:
    """Specialist payload that preserves exact sandbox stdout (matches .result.json)."""
    return (
        "### code_interpreter result (verbatim — source of truth; "
        "matches history/*.result.json stdout)\n\n"
        f"{(tool_result or '').rstrip()}\n"
    )


def _extract_verbatim_code_blocks(text: str) -> list[str]:
    """Pull pinned code_interpreter sections (or raw [agent-sandbox] blocks)."""
    if not text:
        return []
    marked = re.findall(
        r"(### code_interpreter result \(verbatim[^\n]*\)\s*\n+.*?)(?=\n### |\Z)",
        text,
        flags=re.S,
    )
    if marked:
        return [m.strip() for m in marked if m.strip()]
    # Fallback: header written by tools.code_interpreter
    raw = re.findall(
        r"(\[agent-sandbox[^\]]+\].*?)(?=\n\[agent-sandbox|\n### |\Z)",
        text,
        flags=re.S,
    )
    return [m.strip() for m in raw if m.strip()]


# ====================== PLANNER NODE ======================

def _clamp_code_plan(task: str, plan: list[str], specialists: list[str]) -> tuple[list[str], list[str]]:
    """Keep the normal planner flow, but collapse redundant code-only fan-out."""
    if not _requires_code_execution(task, task):
        return plan, specialists
    if len(specialists) <= 1 and len(plan) <= 1:
        return plan, specialists
    # One execute task must not become N parallel "general" subtasks.
    first = (plan[0] if plan else "").strip() or (
        "Call code_interpreter once with the user's Python and report the sandbox "
        "stdout/stderr exactly. Do not call code_execution_history unless asked."
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
- Code execution, run/execute/write Python, compute/calculate with code, code interpreter, get program output/result → general ONLY (exactly 1 subtask, 1 specialist). The specialist MUST call code_interpreter exactly once and report stdout; do not invent results; do NOT add a second subtask for history unless the user asked for history.
- Code execution history, sandbox history, "what code ran", audit interpreter scripts → general ONLY (1 subtask). The specialist MUST call code_execution_history; do not route to research/finance/legal.
- Simple factual questions → general ONLY (1 subtask) — do NOT split into multiple research agents
- Never use internal research/finance specialists for sports or unrelated current events
- Prefer finance + research together only for company financial questions
- Never invent 2–3 overlapping subtasks for the same code run (no "execute" + "run interpreter" + "check history")

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
    system_prompt = SPECIALIST_PROMPTS[specialist_type]
    tools_by_name = config["tools"]
    has_code_tool = "code_interpreter" in tools_by_name
    needs_code = has_code_tool and _requires_code_execution(task, subtask)

    human_parts = [
        f"User question: {task}",
        f"Your subtask: {subtask}",
        "Use your tools when they are required to answer the subtask. "
        "After retrieving context, answer from tool results — do not invent facts.",
    ]
    if needs_code:
        human_parts.append(
            "REQUIRED: This request involves code or computation. "
            "You MUST call the code_interpreter tool with Python code before answering. "
            "Do not provide an artificial/mental result. Report only the tool output."
        )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(human_parts)),
    ]

    response, tools_invoked, tool_results = _invoke_with_tools(
        config["llm"],
        tools_by_name,
        messages,
        on_event=on_event,
        stop_after_code_interpreter=needs_code,
    )

    # Hard guard: if the model answered without running code, force one more
    # tool-using pass so sandbox execution is not skipped.
    if needs_code and "code_interpreter" not in tools_invoked:
        messages.append(response)
        messages.append(
            HumanMessage(
                content=(
                    "You answered without calling code_interpreter. That is invalid "
                    "for this task. Call code_interpreter now with the Python code "
                    "needed to produce the real result, then answer only from its output. "
                    "Call it exactly once."
                )
            )
        )
        response, tools_invoked, tool_results = _invoke_with_tools(
            config["llm"],
            tools_by_name,
            messages,
            on_event=on_event,
            tools_invoked=tools_invoked,
            tool_results=tool_results,
            stop_after_code_interpreter=True,
        )

    # Pin code tasks to the real tool payload so the model cannot rewrite PIDs/stdout.
    output = response.content if hasattr(response, "content") else str(response)
    if needs_code:
        last_code = _last_tool_result(tool_results, "code_interpreter")
        if last_code:
            output = _verbatim_code_specialist_output(last_code)

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
    return ("[agent-sandbox" in blob) or (
        "history/" in blob and "sandbox=" in blob
    )


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

    # Code tasks: never let the synthesizer rewrite sandbox stdout (PIDs, hostnames).
    # Use the last pinned code_interpreter block — same bytes as .result.json.
    if _requires_code_execution(task, task):
        blocks = _extract_verbatim_code_blocks(combined)
        if blocks:
            final = (
                "Sandbox execution output (verbatim from `code_interpreter`; "
                "this is the same stdout stored in `history/*.result.json`):\n\n"
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
- If specialists used code_interpreter / agent-sandbox: quote the concrete stdout lines
  and any [agent-sandbox claim=... sandbox=... history=... result=...] header.
  Do not invent, soften, or omit program output. Runtime errors (e.g. missing
  /etc/hostname) are valid sandbox results — report them as-is."""

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
            "\nThe task requires real code execution.\n"
            "- Set needs_improvement=true ONLY if the draft has no real sandbox/"
            "code_interpreter results (no stdout, no [agent-sandbox] evidence) "
            "and invents numbers or admits it did not run code.\n"
            "- If the draft already includes concrete sandbox stdout (hostname, "
            "pid, printed values, or a runtime error from the sandbox), set "
            "needs_improvement=false.\n"
            "- Do NOT reject for style, missing prose, or 'should mention sandbox "
            "more clearly' when the actual tool output is present.\n"
            "- Do NOT request re-running code or fetching execution history when "
            "results are already present.\n"
        )

    prompt = f"""You are a quality reviewer.

Task: {task}

Draft Answer:
{final_answer}

Evaluate if this answer is complete, accurate, and high quality.
The answer must be grounded in the specialist outputs — reject answers that appear invented.
If the task asks for a specific figure and the draft includes that figure, set
needs_improvement to false unless there is a clear factual error or the answer
admits it could not find the information.
Prefer needs_improvement=false when the draft already answers the task with tool-grounded facts.
{code_rule}"""

    structured_llm = llm.with_structured_output(CriticOutput)
    _emit(on_event, "working_start", {"message": "Critic reviewing..."})
    try:
        response: CriticOutput = structured_llm.invoke([HumanMessage(content=prompt)])
    finally:
        _emit(on_event, "working_done", {})

    needs_improvement = bool(response.needs_improvement)
    critique = response.critique

    # Precision guard (workflow unchanged): do not replan successful sandbox runs
    # over stylistic critic noise.
    if (
        needs_improvement
        and code_required
        and _has_sandbox_evidence(final_answer, combined)
    ):
        needs_improvement = False
        critique = (
            f"{critique}\n\n"
            "[override] Sandbox/tool evidence already present — accepting draft "
            "without replan."
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