# Official mcp-server-fetch (@modelcontextprotocol/server-fetch) wrapped for
# streamable-HTTP + kubelet probes.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    IGNORE_ROBOTS_TXT=true

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY health_wrapper.py http_app.py /app/
RUN chown appuser:appuser /app/health_wrapper.py /app/http_app.py /app/requirements.txt

USER appuser
EXPOSE 8000
CMD ["uvicorn", "health_wrapper:app", "--host", "0.0.0.0", "--port", "8000"]
