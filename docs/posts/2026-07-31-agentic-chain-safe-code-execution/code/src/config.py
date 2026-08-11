from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any, Callable, Iterator

# Ensure flat app modules remain importable even if the process cwd moves
# (Chainlit does this at request time).
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))


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
