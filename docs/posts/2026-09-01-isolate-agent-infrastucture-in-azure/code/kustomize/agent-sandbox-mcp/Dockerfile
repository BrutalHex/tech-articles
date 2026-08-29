# Thin wrap of the official agent-sandbox MCP image (built from
# clients/integrations/mcp-server/Dockerfile): kubelet probes plus
# schema-driven placement defaults.
FROM k8s-agent-sandbox-mcp-upstream:v0.5.4

USER root
COPY health_wrapper.py placement.py /app/
RUN chown appuser:appuser /app/health_wrapper.py /app/placement.py
USER appuser

ENTRYPOINT ["uvicorn", "health_wrapper:app", "--host", "0.0.0.0", "--port", "8000"]
