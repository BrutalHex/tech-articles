"""Smoke tests for the finance_search RAG tool (requires Chroma + OpenAI)."""

import pytest

pytestmark = pytest.mark.integration


def test_finance_search_returns_ai_product_revenue(finance_search_tool):
    result = finance_search_tool.invoke({"query": "AI product revenue Q2 2025"})
    assert isinstance(result, str)
    assert len(result.strip()) > 0
    assert "62" in result
    assert "revenue" in result.lower()


def test_finance_search_returns_net_profit(finance_search_tool):
    result = finance_search_tool.invoke({"query": "Q2 2025 net profit"})
    assert isinstance(result, str)
    assert "48" in result or "profit" in result.lower()


def test_finance_search_returns_operating_margins(finance_search_tool):
    result = finance_search_tool.invoke({"query": "operating margins Q2 2025"})
    assert isinstance(result, str)
    assert "31" in result or "margin" in result.lower()