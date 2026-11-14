"""How the agent loop runs tools: over MCP in the app, or directly in tests and the terminal CLI.

Both runners have the same two methods, so the agent loop doesn't care which one it has:
- definitions(): the tool list in the Claude Messages API format;
- call(name, input, advisor_id=..., today=..., focus_client_id=...): run one tool, return a JSON-safe dict.

McpToolRunner signs a fresh internal token for every call (advisor, selected client, today; 2 minutes),
sends it to the server as a Bearer token over loopback HTTP, and returns the tool's structured result.
The agent loop is synchronous (it runs in FastAPI's thread pool), so each call runs the async MCP client
in its own short event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import lru_cache
from typing import Any, Protocol

import httpx2
import psycopg
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from wealth.config import get_settings
from wealth.mcp.internal_token import sign
from wealth.tools.registry import canonical_schema, execute_tool, tool_definitions

log = logging.getLogger(__name__)
TIMEOUT_SECONDS = 30


class ToolRunner(Protocol):
    def definitions(self) -> list[dict]: ...

    def call(
        self, name: str, raw_input: Any, *, advisor_id: int, today: date, focus_client_id: int | None = None
    ) -> dict: ...


class LocalToolRunner:
    """Runs tools in-process on a given connection. Used by tests (rolled-back connection) and the CLI."""

    def __init__(self, conn: psycopg.Connection | None = None):
        self.conn = conn

    def definitions(self) -> list[dict]:
        return tool_definitions()

    def call(self, name, raw_input, *, advisor_id, today, focus_client_id=None) -> dict:
        return execute_tool(
            name,
            raw_input,
            advisor_id=advisor_id,
            today=today,
            conn=self.conn,
            focus_client_id=focus_client_id,
        )


class McpToolRunner:
    """Runs tools on one of our MCP servers ("portfolio" by default) over loopback HTTP."""

    def __init__(self, server: str = "portfolio", base_url: str | None = None):
        self.server = server
        self.url = f"{(base_url or get_settings().mcp_base_url).rstrip('/')}/mcp/{server}/"

    def definitions(self) -> list[dict]:
        return list(_definitions(self.url, self.server))

    def call(self, name, raw_input, *, advisor_id, today, focus_client_id=None) -> dict:
        token = sign(self.server, advisor_id=advisor_id, today=today, focus_client_id=focus_client_id)
        try:
            return _run(_call(self.url, token, name, raw_input if raw_input is not None else {}))
        except Exception:
            log.exception("MCP call %s on %s failed", name, self.server)
            return {"error": "tool service unavailable"}


@lru_cache(maxsize=8)
def _definitions(url: str, server: str) -> tuple[dict, ...]:
    """The tool list, fetched once per process (it only changes with a release). Order is kept as served,
    so the tool definitions sent to Claude are byte-identical on every request (prompt cache)."""
    token = sign(server, advisor_id=None, today=date.today())
    return tuple(_run(_list(url, token)))


async def _session_client(url: str, token: str) -> tuple[httpx2.AsyncClient, Client]:
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT_SECONDS)
    return http, Client(streamable_http_client(url, http_client=http), read_timeout_seconds=TIMEOUT_SECONDS)


async def _list(url: str, token: str) -> list[dict]:
    http, client = await _session_client(url, token)
    async with http, client:
        result = await client.list_tools()
    return [
        {"name": t.name, "description": t.description, "input_schema": canonical_schema(t.input_schema)}
        for t in result.tools
    ]


async def _call(url: str, token: str, name: str, arguments: Any) -> dict:
    if not isinstance(arguments, dict):
        return {"error": "invalid input", "details": ["input: must be an object"]}
    http, client = await _session_client(url, token)
    async with http, client:
        result = await client.call_tool(name, arguments)
    if isinstance(result.structured_content, dict):
        return result.structured_content
    text = "".join(getattr(b, "text", "") for b in result.content)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    except ValueError:
        return {"error": text or "tool failed"} if result.is_error else {"result": text}


def _run(coro):
    """Run a coroutine from synchronous code, even if this thread already has a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
