from typing import Annotated, Dict, List, TypedDict
import operator


class OverallState(TypedDict):
    # Main task from the user
    task: str

    # Incremented each user query so prior specialist results are ignored
    query_id: int

    # Plan created by the planner node
    plan: List[str]
    specialists_needed: List[str]

    # Per-specialist routing (injected via Send into parallel branches)
    specialist_type: str
    subtask: str

    # Results from parallel specialists (merged across branches via reducer)
    specialist_results: Annotated[List[Dict], operator.add]
    combined_results: str

    # Reflection / critique
    critique: str
    needs_improvement: bool
    iteration: int

    # Final output
    final_answer: str