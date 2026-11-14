"""Market MCP server: the data egress guard, news search (with a fake Tavily) and its cache, market moves."""

from __future__ import annotations

from datetime import timedelta

import anyio
import httpx2
import pytest

from tests.fixtures import A1, LATEST, TODAY, X
from tests.test_mcp import base_url  # noqa: F401  (live server fixture)
from wealth.config import get_settings
from wealth.mcp import market
from wealth.mcp.client import McpToolRunner


@pytest.fixture(autouse=True)
def market_on_test_db(conn):
    market.use_connection(conn)
    conn.execute(
        "INSERT INTO clients (username, first_name, last_name, email, risk_profile, target_allocation,"
        " next_review_date) VALUES ('rwilson', 'Renee', 'Wilson', 'renee@example.com', 'moderate',"
        ' \'{"equity": 0.6, "fixed_income": 0.35, "cash": 0.05}\', %s)',
        (TODAY,),
    )
    yield
    market.use_connection(None)


@pytest.fixture
def tavily(monkeypatch):
    """A fake Tavily: records calls and returns two results."""
    calls = []

    async def fake(query, time_range, max_results):
        calls.append((query, time_range, max_results))
        return {
            "results": [
                {
                    "title": "Chipmakers rally",
                    "url": "https://www.example.com/a",
                    "content": "x" * 900,
                    "published_date": "Fri, 13 Nov 2026 10:00:00 GMT",
                },
                {"title": "Rates steady", "url": "https://news.example.org/b", "content": "Fed holds."},
            ]
        }

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    get_settings.cache_clear()
    monkeypatch.setattr(market, "_tavily", fake)
    return calls


def news(query, **kw):
    return anyio.run(lambda: market.search_news(query, **kw))


# --- the egress guard ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "Renee Wilson portfolio news",
        "news about renee   WILSON",
        "renee@example.com",
        "account 4401928833 transfer",
    ],
)
def test_queries_with_client_data_are_refused_and_never_sent(tavily, query):
    out = news(query)
    assert out["error"] == "query refused" and tavily == []


@pytest.mark.parametrize("query", ["NVDA earnings outlook", "Johnson & Johnson Q3 2026 results", "Fed rates"])
def test_market_queries_are_allowed(tavily, query):
    assert "error" not in news(query) and len(tavily) == 1


def test_a_last_name_alone_is_not_refused():
    # "Wilson" alone is common in company names; only full names of people in the database are refused.
    assert market.check_query("Wilson Sporting Goods earnings") is None


# --- news search -------------------------------------------------------------------------------------------


def test_results_are_shaped_and_cached_for_six_hours(tavily, conn):
    first = news("semiconductor stocks", time_range="month", max_results=2)
    assert first["from_cache"] is False and tavily == [("semiconductor stocks", "month", 2)]
    item = first["results"][0]
    assert item["source"] == "example.com" and len(item["snippet"]) == 500 and item["published"]
    again = news("  Semiconductor   STOCKS ", time_range="month", max_results=2)
    assert again["from_cache"] is True and len(tavily) == 1  # normalized query hits the cache
    conn.execute("UPDATE market_news_cache SET fetched_at = now() - interval '7 hours'")
    assert news("semiconductor stocks", time_range="month", max_results=2)["from_cache"] is False
    assert len(tavily) == 2


def test_news_search_is_off_without_a_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    assert news("bank stocks")["error"] == "news search isn't set up"


def test_news_service_errors_become_tool_errors(tavily, monkeypatch):
    async def failing(*args):
        request = httpx2.Request("POST", market.TAVILY_URL)
        raise httpx2.HTTPStatusError("429", request=request, response=httpx2.Response(429, request=request))

    monkeypatch.setattr(market, "_tavily", failing)
    out = news("bank stocks")
    assert out["error"] == "news search failed" and "429" in out["reason"]


# --- market moves from the seeded prices --------------------------------------------------------------------


def test_sector_moves_and_security_profile(conn):
    start = LATEST - timedelta(days=95)
    conn.execute(
        "INSERT INTO holdings (account_id, symbol, quantity, cost_basis, price, as_of_date) VALUES"
        " (%s, 'AAPL', 10, 1000, 160, %s), (%s, 'MSFT', 5, 1500, 500, %s)",
        (X, start, X, start),
    )
    out = market.sector_moves("Technology", 3)
    assert out["securities"] == 2 and out["average_change_pct"] == 2.5  # AAPL +25%, MSFT -20%
    assert out["best"]["symbol"] == "AAPL" and out["worst"]["symbol"] == "MSFT"
    assert market.sector_moves("Energy", 3)["error"]
    profile = market.security_profile("aapl")
    assert profile["sector"] == "Technology" and profile["one_year"] is None  # no price a year back
    assert market.security_profile("ZZZZ") == {"error": "unknown symbol"}


# --- over MCP ---------------------------------------------------------------------------------------------


def test_market_tools_over_mcp(base_url, tavily):  # noqa: F811
    runner = McpToolRunner("market", base_url=base_url)
    assert [t["name"] for t in runner.definitions()] == ["search_news", "sector_moves", "security_profile"]
    refused = runner.call("search_news", {"query": "Renee Wilson holdings"}, advisor_id=A1, today=TODAY)
    assert refused["error"] == "query refused" and tavily == []
    ok = runner.call("search_news", {"query": "chip stocks"}, advisor_id=A1, today=TODAY)
    assert ok["results"][0]["title"] == "Chipmakers rally"
    too_long = runner.call("search_news", {"query": "x" * 200}, advisor_id=A1, today=TODAY)
    assert "error" in too_long and len(tavily) == 1  # rejected by the schema, never sent
