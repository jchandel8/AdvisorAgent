"""Client portal API. The client is always the signed-in user; there is no client_id parameter.

An optional account_id narrows a view to one account; it must be one of the client's own accounts,
otherwise the response is 404 (the same as an account that doesn't exist).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from wealth.access import ToolContext, scoped_account_ids
from wealth.api import queries
from wealth.api.deps import CurrentUser, get_conn, require_client
from wealth.tools.holdings import get_holdings
from wealth.tools.performance import get_performance
from wealth.tools.schemas import HoldingsInput, PerformanceInput

router = APIRouter(prefix="/api/client", tags=["client"])

TxnType = Literal["buy", "sell", "dividend", "deposit", "withdrawal"]


def _ctx(conn: psycopg.Connection, user: CurrentUser) -> ToolContext:
    return ToolContext(conn=conn, viewer=user.viewer, today=date.today())


def _scope(ctx: ToolContext, account_id: int | None) -> dict:
    """Scope arguments for the shared queries: one of the client's accounts, or all of them."""
    if account_id is not None:
        if not scoped_account_ids(ctx, account_id=account_id, client_id=None):
            raise HTTPException(404, "Account not found.")
        return {"account_id": account_id, "client_id": None}
    return {"account_id": None, "client_id": ctx.viewer.id}


@router.get("/profile")
def profile(user: CurrentUser = Depends(require_client), conn=Depends(get_conn)):
    return queries.client_profile(conn, user.viewer.id)


@router.get("/accounts")
def accounts(user: CurrentUser = Depends(require_client), conn=Depends(get_conn)):
    return queries.account_list(conn, user.viewer, date.today())


@router.get("/holdings")
def holdings(
    account_id: int | None = Query(default=None, gt=0),
    user: CurrentUser = Depends(require_client),
    conn=Depends(get_conn),
):
    ctx = _ctx(conn, user)
    return get_holdings(ctx, HoldingsInput(**_scope(ctx, account_id), detail="full"))


@router.get("/transactions")
def transactions(
    account_id: int | None = Query(default=None, gt=0),
    types: list[TxnType] | None = Query(default=None),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=25, ge=1, le=100),
    user: CurrentUser = Depends(require_client),
    conn=Depends(get_conn),
):
    ctx = _ctx(conn, user)
    ids = scoped_account_ids(ctx, **_scope(ctx, account_id))
    return queries.transactions_page(conn, user.viewer, ids, types=types, page=page, page_size=page_size)


@router.get("/gains")
def gains(
    account_id: int | None = Query(default=None, gt=0),
    user: CurrentUser = Depends(require_client),
    conn=Depends(get_conn),
):
    ctx = _ctx(conn, user)
    ids = scoped_account_ids(ctx, **_scope(ctx, account_id))
    return queries.gains(conn, user.viewer, ids, ctx.today)


@router.get("/performance")
def performance(
    account_id: int | None = Query(default=None, gt=0),
    user: CurrentUser = Depends(require_client),
    conn=Depends(get_conn),
):
    ctx = _ctx(conn, user)
    scope = _scope(ctx, account_id)
    ids = scoped_account_ids(ctx, **scope)
    result = get_performance(ctx, PerformanceInput(**scope))
    return {**result, "growth": queries.growth_series(conn, user.viewer, ids, ctx.today)}
