from typing import Any, Callable, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Send
from pydantic import BaseModel, Field

from specialists import MAX_TOOL_ROUNDS, SPECIALIST_PROMPTS, VALID_SPECIALIST_TYPES
from state import OverallState

EventCallback = Callable[[str, dict], None] | None


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
    _emit(on_event, "working_start", {"message": f"Running {tool_name}..."})
    try:
        result = str(tool.invoke(args))
    finally:
        _emit(on_event, "working_done", {})

    _emit(on_event, "tool_call", {
        "tool": tool_name,
        "args": args,
        "preview": _preview(result),
        "source": _tool_source(tool_name),
    })
    return result


def _invoke_with_tools(
    bound_llm: Any,
    tools_by_name: dict,
    messages: list,
    on_event: EventCallback = None,
    tools_invoked: list[str] | None = None,
) -> tuple[Any, list[str]]:
    if tools_invoked is None:
        tools_invoked = []

    for _round in range(MAX_TOOL_ROUNDS):
        _emit(on_event, "working_start", {"message": "Specialist thinking..."})
        try:
            response = bound_llm.invoke(messages)
        finally:
            _emit(on_event, "working_done", {})

        if not response.tool_calls:
            return response, tools_invoked

        messages.append(response)
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
            messages.append(
                ToolMessage(content=result, tool_call_id=tool_call_id)
            )

    # Agentic RAG safety: stop after MAX_TOOL_ROUNDS even if the model keeps calling tools.
    _emit(on_event, "working_start", {"message": "Specialist thinking..."})
    try:
        response = bound_llm.invoke(messages)
    finally:
        _emit(on_event, "working_done", {})
    return response, tools_invoked


# ====================== PLANNER NODE ======================

def planner_node(state: OverallState, llm: Any, on_event: EventCallback = None) -> dict:
    critique_section = ""
    if state.get("critique") and state.get("iteration", 0) > 0:
        critique_section = f"\n\nPrevious critique to address:\n{state['critique']}"

    _emit(on_event, "planner_start", {"task": state["task"]})

    prompt = f"""You are a world-class planner.
Break down the following task into clear subtasks and decide which specialists should handle them.
Use only these specialist types: {sorted(VALID_SPECIALIST_TYPES)}.
The number of subtasks must match the number of specialists.

Routing hints:
- Profit, revenue, earnings, margins, growth % → finance + research (max 2 specialists)
- Product performance, growth drivers → research
- Regulations, compliance, legal risk → legal only when the task is about law or compliance
- Sports, match results, news, weather, current events, "last night", "today" → general ONLY (1 subtask, 1 specialist)
- Simple factual questions → general ONLY (1 subtask) — do NOT split into multiple research agents
- Never use internal research/finance specialists for sports or unrelated current events
- Prefer finance + research together only for company financial questions

Task: {state['task']}{critique_section}"""

    structured_llm = llm.with_structured_output(PlannerOutput)
    _emit(on_event, "working_start", {"message": "Planner thinking..."})
    try:
        response: PlannerOutput = structured_llm.invoke([HumanMessage(content=prompt)])
    finally:
        _emit(on_event, "working_done", {})

    _emit(on_event, "planner_done", {
        "plan": response.plan,
        "specialists": response.specialists_needed,
    })

    return {
        "plan": response.plan,
        "specialists_needed": [_normalize_specialist(s) for s in response.specialists_needed],
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

    human_parts = [
        f"User question: {task}",
        f"Your subtask: {subtask}",
        "Use your tools only when needed to answer the subtask. "
        "After retrieving context, answer from tool results — do not invent facts.",
    ]

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(human_parts)),
    ]

    response, tools_invoked = _invoke_with_tools(
        config["llm"],
        config["tools"],
        messages,
        on_event=on_event,
    )

    _emit(on_event, "specialist_done", {
        "specialist": specialist_type,
        "tools": tools_invoked,
    })

    return {
        "specialist_results": [{
            "specialist": specialist_type,
            "subtask": subtask,
            "output": response.content,
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

def synthesizer_node(state: OverallState, llm: Any, on_event: EventCallback = None) -> Dict:
    """Synthesize specialist outputs into a single draft answer."""
    _emit(on_event, "synthesizer_start", {})

    combined = state.get("combined_results", "").strip()
    if not combined:
        _emit(on_event, "synthesizer_done", {})
        return {
            "final_answer": (
                "Unable to produce an answer: no specialist results were collected. "
                "Please try again."
            )
        }

    prompt = f"""You are a skilled writer. Synthesize the following specialist outputs into one clear, cohesive answer.

Original Task: {state['task']}

Specialist Outputs:
{combined}

Rules:
- Use ONLY facts present in the specialist outputs above. Do not add information from your own knowledge.
- For company metrics, prefer internal document figures. For sports/news/current events, use web results only.
- Preserve exact scores, dates, percentages, and dollar amounts — do not round or omit them.
- If specialist outputs conflict, state the conflict rather than picking arbitrarily."""

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
    prompt = f"""You are a quality reviewer.

Task: {state['task']}

Draft Answer:
{state.get('final_answer', '')}

Evaluate if this answer is complete, accurate, and high quality.
The answer must be grounded in the specialist outputs — reject answers that appear invented.
If the task asks for a specific figure and the draft includes that figure, set
needs_improvement to false unless there is a clear factual error or the answer
admits it could not find the information.
"""

    structured_llm = llm.with_structured_output(CriticOutput)
    _emit(on_event, "working_start", {"message": "Critic reviewing..."})
    try:
        response: CriticOutput = structured_llm.invoke([HumanMessage(content=prompt)])
    finally:
        _emit(on_event, "working_done", {})

    _emit(on_event, "critic_done", {
        "needs_improvement": response.needs_improvement,
        "critique": response.critique,
    })

    return {
        "critique": response.critique,
        "needs_improvement": response.needs_improvement,
        "iteration": state.get("iteration", 0) + 1,
    }