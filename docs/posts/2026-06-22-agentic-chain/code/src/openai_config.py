import socket

import httpx
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from env_setup import OPENAI_API_BASE, OPENAI_API_KEY

OPENAI_CHAT_MODEL = "gpt-4o-mini"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"

_HTTP_CLIENT = httpx.Client(
    timeout=httpx.Timeout(60.0, connect=30.0),
    transport=httpx.HTTPTransport(retries=3),
)


def _api_key() -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to code/.env or export it in your shell."
        )
    return OPENAI_API_KEY


def verify_openai_connectivity() -> None:
    """Check DNS with retries — WSL DNS can be briefly unavailable."""
    import time

    last_error: Exception | None = None
    for attempt in range(5):
        try:
            socket.getaddrinfo("api.openai.com", 443)
            return
        except socket.gaierror as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(
        "Cannot resolve api.openai.com after several retries (DNS/network error). "
        "In WSL, check /etc/resolv.conf or run: wsl --shutdown, then reopen WSL."
    ) from last_error


def create_chat_llm(**kwargs) -> ChatOpenAI:
    return ChatOpenAI(
        api_key=_api_key(),
        base_url=OPENAI_API_BASE,
        http_client=_HTTP_CLIENT,
        model=OPENAI_CHAT_MODEL,
        temperature=0.2,
        max_retries=3,
        **kwargs,
    )


def create_embeddings(**kwargs) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=OPENAI_EMBEDDING_MODEL,
        api_key=_api_key(),
        base_url=OPENAI_API_BASE,
        max_retries=3,
        http_client=_HTTP_CLIENT,
        **kwargs,
    )