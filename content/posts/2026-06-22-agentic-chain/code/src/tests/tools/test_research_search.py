"""Smoke tests for the research_search RAG tool (requires Chroma + OpenAI)."""

import pytest

pytestmark = pytest.mark.integration


def test_research_search_returns_revenue_growth(research_search_tool):
    result = research_search_tool.invoke({"query": "Q2 2025 revenue growth AI products"})
    assert isinstance(result, str)
    assert len(result.strip()) > 0
    assert "23" in result


def test_research_search_returns_growth_drivers(research_search_tool):
    result = research_search_tool.invoke({"query": "growth drivers for AI products"})
    assert isinstance(result, str)
    assert "enterprise" in result.lower() or "healthcare" in result.lower()
    assert "driver" in result.lower() or "adoption" in result.lower()