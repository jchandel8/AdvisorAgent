"""The single place where "which accounts can this advisor see?" is defined.

Every tool query starts with `WITH {VISIBLE}` and joins through it. An advisor sees an account only if
there is an account_access row linking them to it and the account is open. Clients are reached only
through those visible accounts, which is what limits an advisor to the accounts they share with a client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg

# Requires the query parameter %(advisor_id)s.
VISIBLE = """
visible AS (
    SELECT aa.account_id
    FROM account_access aa
    JOIN accounts a ON a.id = aa.account_id
    WHERE aa.advisor_id = %(advisor_id)s
      AND a.close_date IS NULL
)"""


def snapshot_sql(source: str = "visible") -> str:
    """CTEs `snapshot` and `account_mv`: each account's latest holdings snapshot on or before %(as_of)s.

    `source` is the CTE listing the accounts to include: `visible` (all the advisor's accounts) or
    `scoped` (a subset of visible accounts). Requires the query parameter %(as_of)s.
    """
    assert source in ("visible", "scoped")  # never interpolate anything else
    # LATERAL makes Postgres look up each account through the (account_id, as_of_date, symbol) index
    # instead of scanning the whole holdings table.
    return f"""
snapshot AS (
    SELECT src.account_id, latest.as_of_date
    FROM {source} src
    CROSS JOIN LATERAL (
        SELECT h.as_of_date FROM holdings h
        WHERE h.account_id = src.account_id AND h.as_of_date <= %(as_of)s
        ORDER BY h.as_of_date DESC
        LIMIT 1
    ) latest
),
account_mv AS (
    SELECT sn.account_id, sn.as_of_date, mv.market_value
    FROM snapshot sn
    CROSS JOIN LATERAL (
        SELECT sum(h.quantity * h.price) AS market_value FROM holdings h
        WHERE h.account_id = sn.account_id AND h.as_of_date = sn.as_of_date
    ) mv
)"""


SNAPSHOT = snapshot_sql("visible")

# Visible accounts limited to the tool's scope. Requires %(advisor_id)s (via VISIBLE) and %(ids)s.
SCOPED = """
scoped AS (
    SELECT account_id FROM visible WHERE account_id = ANY(%(ids)s)
)"""


NOT_FOUND = {"error": "not found"}


@dataclass(frozen=True)
class ToolContext:
    """Built by the backend for each request. advisor_id comes from the session, never from the model."""

    conn: psycopg.Connection
    advisor_id: int
    today: date


def scoped_account_ids(ctx: ToolContext, *, account_id: int | None, client_id: int | None) -> list[int]:
    """Visible account IDs for the requested scope.

    - account_id: [account_id] if the advisor can see it, else [].
    - client_id: the visible accounts that client has an ACL row on (never the client's other accounts).
    An empty list means "not found" — callers must not distinguish "doesn't exist" from "not allowed".
    """
    if (account_id is None) == (client_id is None):
        raise ValueError("exactly one of account_id or client_id is required")
    if account_id is not None:
        rows = ctx.conn.execute(
            f"WITH {VISIBLE} SELECT account_id FROM visible WHERE account_id = %(account_id)s",
            {"advisor_id": ctx.advisor_id, "account_id": account_id},
        ).fetchall()
    else:
        rows = ctx.conn.execute(
            f"""WITH {VISIBLE}
            SELECT v.account_id
            FROM visible v
            JOIN account_access ca ON ca.account_id = v.account_id AND ca.client_id = %(client_id)s
            ORDER BY v.account_id""",
            {"advisor_id": ctx.advisor_id, "client_id": client_id},
        ).fetchall()
    return [r["account_id"] for r in rows]


def advisor_exists(conn: psycopg.Connection, advisor_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM advisors WHERE id = %s", (advisor_id,)).fetchone()
    return row is not None
