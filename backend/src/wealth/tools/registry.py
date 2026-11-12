"""Tool registry and the single entry point for running a tool.

`execute_tool` is the security boundary between the model and the database:
1. the model's input is validated against the tool's pydantic model (unknown fields, including
   advisor_id, are rejected);
2. advisor_id is taken from the caller's session argument, never from the input;
3. the tool runs in a read-only transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from pydantic import BaseModel, ValidationError

from wealth.access import ToolContext, Viewer
from wealth.db import read_only
from wealth.tools.accounts import get_accounts
from wealth.tools.clients import find_reviews_due, get_my_clients
from wealth.tools.holdings import get_holdings
from wealth.tools.performance import get_performance
from wealth.tools.schemas import (
    ClientInput,
    HoldingsInput,
    NoInput,
    PerformanceInput,
    ReviewsInput,
    TransactionsInput,
)
from wealth.tools.transactions import get_transactions

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    fn: Callable[[ToolContext, Any], dict]


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "get_my_clients",
            "List every client you share at least one account with, with risk profile, next review date, and "
            "the count and market value of the accounts you can access.",
            NoInput,
            get_my_clients,
        ),
        Tool(
            "get_accounts",
            "List one client's accounts that you can access, with market value and the client's role.",
            ClientInput,
            get_accounts,
        ),
        Tool(
            "get_holdings",
            "Holdings for one account (account_id) or all of a client's accessible accounts (client_id), "
            "combined by symbol, with weight_pct, unrealized gain, and sector and asset-class summaries "
            "(use sector_summary to judge sector concentration, e.g. Technology).",
            HoldingsInput,
            get_holdings,
        ),
        Tool(
            "get_transactions",
            "Transactions in a date range for one account or a client's accessible accounts, newest first "
            "(max 200 rows), with totals by type including realized gain on sells.",
            TransactionsInput,
            get_transactions,
        ),
        Tool(
            "get_performance",
            "Returns (1D, 1M, 3M, 6M, YTD, 1Y, 2Y, 3Y, 5Y) in percent for one account or a client's accessible "
            "accounts, per account and combined (market-value weighted).",
            PerformanceInput,
            get_performance,
        ),
        Tool(
            "find_reviews_due",
            "Clients you can access whose next review is due within the given number of days from today "
            "(overdue reviews are included and flagged).",
            ReviewsInput,
            find_reviews_due,
        ),
    ]
}


def _input_schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    schema.setdefault("properties", {})
    return schema


def tool_definitions() -> list[dict]:
    """Tool list in the format the Claude Messages API expects."""
    return [
        {"name": t.name, "description": t.description, "input_schema": _input_schema(t.input_model)}
        for t in TOOLS.values()
    ]


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def execute_tool(
    name: str,
    raw_input: Any,
    *,
    advisor_id: int,
    today: date,
    conn: psycopg.Connection | None = None,
    focus_client_id: int | None = None,
) -> dict:
    """Validate and run one tool for the session's advisor. Always returns a JSON-safe dict."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool {name!r}"}
    try:
        params = tool.input_model.model_validate(raw_input if raw_input is not None else {})
    except ValidationError as exc:
        details = [f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}" for e in exc.errors()]
        return {"error": "invalid input", "details": details}

    # Hard scope: with a client selected, a lookup that names any other client is refused outright.
    asked_client = getattr(params, "client_id", None)
    if focus_client_id is not None and asked_client is not None and asked_client != focus_client_id:
        return {
            "error": "outside selected client",
            "detail": f"The advisor has selected client {focus_client_id}; only that client's data is available. "
            "Tell the advisor to choose 'All your clients' to ask about anyone else.",
        }

    def ctx(c: psycopg.Connection) -> ToolContext:
        viewer = Viewer("advisor", advisor_id)
        return ToolContext(conn=c, viewer=viewer, today=today, focus_client_id=focus_client_id)

    try:
        if conn is not None:
            result = tool.fn(ctx(conn), params)
        else:
            with read_only() as c:
                result = tool.fn(ctx(c), params)
    except Exception:
        log.exception("tool %s failed", name)
        return {"error": "tool failed"}
    return to_jsonable(result)
