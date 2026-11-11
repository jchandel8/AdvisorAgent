"""get_transactions: activity in a date range for one account or a client's accessible accounts."""

from __future__ import annotations

from datetime import timedelta

from wealth.access import NOT_FOUND, VISIBLE, ToolContext, scoped_account_ids
from wealth.tools.schemas import TransactionsInput

MAX_ROWS = 200

# Security filters exclude deposits and withdrawals (they have no security), which is the intended meaning.
_IN_RANGE = f"""
WITH {VISIBLE}
SELECT {{columns}}
FROM transactions t
JOIN visible v ON v.account_id = t.account_id
LEFT JOIN securities s ON s.symbol = t.symbol
WHERE t.account_id = ANY(%(ids)s)
  AND t.trade_date BETWEEN %(start)s AND %(end)s
  AND (%(types)s::text[] IS NULL OR t.type = ANY(%(types)s::text[]))
  AND (%(sectors)s::text[] IS NULL OR s.sector = ANY(%(sectors)s::text[]))
  AND (%(asset_classes)s::text[] IS NULL OR s.asset_class = ANY(%(asset_classes)s::text[]))
  AND (%(currencies)s::text[] IS NULL OR s.currency::text = ANY(%(currencies)s::text[]))
"""


def get_transactions(ctx: ToolContext, params: TransactionsInput) -> dict:
    ids = scoped_account_ids(ctx, account_id=params.account_id, client_id=params.client_id)
    if not ids:
        return NOT_FOUND
    end = params.end_date or ctx.today
    start = params.start_date or end - timedelta(days=90)
    if start > end:
        return {"error": "start_date must be on or before end_date"}
    q = {
        "advisor_id": ctx.advisor_id,
        "ids": ids,
        "start": start,
        "end": end,
        "types": params.types,
        **params.filter_params(),
    }

    rows = ctx.conn.execute(
        _IN_RANGE.format(
            columns="t.account_id, t.trade_date, t.type, t.symbol, s.sector, t.quantity, t.price, t.amount,"
            " t.realized_gain"
        )
        + " ORDER BY t.trade_date DESC, t.id DESC LIMIT %(limit)s",
        {**q, "limit": MAX_ROWS + 1},
    ).fetchall()

    summary = ctx.conn.execute(
        _IN_RANGE.format(
            columns="t.type, count(*) AS count, round(sum(t.amount), 2) AS total_amount,"
            " round(sum(t.realized_gain), 2) AS realized_gain"
        )
        + " GROUP BY t.type ORDER BY t.type",
        q,
    ).fetchall()

    return {
        "scope": {"account_id": params.account_id, "client_id": params.client_id},
        "start_date": start,
        "end_date": end,
        "filters": {k: v for k, v in {"types": params.types, **params.filter_params()}.items() if v}
        or "none",
        "summary_by_type": summary,
        "truncated": len(rows) > MAX_ROWS,
        "transactions": rows[:MAX_ROWS],
    }
