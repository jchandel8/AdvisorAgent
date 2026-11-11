"""Client-level tools: get_my_clients, find_reviews_due."""

from __future__ import annotations

from datetime import timedelta

from wealth.access import SNAPSHOT, VISIBLE, ToolContext
from wealth.tools.schemas import NoInput, ReviewsInput

# One row per client reachable through a visible account, with totals over ONLY those accounts.
# A joint account counts in full for each of its clients (it is part of each client's portfolio).
_CLIENT_ROLLUP = f"""
WITH {VISIBLE}, {SNAPSHOT},
client_accounts AS (
    SELECT DISTINCT ca.client_id, v.account_id
    FROM visible v
    JOIN account_access ca ON ca.account_id = v.account_id AND ca.client_id IS NOT NULL
)
SELECT c.id AS client_id,
       c.first_name || ' ' || c.last_name AS name,
       c.risk_profile,
       c.next_review_date,
       c.next_review_date - %(as_of)s::date AS days_until_review,
       count(*) AS accessible_account_count,
       round(coalesce(sum(m.market_value), 0), 2) AS accessible_market_value
FROM client_accounts x
JOIN clients c ON c.id = x.client_id
LEFT JOIN account_mv m ON m.account_id = x.account_id
"""


def get_my_clients(ctx: ToolContext, params: NoInput) -> dict:
    rows = ctx.conn.execute(
        _CLIENT_ROLLUP + " GROUP BY c.id ORDER BY c.last_name, c.first_name, c.id",
        {**ctx.viewer_params(), "as_of": ctx.today},
    ).fetchall()
    return {"client_count": len(rows), "clients": rows}


def find_reviews_due(ctx: ToolContext, params: ReviewsInput) -> dict:
    rows = ctx.conn.execute(
        _CLIENT_ROLLUP
        + """ WHERE c.next_review_date <= %(until)s
        GROUP BY c.id
        ORDER BY c.next_review_date, c.id""",
        {
            **ctx.viewer_params(),
            "as_of": ctx.today,
            "until": ctx.today + timedelta(days=params.within_days),
        },
    ).fetchall()
    for r in rows:
        r["overdue"] = r["days_until_review"] < 0
    return {"today": ctx.today, "within_days": params.within_days, "client_count": len(rows), "clients": rows}
