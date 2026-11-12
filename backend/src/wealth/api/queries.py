"""Portal queries that the agent tools don't cover (paged tables, chart series, profiles).

Every query here starts from the same VISIBLE / SCOPED fragments as the tools, so the access rule is
defined once in wealth/access.py. Math (totals, gains, growth) is done in SQL.
"""

from __future__ import annotations

from datetime import date

import psycopg

from wealth.access import SCOPED, SNAPSHOT, VISIBLE, Viewer, snapshot_sql


def account_list(conn: psycopg.Connection, viewer: Viewer, today: date, client_id: int | None = None) -> dict:
    """Visible accounts (optionally only those a given client is on) with market value and the total.

    The total sums distinct accounts, so a joint account is counted once.
    """
    rows = conn.execute(
        f"""WITH {VISIBLE}, {SNAPSHOT}
        SELECT a.id AS account_id, a.account_name, a.account_type, a.open_date,
               (SELECT string_agg(c.first_name || ' ' || c.last_name, ' & ' ORDER BY ca.role DESC, c.id)
                  FROM account_access ca JOIN clients c ON c.id = ca.client_id
                 WHERE ca.account_id = a.id) AS owners,
               round(coalesce(m.market_value, 0), 2) AS market_value,
               m.as_of_date,
               round(sum(coalesce(m.market_value, 0)) OVER (), 2) AS total
        FROM visible v
        JOIN accounts a ON a.id = v.account_id
        LEFT JOIN account_mv m ON m.account_id = v.account_id
        WHERE %(client_id)s::int IS NULL
           OR EXISTS (SELECT 1 FROM account_access x WHERE x.account_id = a.id AND x.client_id = %(client_id)s)
        ORDER BY m.market_value DESC NULLS LAST, a.id""",
        {**viewer.params(), "as_of": today, "client_id": client_id},
    ).fetchall()
    total = rows[0]["total"] if rows else 0
    for r in rows:
        del r["total"]
    return {"account_count": len(rows), "total_market_value": total, "accounts": rows}


def book_total(conn: psycopg.Connection, viewer: Viewer, today: date) -> dict:
    """Total market value and account count over the viewer's visible accounts (each account once)."""
    return conn.execute(
        f"""WITH {VISIBLE}, {SNAPSHOT}
        SELECT count(*) AS account_count, round(coalesce(sum(m.market_value), 0), 2) AS total_market_value
        FROM visible v LEFT JOIN account_mv m ON m.account_id = v.account_id""",
        {**viewer.params(), "as_of": today},
    ).fetchone()


def transactions_page(
    conn: psycopg.Connection,
    viewer: Viewer,
    ids: list[int],
    *,
    types: list[str] | None,
    page: int,
    page_size: int,
) -> dict:
    rows = conn.execute(
        f"""WITH {VISIBLE}, {SCOPED}
        SELECT t.id, t.account_id, a.account_name, t.trade_date, t.type, t.symbol, s.description, s.sector,
               t.quantity, t.price, t.amount, t.realized_gain,
               count(*) OVER () AS total_rows
        FROM transactions t
        JOIN scoped sc ON sc.account_id = t.account_id
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN securities s ON s.symbol = t.symbol
        WHERE %(types)s::text[] IS NULL OR t.type = ANY(%(types)s::text[])
        ORDER BY t.trade_date DESC, t.id DESC
        LIMIT %(limit)s OFFSET %(offset)s""",
        {
            **viewer.params(),
            "ids": ids,
            "types": types,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        },
    ).fetchall()
    total = rows[0]["total_rows"] if rows else 0
    for r in rows:
        del r["total_rows"]
    return {"page": page, "page_size": page_size, "total_rows": total, "transactions": rows}


def gains(conn: psycopg.Connection, viewer: Viewer, ids: list[int], today: date) -> dict:
    """Realized gain/loss from sells (recorded with the average-cost method) and unrealized gain/loss of
    current holdings (market value minus cost basis)."""
    q = {**viewer.params(), "ids": ids, "as_of": today}
    realized = conn.execute(
        f"""WITH {VISIBLE}, {SCOPED}
        SELECT date_trunc('month', t.trade_date)::date AS month,
               round(sum(t.realized_gain), 2) AS realized_gain,
               count(*) AS sells
        FROM transactions t JOIN scoped sc ON sc.account_id = t.account_id
        WHERE t.type = 'sell' AND t.trade_date <= %(as_of)s
        GROUP BY 1 ORDER BY 1""",
        q,
    ).fetchall()
    unrealized = conn.execute(
        f"""WITH {VISIBLE}, {SCOPED}, {snapshot_sql("scoped")}
        SELECT h.symbol, s.description, s.sector,
               round(sum(h.quantity * h.price), 2) AS market_value,
               round(sum(h.cost_basis), 2) AS cost_basis,
               round(sum(h.quantity * h.price) - sum(h.cost_basis), 2) AS unrealized_gain
        FROM holdings h
        JOIN snapshot sn ON sn.account_id = h.account_id AND sn.as_of_date = h.as_of_date
        JOIN securities s ON s.symbol = h.symbol
        WHERE s.asset_class <> 'cash'
        GROUP BY h.symbol, s.description, s.sector
        ORDER BY abs(sum(h.quantity * h.price) - sum(h.cost_basis)) DESC, h.symbol""",
        q,
    ).fetchall()
    totals = conn.execute(
        f"""WITH {VISIBLE}, {SCOPED}, {snapshot_sql("scoped")}
        SELECT
          (SELECT round(coalesce(sum(t.realized_gain), 0), 2) FROM transactions t
             JOIN scoped sc ON sc.account_id = t.account_id
            WHERE t.type = 'sell' AND t.trade_date <= %(as_of)s) AS realized_total,
          (SELECT round(coalesce(sum(h.quantity * h.price - h.cost_basis), 0), 2) FROM holdings h
             JOIN snapshot sn ON sn.account_id = h.account_id AND sn.as_of_date = h.as_of_date) AS unrealized_total""",
        q,
    ).fetchone()
    return {
        **totals,
        "realized_by_month": realized,
        "unrealized_by_symbol": unrealized,
    }


def growth_series(conn: psycopg.Connection, viewer: Viewer, ids: list[int], today: date) -> list[dict]:
    """Market value per snapshot date, and growth of 100 from the market-value weighted monthly returns
    (time-weighted, so deposits and withdrawals don't count as growth)."""
    return conn.execute(
        f"""WITH {VISIBLE}, {SCOPED},
        acct AS (
            SELECT h.account_id, h.as_of_date, sum(h.quantity * h.price) AS mv
            FROM holdings h JOIN scoped sc ON sc.account_id = h.account_id
            WHERE h.as_of_date <= %(as_of)s
            GROUP BY h.account_id, h.as_of_date
        ),
        by_date AS (
            SELECT a.as_of_date,
                   sum(a.mv) AS mv,
                   sum(p.return_1m * a.mv) FILTER (WHERE p.return_1m IS NOT NULL)
                     / nullif(sum(a.mv) FILTER (WHERE p.return_1m IS NOT NULL), 0) AS r
            FROM acct a
            LEFT JOIN performance p ON p.account_id = a.account_id AND p.as_of_date = a.as_of_date
            GROUP BY a.as_of_date
        )
        SELECT as_of_date,
               round(mv, 2) AS market_value,
               round(100 * exp(sum(ln(1 + coalesce(r, 0))) OVER w - first_value(ln(1 + coalesce(r, 0))) OVER w),
                     2) AS growth_index
        FROM by_date
        WINDOW w AS (ORDER BY as_of_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
        ORDER BY as_of_date""",
        {**viewer.params(), "ids": ids, "as_of": today},
    ).fetchall()


def advisor_profile(conn: psycopg.Connection, advisor_id: int) -> dict:
    return conn.execute(
        "SELECT id, username, first_name, last_name, email, phone, certifications, city, state"
        " FROM advisors WHERE id = %s",
        (advisor_id,),
    ).fetchone()


def client_profile(conn: psycopg.Connection, client_id: int) -> dict:
    return conn.execute(
        "SELECT id, username, first_name, last_name, email, phone, address, city, state"
        " FROM clients WHERE id = %s",
        (client_id,),
    ).fetchone()


def demo_users(conn: psycopg.Connection, today: date) -> list[dict]:
    """Suggested demo users with what each can see (computed through the same access rules)."""
    return conn.execute(
        """SELECT d.person_type AS kind, coalesce(d.advisor_id, d.client_id, d.admin_id) AS id, d.note,
                  coalesce(a.first_name || ' ' || a.last_name, c.first_name || ' ' || c.last_name,
                           m.first_name || ' ' || m.last_name) AS name,
                  coalesce(a.username, c.username, m.username) AS username,
                  coalesce(a.email, c.email, m.email) AS email,
                  (SELECT count(*) FROM account_access x
                    WHERE (d.person_type = 'advisor' AND x.advisor_id = d.advisor_id)
                       OR (d.person_type = 'client' AND x.client_id = d.client_id)) AS account_count,
                  CASE WHEN d.person_type = 'advisor' THEN
                    (SELECT count(DISTINCT ca.client_id) FROM account_access aa
                       JOIN account_access ca ON ca.account_id = aa.account_id AND ca.client_id IS NOT NULL
                      WHERE aa.advisor_id = d.advisor_id)
                  END AS client_count
           FROM demo_users d
           LEFT JOIN advisors a ON a.id = d.advisor_id
           LEFT JOIN clients c ON c.id = d.client_id
           LEFT JOIN admins m ON m.id = d.admin_id
           ORDER BY d.sort_order"""
    ).fetchall()
