"""get_accounts: a client's accounts that the advisor can access."""

from __future__ import annotations

from wealth.access import NOT_FOUND, SNAPSHOT, VISIBLE, ToolContext
from wealth.tools.schemas import ClientInput


def get_accounts(ctx: ToolContext, params: ClientInput) -> dict:
    rows = ctx.conn.execute(
        f"""WITH {VISIBLE}, {SNAPSHOT}
        SELECT a.id AS account_id,
               a.account_name,
               a.account_type,
               ca.role AS client_role,
               a.open_date,
               round(coalesce(m.market_value, 0), 2) AS market_value,
               m.as_of_date AS valued_as_of,
               round(sum(coalesce(m.market_value, 0)) OVER (), 2) AS total_market_value
        FROM visible v
        JOIN account_access ca ON ca.account_id = v.account_id AND ca.client_id = %(client_id)s
        JOIN accounts a ON a.id = v.account_id
        LEFT JOIN account_mv m ON m.account_id = v.account_id
        ORDER BY a.id""",
        {**ctx.viewer_params(), "as_of": ctx.today, "client_id": params.client_id},
    ).fetchall()
    if not rows:
        return NOT_FOUND
    total = rows[0]["total_market_value"]
    for r in rows:
        del r["total_market_value"]
    return {
        "client_id": params.client_id,
        "account_count": len(rows),
        "total_market_value": total,
        "accounts": rows,
    }
