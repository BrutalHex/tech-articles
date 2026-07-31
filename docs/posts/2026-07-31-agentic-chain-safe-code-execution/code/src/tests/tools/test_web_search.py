"""Smoke tests for the web_search tool (requires network)."""

import pytest

from tools import web_search

pytestmark = pytest.mark.integration


def test_web_search_returns_non_empty_results():
    result = web_search.invoke({"query": "Python programming language"})
    assert isinstance(result, str)
    assert len(result.strip()) > 20


def test_web_search_handles_specific_query():
    result = web_search.invoke({"query": "LangGraph multi-agent workflows"})
    assert isinstance(result, str)
    assert len(result.strip()) > 10