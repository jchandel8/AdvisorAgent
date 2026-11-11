"""The single place where "which accounts can this person see?" is defined.

Every query starts with `WITH {VISIBLE}` and joins through it. A person (advisor or client) sees an account
only if an account_access row links them to it and the account is open. Clients are reached only through
those visible accounts, which is what limits an advisor to the accounts they share with a client.

Who the viewer is always comes from the backend session (CLI flag now, verified login token later),
never from the model or from request parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import psycopg

# Requires the query parameters %(viewer_kind)s ('advisor' or 'client') and %(viewer_id)s.
VISIBLE = """
visible AS (
    SELECT aa.account_id
    FROM account_access aa
    JOIN accounts a ON a.id = aa.account_id
    WHERE a.close_date IS NULL
      AND (
          (%(viewer_kind)s = 'advisor' AND aa.advisor_id = %(viewer_id)s)
          OR (%(viewer_kind)s = 'client' AND aa.client_id = %(viewer_id)s)
      )
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

# Visible accounts limited to the tool's scope. Requires the VISIBLE parameters and %(ids)s.
SCOPED = """
scoped AS (
    SELECT account_id FROM visible WHERE account_id = ANY(%(ids)s)
)"""


NOT_FOUND = {"error": "not found"}


@dataclass(frozen=True)
class Viewer:
    """The signed-in person. Built only by the backend from the session."""

    kind: Literal["advisor", "client"]
    id: int

    def __post_init__(self):
        if self.kind not in ("advisor", "client") or not isinstance(self.id, int) or self.id <= 0:
            raise ValueError(f"invalid viewer {self.kind!r} {self.id!r}")

    def params(self) -> dict:
        return {"viewer_kind": self.kind, "viewer_id": self.id}


@dataclass(frozen=True)
class ToolContext:
    """Built by the backend for each request. The viewer comes from the session, never from the model."""

    conn: psycopg.Connection
    viewer: Viewer
    today: date

    def viewer_params(self) -> dict:
        return self.viewer.params()


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
            {**ctx.viewer_params(), "account_id": account_id},
        ).fetchall()
    else:
        rows = ctx.conn.execute(
            f"""WITH {VISIBLE}
            SELECT v.account_id
            FROM visible v
            JOIN account_access ca ON ca.account_id = v.account_id AND ca.client_id = %(client_id)s
            ORDER BY v.account_id""",
            {**ctx.viewer_params(), "client_id": client_id},
        ).fetchall()
    return [r["account_id"] for r in rows]


def advisor_exists(conn: psycopg.Connection, advisor_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM advisors WHERE id = %s", (advisor_id,)).fetchone()
    return row is not None


def accessible_client_name(conn: psycopg.Connection, viewer: Viewer, client_id: int) -> str | None:
    """Name of the client if the viewer can see at least one of their accounts, else None."""
    row = conn.execute(
        f"""WITH {VISIBLE}
        SELECT c.first_name || ' ' || c.last_name AS name
        FROM clients c
        WHERE c.id = %(client_id)s
          AND EXISTS (
              SELECT 1 FROM visible v
              JOIN account_access ca ON ca.account_id = v.account_id AND ca.client_id = c.id
          )""",
        {**viewer.params(), "client_id": client_id},
    ).fetchone()
    if row is None:
        return None
    return row["name"] if isinstance(row, dict) else row[0]
