from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


@dataclass
class GraphConfig:
    db_connection: str
    embedding_function: Any
    llm: Any
    chroma_host: str
    chroma_port: int
    on_event: Callable[[str, dict], None] | None = field(default=None)


@contextmanager
def graph_session(config: GraphConfig) -> Iterator[Any]:
    """Build a compiled graph and close its connection pool on exit."""
    from graph import build_graph

    graph, pool = build_graph(config)
    try:
        yield graph
    finally:
        pool.close()