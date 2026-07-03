"""Smoke tests for the legal_search RAG tool (requires Chroma + OpenAI)."""

import pytest

pytestmark = pytest.mark.integration


def test_legal_search_returns_eu_ai_act(legal_search_tool):
    result = legal_search_tool.invoke({"query": "EU AI Act conformity assessments"})
    assert isinstance(result, str)
    assert len(result.strip()) > 0
    assert "EU AI Act" in result or "conformity" in result.lower()


def test_legal_search_returns_high_risk_requirements(legal_search_tool):
    result = legal_search_tool.invoke({"query": "high-risk AI systems requirements"})
    assert isinstance(result, str)
    assert "high-risk" in result.lower() or "AI" in result