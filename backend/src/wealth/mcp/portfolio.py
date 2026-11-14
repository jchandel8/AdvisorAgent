"""Portfolio MCP server: the advisor's data tools, served over MCP.

It serves the existing tool registry (wealth/tools/registry.py) unchanged, so there is still exactly one
security boundary for data tools, `execute_tool`:
- the arguments are validated against the tool's pydantic model (unknown fields such as advisor_id are
  rejected);
- the advisor, the selected client and "today" come from the verified internal token (guard.py), never
  from the arguments;
- every query joins through the access layer, in a read-only transaction.

Built on the SDK's low-level Server (not the decorator API) so the JSON schemas the model sees are exactly
the registry's, byte for byte. That keeps the prompt cache stable and avoids a second definition of every
tool.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import mcp_types as types
import psycopg
from mcp.server.lowlevel import Server

from wealth.mcp.guard import InternalOnly
from wealth.mcp.internal_token import McpIdentity
from wealth.tools.registry import TOOLS, execute_tool, tool_definitions

NAME = "advisoragent-portfolio"
TOOL_LIST_TTL_MS = 60 * 60 * 1000  # the tool list only changes with a new release; clients may cache it

# Tools run synchronous psycopg code. They get their own small thread pool so a burst of agent requests
# (each waiting on its tool calls) can never use up the threads the tool calls themselves need.
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mcp-portfolio")

# Tests point the tools at their rolled-back test connection. Production leaves it None (pool connections).
_test_conn: psycopg.Connection | None = None


def use_connection(conn: psycopg.Connection | None) -> None:
    global _test_conn
    _test_conn = conn


def identity_of(ctx: Any) -> McpIdentity:
    """The identity guard.py verified for this HTTP request. Missing means the guard didn't run: refuse."""
    request = getattr(ctx, "request", None)
    state = getattr(request, "scope", {}).get("state", {}) if request is not None else {}
    identity = state.get("mcp_identity")
    if not isinstance(identity, McpIdentity) or identity.advisor_id is None:
        raise PermissionError("no verified advisor for this MCP request")
    return identity


async def list_tools(ctx, params) -> types.ListToolsResult:
    tools = [
        types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"])
        for t in tool_definitions()
    ]
    return types.ListToolsResult(tools=tools, ttl_ms=TOOL_LIST_TTL_MS)


async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    try:
        who = identity_of(ctx)
    except PermissionError:
        return _result({"error": "not authorized"})
    if params.name not in TOOLS:
        return _result({"error": f"unknown tool {params.name!r}"})

    def run() -> dict:
        return execute_tool(
            params.name,
            params.arguments or {},
            advisor_id=who.advisor_id,
            today=who.today,
            conn=_test_conn,
            focus_client_id=who.focus_client_id,
        )

    output = await asyncio.get_running_loop().run_in_executor(_executor, run)
    return _result(output)


def _result(output: dict) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(output))],
        structured_content=output,
        is_error="error" in output,
    )


server = Server(NAME, version="1", on_list_tools=list_tools, on_call_tool=call_tool)


def asgi_app():
    """The server as an ASGI app for app.mount("/mcp/portfolio", ...). Stateless: each call stands alone."""
    inner = server.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True)
    return InternalOnly(inner, "portfolio"), inner
