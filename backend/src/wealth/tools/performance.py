"""get_performance: return periods for one account, or market-value weighted across a client's accounts."""

from __future__ import annotations

from wealth.access import NOT_FOUND, SCOPED, VISIBLE, ToolContext, scoped_account_ids, snapshot_sql
from wealth.tools.schemas import PerformanceInput

PERIODS = ("1d", "1m", "3m", "6m", "ytd", "1y", "2y", "3y", "5y")


def _return_col(p: str) -> str:
    """Per-account rows: the account's own figure. Total row: market-value weighted average, leaving out
    accounts with no figure for that period. Returned as percentages."""
    return (
        f"round(100 * CASE WHEN GROUPING(w.account_id) = 0 THEN max(w.return_{p}) ELSE "
        f"sum(w.return_{p} * w.mv) FILTER (WHERE w.return_{p} IS NOT NULL)"
        f" / nullif(sum(w.mv) FILTER (WHERE w.return_{p} IS NOT NULL), 0) END, 2) AS return_{p}_pct"
    )


# One query: a row per account plus a combined row (the () grouping set).
_QUERY = f"""
WITH {VISIBLE}, {SCOPED}, {snapshot_sql("scoped")},
latest AS (
    SELECT DISTINCT ON (p.account_id) p.*
    FROM performance p
    JOIN scoped sc ON sc.account_id = p.account_id
    WHERE p.as_of_date <= %(as_of)s
    ORDER BY p.account_id, p.as_of_date DESC
),
weighted AS (
    SELECT l.*, coalesce(m.market_value, 0) AS mv
    FROM latest l
    LEFT JOIN account_mv m ON m.account_id = l.account_id
)
SELECT GROUPING(w.account_id) AS is_total,
       {", ".join(f"bool_or(w.return_{p} IS NULL) AS missing_{p}" for p in PERIODS)},
       w.account_id, a.account_name, w.as_of_date,
       round(sum(w.mv), 2) AS market_value,
       {", ".join(_return_col(p) for p in PERIODS)}
FROM weighted w
JOIN accounts a ON a.id = w.account_id
GROUP BY GROUPING SETS ((w.account_id, a.account_name, w.as_of_date), ())
ORDER BY GROUPING(w.account_id), w.account_id"""


def get_performance(ctx: ToolContext, params: PerformanceInput) -> dict:
    ids = scoped_account_ids(ctx, account_id=params.account_id, client_id=params.client_id)
    if not ids:
        return NOT_FOUND
    q = {"advisor_id": ctx.advisor_id, "ids": ids, "as_of": params.as_of_date or ctx.today}

    rows = ctx.conn.execute(_QUERY, q).fetchall()
    scope = {"account_id": params.account_id, "client_id": params.client_id}
    if not rows:
        return {"scope": scope, "accounts": [], "note": "no performance figures on or before that date"}
    missing = {p: rows[-1][f"missing_{p}"] for p in PERIODS}  # from the combined row
    for r in rows:
        for p in PERIODS:
            del r[f"missing_{p}"]
    accounts = [r for r in rows if not r.pop("is_total")]
    if not accounts:
        return {"scope": scope, "accounts": [], "note": "no performance figures on or before that date"}

    combined = {k: v for k, v in rows[-1].items() if k.startswith("return_") or k == "market_value"}
    return {
        "scope": scope,
        "returns_are": "percent",
        "combined_market_value_weighted": combined,
        # Periods where some accounts have no figure (too new); the combined figure covers the others only.
        "partial_periods": [p for p in PERIODS if missing[p]] if len(accounts) > 1 else [],
        "accounts": accounts,
    }
