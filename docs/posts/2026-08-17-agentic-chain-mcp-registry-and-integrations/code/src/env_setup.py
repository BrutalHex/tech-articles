"""Load .env and configure service endpoints before other imports."""

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_FILE)

# Hardcoded OpenAI endpoint
OPENAI_API_BASE = "https://api.openai.com/v1"

# API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")

# Service endpoints
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
CHECKPOINTS_DB_URI = os.getenv(
    "CHECKPOINTS_DB_URI",
    "postgresql://langgraph:langgraph@localhost:5432/langgraph",
)

# LangSmith: keep endpoint from .env (EU or US); default to US if unset
_DEFAULT_LANGSMITH = "https://api.smith.langchain.com"
LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", _DEFAULT_LANGSMITH)
os.environ.setdefault("LANGSMITH_ENDPOINT", LANGSMITH_ENDPOINT)
os.environ.setdefault("LANGCHAIN_ENDPOINT", os.environ["LANGSMITH_ENDPOINT"])

# Tracing off unless ENABLE_LANGSMITH_TRACING=true — avoids DNS/403 breaking local runs
ENABLE_LANGSMITH_TRACING = os.getenv("ENABLE_LANGSMITH_TRACING", "").lower() in (
    "true",
    "1",
    "yes",
)
_tracing_enabled = ENABLE_LANGSMITH_TRACING and bool(LANGSMITH_API_KEY)
if _tracing_enabled:
    os.environ["LANGSMITH_TRACING"] = "true"
else:
    os.environ["LANGSMITH_TRACING"] = "false"
