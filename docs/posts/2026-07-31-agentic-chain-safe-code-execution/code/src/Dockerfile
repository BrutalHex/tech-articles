# Multi-agent Chainlit UI + CLI tooling for agentic-chain POC.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Keep flat modules (graph.py, config.py, …) importable when Chainlit
    # changes the process cwd away from WORKDIR.
    PYTHONPATH=/app \
    CHAINLIT_HOST=0.0.0.0 \
    CHAINLIT_PORT=8000

WORKDIR /app

# Minimal OS deps for psycopg / healthchecks
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

# Non-root runtime
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Serves the Chainlit UI. Init containers override command to run seed_chroma.py.
CMD ["chainlit", "run", "chainlit_app.py", "--host", "0.0.0.0", "--port", "8000"]
