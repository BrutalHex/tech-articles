"""Shared fixtures for per-tool smoke tests."""

import sys
from pathlib import Path

import httpx
import pytest

SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import env_setup  # noqa: F401, E402
from env_setup import CHROMA_HOST, CHROMA_PORT, OPENAI_API_KEY


def _chroma_heartbeat_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/api/v2/heartbeat"


def chroma_is_available(host: str, port: int) -> bool:
    try:
        response = httpx.get(_chroma_heartbeat_url(host, port), timeout=3.0)
        return response.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def chroma_host() -> str:
    return CHROMA_HOST


@pytest.fixture(scope="session")
def chroma_port() -> int:
    return CHROMA_PORT


@pytest.fixture(scope="session")
def require_openai():
    if not OPENAI_API_KEY:
        pytest.skip("OPENAI_API_KEY is not set")

    from openai_config import verify_openai_connectivity

    try:
        verify_openai_connectivity()
    except Exception as exc:
        pytest.skip(f"OpenAI is not reachable: {exc}")


@pytest.fixture(scope="session")
def embeddings(require_openai):
    from openai_config import create_embeddings

    return create_embeddings()


@pytest.fixture(scope="session")
def require_chroma(chroma_host: str, chroma_port: int):
    if not chroma_is_available(chroma_host, chroma_port):
        pytest.skip(
            f"Chroma is not available at {chroma_host}:{chroma_port}. "
            "Start it with: docker compose up -d chroma"
        )
    return chroma_host, chroma_port


@pytest.fixture(scope="session")
def rag_tools(embeddings, require_chroma, chroma_host: str, chroma_port: int):
    from rag import build_rag_tools

    return build_rag_tools(embeddings, chroma_host, chroma_port)


@pytest.fixture
def research_search_tool(rag_tools):
    return rag_tools["research_search"]


@pytest.fixture
def finance_search_tool(rag_tools):
    return rag_tools["finance_search"]


@pytest.fixture
def legal_search_tool(rag_tools):
    return rag_tools["legal_search"]