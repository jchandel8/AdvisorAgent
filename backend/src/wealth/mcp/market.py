"""Market MCP server: the outside view for the AI Finalyst. News search (Tavily) and market moves.

Tools:
- search_news(query, time_range, max_results): recent news from the web, each item with title, source, URL,
  date and a short snippet. Results are cached for 6 hours (market_news_cache).
- sector_moves(sector, months): how a sector's securities moved in the demo price data.
- security_profile(symbol): what a security is, its latest price and its 1-year move in the demo data.

Prices come from the seeded database, so figures agree with the portals. Only news comes from outside.

Data egress guard: the only thing that ever leaves the app is a news query, and check_query() refuses any
query containing a person's full name from our database (clients, advisors, admins), an email address, or a
long digit run (account or phone numbers), before Tavily is called. Refusals are returned as tool errors,
so they appear in the admin portal's agent traces.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Annotated, Literal

import anyio
import httpx2
import psycopg
from mcp.server.mcpserver import MCPServer
from pydantic import Field

from wealth.config import get_settings
from wealth.db import connection
from wealth.mcp.guard import InternalOnly
from wealth.tools.registry import to_jsonable
from wealth.tools.schemas import Sector

log = logging.getLogger(__name__)

NAME = "advisoragent-market"
TAVILY_URL = "https://api.tavily.com/search"
CACHE_HOURS = 6
NAMES_TTL_SECONDS = 600
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LONG_DIGITS = re.compile(r"\d{6,}")

_test_conn: psycopg.Connection | None = None
_names: tuple[float, frozenset[str]] = (0.0, frozenset())


def use_connection(conn: psycopg.Connection | None) -> None:
    """Tests point the server at their rolled-back connection."""
    global _test_conn, _names
    _test_conn = conn
    _names = (0.0, frozenset())


@contextmanager
def _conn() -> Iterator[psycopg.Connection]:
    if _test_conn is not None:
        yield _test_conn
        return
    with connection() as c, c.transaction():
        yield c


# --- the egress guard ------------------------------------------------------------------------------------


def _people() -> frozenset[str]:
    global _names
    loaded_at, names = _names
    if time.monotonic() - loaded_at > NAMES_TTL_SECONDS or not names:
        with _conn() as c:
            rows = c.execute(
                """SELECT lower(first_name || ' ' || last_name) AS n FROM clients
                   UNION SELECT lower(first_name || ' ' || last_name) FROM advisors
                   UNION SELECT lower(first_name || ' ' || last_name) FROM admins"""
            ).fetchall()
        names = frozenset(r["n"] if isinstance(r, dict) else r[0] for r in rows)
        _names = (time.monotonic(), names)
    return names


def check_query(query: str) -> str | None:
    """Why a query may not leave the app, or None if it may."""
    if _EMAIL.search(query):
        return "it contains an email address"
    if _LONG_DIGITS.search(query):
        return "it contains a long number (an account or phone number?)"
    words = " ".join(re.findall(r"[a-z']+", query.lower()))
    for name in _people():
        if re.search(rf"\b{re.escape(name)}\b", words):
            return "it contains the name of a person in our database"
    return None


# --- news ------------------------------------------------------------------------------------------------


async def _tavily(query: str, time_range: str, max_results: int) -> dict:
    key = get_settings().tavily_api_key
    async with httpx2.AsyncClient(timeout=20) as http:
        response = await http.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "query": query,
                "topic": "news",
                "time_range": time_range,
                "max_results": max_results,
                "search_depth": "basic",  # 1 credit per search
                "include_answer": False,
                "include_raw_content": False,
            },
        )
    response.raise_for_status()
    return response.json()


def _cache_key(query: str, time_range: str, max_results: int) -> str:
    normalized = " ".join(query.lower().split())
    return hashlib.sha256(json.dumps([normalized, time_range, max_results]).encode()).hexdigest()


def _cached(key: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT response FROM market_news_cache WHERE key = %s AND fetched_at > now() - make_interval(hours => %s)",
            (key, CACHE_HOURS),
        ).fetchone()
    return (row["response"] if isinstance(row, dict) else row[0]) if row else None


def _store(key: str, query: str, response: dict) -> None:
    with _conn() as c:
        c.execute(
            "DELETE FROM market_news_cache WHERE fetched_at < now() - make_interval(hours => %s)",
            (CACHE_HOURS,),
        )
        c.execute(
            """INSERT INTO market_news_cache (key, query, response) VALUES (%s, %s, %s)
               ON CONFLICT (key) DO UPDATE SET response = EXCLUDED.response, fetched_at = now()""",
            (key, query, json.dumps(response)),
        )


def _source(url: str) -> str:
    host = re.sub(r"^https?://", "", url).split("/")[0]
    return host.removeprefix("www.")


async def search_news(query: str, time_range: str = "week", max_results: int = 5) -> dict:
    reason = await anyio.to_thread.run_sync(check_query, query)
    if reason:
        log.warning("market: refused a news query because %s", reason)
        return {
            "error": "query refused",
            "reason": f"The query was not sent because {reason}. "
            "Search only for companies, tickers, sectors or market topics.",
        }
    if not get_settings().tavily_api_key:
        return {"error": "news search isn't set up", "reason": "TAVILY_API_KEY is not configured."}
    key = _cache_key(query, time_range, max_results)
    cached = await anyio.to_thread.run_sync(_cached, key)
    if cached is not None:
        return {**cached, "from_cache": True}
    try:
        raw = await _tavily(query, time_range, max_results)
    except httpx2.HTTPStatusError as exc:
        log.warning("market: news search failed with HTTP %s", exc.response.status_code)
        return {
            "error": "news search failed",
            "reason": f"The news service answered {exc.response.status_code}.",
        }
    except httpx2.HTTPError as exc:
        log.warning("market: news search failed: %s", type(exc).__name__)
        return {"error": "news search failed", "reason": "The news service could not be reached."}
    result = {
        "query": query,
        "time_range": time_range,
        "results": [
            {
                "title": r.get("title"),
                "source": _source(r.get("url", "")),
                "url": r.get("url"),
                "published": r.get("published_date"),
                "snippet": (r.get("content") or "")[:500],
            }
            for r in raw.get("results", [])[:max_results]
        ],
    }
    await anyio.to_thread.run_sync(_store, key, query, result)
    return {**result, "from_cache": False}


# --- market data from the seeded prices --------------------------------------------------------------------

_PRICES_SQL = """
SELECT h.symbol, h.as_of_date, max(h.price) AS price
FROM holdings h JOIN securities s ON s.symbol = h.symbol
WHERE {where} AND h.as_of_date <= %(today)s
GROUP BY h.symbol, h.as_of_date"""


def _moves(where: str, params: dict, months: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(_PRICES_SQL.format(where=where), params).fetchall()
    by_symbol: dict[str, dict[date, float]] = {}
    for r in rows:
        by_symbol.setdefault(r["symbol"], {})[r["as_of_date"]] = float(r["price"])
    out = []
    for symbol, prices in sorted(by_symbol.items()):
        latest = max(prices)
        start_target = latest - timedelta(days=round(months * 30.44))
        earlier = [d for d in prices if d <= start_target]
        if not earlier:
            continue
        start = max(earlier)
        change = (prices[latest] / prices[start] - 1) * 100
        out.append(
            {
                "symbol": symbol,
                "from": start,
                "to": latest,
                "start_price": prices[start],
                "end_price": prices[latest],
                "change_pct": round(change, 2),
            }
        )
    return out


def sector_moves(sector: str, months: int = 3) -> dict:
    moves = _moves("s.sector = %(sector)s", {"sector": sector, "today": date.today()}, months)
    if not moves:
        return {"error": "no price data for that sector and period"}
    avg = sum(m["change_pct"] for m in moves) / len(moves)
    best = max(moves, key=lambda m: m["change_pct"])
    worst = min(moves, key=lambda m: m["change_pct"])
    return to_jsonable(
        {
            "sector": sector,
            "months": months,
            "average_change_pct": round(avg, 2),
            "securities": len(moves),
            "best": best,
            "worst": worst,
            "note": "Equal-weighted price change of the sector's securities in this app's price data (demo data).",
        }
    )


def security_profile(symbol: str) -> dict:
    with _conn() as c:
        row = c.execute(
            "SELECT symbol, description, sector, asset_class FROM securities WHERE symbol = %s",
            (symbol.upper(),),
        ).fetchone()
    if row is None:
        return {"error": "unknown symbol"}
    year = _moves("h.symbol = %(symbol)s", {"symbol": row["symbol"], "today": date.today()}, 12)
    return to_jsonable({**row, "one_year": year[0] if year else None})


# --- the server --------------------------------------------------------------------------------------------

server = MCPServer(
    NAME, version="1", instructions="Public market context. Never send client data in a query."
)


@server.tool(name="search_news")
async def _search_news(
    query: Annotated[str, Field(min_length=2, max_length=150)],
    time_range: Literal["day", "week", "month", "year"] = "week",
    max_results: Annotated[int, Field(ge=1, le=8)] = 5,
) -> dict:
    """Search recent news about companies, tickers, sectors or market topics. Never include client names,
    account numbers or other client data in the query: such queries are refused. Each result has a title,
    source, URL, date and snippet; cite the URL when you use a result."""
    return await search_news(query, time_range, max_results)


@server.tool(name="sector_moves")
def _sector_moves(sector: Sector, months: Literal[1, 3, 6, 12] = 3) -> dict:
    """How a sector's securities moved over the last 1, 3, 6 or 12 months in this app's price data: the
    average change and the best and worst security."""
    return sector_moves(sector, months)


@server.tool(name="security_profile")
def _security_profile(
    symbol: Annotated[str, Field(min_length=1, max_length=10, pattern=r"^[A-Za-z.\-]+$")],
) -> dict:
    """What a security is (description, sector, asset class), its latest price, and its 1-year price change in
    this app's price data."""
    return security_profile(symbol)


def asgi_app():
    inner = server.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True)
    return InternalOnly(inner, "market"), inner
