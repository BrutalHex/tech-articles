from functools import partial
from typing import Any, Literal

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import GraphConfig
from nodes import (
    aggregator_node,
    critic_node,
    planner_node,
    router_node,
    specialist_node,
    synthesizer_node,
)
from specialist_config import build_specialist_config
from state import OverallState

_setup_done = False


def should_continue(state: OverallState) -> Literal["planner", "__end__"]:
    """Loop back to planner for improvement, or finish with the synthesized answer."""
    if state.get("needs_improvement") and state.get("iteration", 0) < 3:
        return "planner"
    return END


def build_graph(config: GraphConfig) -> tuple[Any, ConnectionPool]:
    global _setup_done

    specialist_config = build_specialist_config(
        config.llm,
        config.embedding_function,
        config.chroma_host,
        config.chroma_port,
    )

    builder = StateGraph(OverallState)

    builder.add_node(
        "planner",
        partial(planner_node, llm=config.llm, on_event=config.on_event),
    )
    builder.add_node(
        "specialist_node",
        partial(
            specialist_node,
            specialist_config=specialist_config,
            on_event=config.on_event,
        ),
    )
    builder.add_node(
        "aggregator",
        partial(aggregator_node, on_event=config.on_event),
    )
    builder.add_node(
        "synthesizer",
        partial(synthesizer_node, llm=config.llm, on_event=config.on_event),
    )
    builder.add_node(
        "critic",
        partial(critic_node, llm=config.llm, on_event=config.on_event),
    )

    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", router_node, ["specialist_node"])
    builder.add_edge("specialist_node", "aggregator")
    builder.add_edge("aggregator", "synthesizer")
    builder.add_edge("synthesizer", "critic")
    builder.add_conditional_edges(
        "critic",
        should_continue,
        {
            "planner": "planner",
            END: END,
        },
    )

    pool = ConnectionPool(
        conninfo=config.db_connection,
        max_size=10,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    )
    checkpointer = PostgresSaver(pool)
    if not _setup_done:
        checkpointer.setup()
        _setup_done = True

    return builder.compile(checkpointer=checkpointer), pool