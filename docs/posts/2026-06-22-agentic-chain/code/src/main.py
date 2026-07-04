import env_setup  # noqa: F401 — must run before langchain/langgraph imports

from typing import Callable, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from config import GraphConfig, graph_session
from env_setup import CHECKPOINTS_DB_URI, CHROMA_HOST, CHROMA_PORT
from openai_config import create_chat_llm, create_embeddings, verify_openai_connectivity

app = typer.Typer(
    name="agent-workflow",
    help="🚀 Professional Multi-Agent Workflow Tool (LangGraph + GPT)",
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()
EXIT_COMMANDS = {"quit", "exit", "q"}


class ProgressDisplay:
    """Rich CLI progress: dotted spinner while work is in flight."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self._depth = 0
        self._ctx = None
        self._status = None

    def _start_spinner(self, message: str) -> None:
        self._depth += 1
        if self._depth == 1:
            self._ctx = self.console.status(
                f"[bold yellow]{message}[/bold yellow]",
                spinner="dots",
            )
            self._status = self._ctx.__enter__()
        elif self._status is not None:
            self._status.update(f"[bold yellow]{message}[/bold yellow]")

    def _stop_spinner(self) -> None:
        self._depth = max(0, self._depth - 1)
        if self._depth == 0 and self._ctx is not None:
            self._ctx.__exit__(None, None, None)
            self._ctx = None
            self._status = None

    def __call__(self, event: str, payload: dict) -> None:
        if event == "working_start":
            self._start_spinner(payload.get("message", "Working..."))
        elif event == "working_done":
            self._stop_spinner()
        elif event == "planner_start":
            console.print(Rule("[bold blue]Planner[/bold blue]"))
            console.print(f"[dim]Task:[/dim] {payload['task']}")
        elif event == "planner_done":
            console.print("[green]✓[/green] Plan created")
            for i, (specialist, step) in enumerate(
                zip(payload["specialists"], payload["plan"], strict=False),
                start=1,
            ):
                console.print(f"  [cyan]{i}.[/cyan] [bold]{specialist}[/bold] → {step}")
        elif event == "specialist_start":
            console.print(
                f"\n[bold magenta]▶ {payload['specialist'].upper()}[/bold magenta] "
                f"[dim]({payload['subtask']})[/dim]"
            )
        elif event == "tool_call":
            source = payload.get("source", "agent")
            source_labels = {
                "internal docs": "internal docs",
                "web": "web",
                "agent": "agent",
            }
            source_label = source_labels.get(source, source)
            args = payload.get("args", {})
            query = args.get("query") or args.get("code", "")
            console.print(
                f"  [yellow]⚙ {payload['tool']}[/yellow] "
                f"[dim]({source_label})[/dim]"
                + (f" query={query!r}" if query else "")
            )
            if payload.get("preview"):
                console.print(f"    [dim]{payload['preview']}[/dim]")
        elif event == "specialist_done":
            tools = ", ".join(payload.get("tools", [])) or "none"
            console.print(f"  [green]✓[/green] Done — tools used: {tools}")
        elif event == "aggregator_done":
            console.print(Rule("[bold blue]Aggregator[/bold blue]"))
            console.print(
                f"[green]✓[/green] Combined {payload.get('specialists', 0)} specialist result(s)"
            )
        elif event == "synthesizer_start":
            console.print(Rule("[bold blue]Synthesizer[/bold blue]"))
        elif event == "synthesizer_done":
            console.print("[green]✓[/green] Draft answer written")
        elif event == "critic_done":
            console.print(Rule("[bold blue]Critic[/bold blue]"))
            if payload.get("needs_improvement"):
                console.print("[yellow]↻[/yellow] Needs improvement — replanning")
                console.print(f"  [dim]{payload.get('critique', '')}[/dim]")
            else:
                console.print("[green]✓[/green] Quality check passed")


def _make_progress_handler() -> Callable[[str, dict], None]:
    return ProgressDisplay(console)


def _next_query_id(graph, invoke_config: dict) -> int:
    snapshot = graph.get_state(invoke_config)
    return snapshot.values.get("query_id", 0) + 1


def _run_task(graph, task: str, invoke_config: dict) -> dict:
    query_id = _next_query_id(graph, invoke_config)

    for update in graph.stream(
        {"task": task, "iteration": 0, "query_id": query_id},
        config=invoke_config,
        stream_mode="updates",
    ):
        for node_name, node_output in update.items():
            if node_name == "critic" and node_output.get("needs_improvement"):
                console.print(
                    f"[dim]  iteration {node_output.get('iteration', '?')} complete[/dim]"
                )

    snapshot = graph.get_state(invoke_config)
    return snapshot.values


def _print_result(result: dict) -> None:
    console.print("\n" + "=" * 60)
    console.print(Panel(
        result.get("final_answer", "[red]No final answer generated.[/red]"),
        title="[bold green]✅ FINAL ANSWER[/bold green]",
        border_style="green",
    ))

    if result.get("critique") and not result.get("needs_improvement"):
        console.print(Panel(
            result["critique"],
            title="[bold yellow]📝 Final Critique[/bold yellow]",
            border_style="yellow",
        ))


@app.command()
def run(
    task: Optional[str] = typer.Option(
        None,
        "--task",
        "-t",
        help="The task you want the agents to perform",
    ),
    thread_id: str = typer.Option(
        "default-session",
        "--thread",
        "-th",
        help="Unique session ID (for memory & checkpointing)",
    ),
):
    """Run the multi-agent workflow — stays open for follow-up tasks in the same session."""
    verify_openai_connectivity()

    graph_config = GraphConfig(
        db_connection=CHECKPOINTS_DB_URI,
        embedding_function=create_embeddings(),
        llm=create_chat_llm(),
        chroma_host=CHROMA_HOST,
        chroma_port=CHROMA_PORT,
        on_event=_make_progress_handler(),
    )

    invoke_config = {"configurable": {"thread_id": thread_id}}

    console.print(Panel.fit(
        f"[bold]Session:[/bold] {thread_id}\n"
        "[dim]Type a task and press Enter. "
        "Type [bold]quit[/bold] to exit.[/dim]",
        title="[bold green]🚀 Multi-Agent Workflow[/bold green]",
        border_style="green",
    ))

    with graph_session(graph_config) as graph:
        first = True
        while True:
            if first and task:
                current_task = task
                first = False
            else:
                current_task = console.input("\n[bold cyan]Task>[/bold cyan] ").strip()

            if not current_task:
                continue
            if current_task.lower() in EXIT_COMMANDS:
                console.print("[dim]Goodbye.[/dim]")
                break

            console.print(Panel.fit(
                f"[bold cyan]Task:[/bold cyan] {current_task}",
                title="[bold green]🚀 Running[/bold green]",
                border_style="green",
            ))

            try:
                result = _run_task(graph, current_task, invoke_config)
                _print_result(result)
            except Exception as exc:
                console.print(f"[bold red]Error:[/bold red] {exc}")


if __name__ == "__main__":
    app()