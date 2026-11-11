"""Checks against the generated dev database (DATABASE_URL), using the real read-only tool path.

Skipped if the dev database has not been seeded (`uv run python -m wealth.datagen`).
"""

from __future__ import annotations

import calendar
from datetime import date

import psycopg
import pytest

from wealth.config import get_settings
from wealth.tools.registry import execute_tool

pytestmark = pytest.mark.seeded


@pytest.fixture(scope="module")
def dev():
    try:
        conn = psycopg.connect(get_settings().database_url, autocommit=True)
        n = conn.execute("SELECT count(*) FROM accounts").fetchone()[0]
    except psycopg.Error as exc:
        pytest.skip(f"dev database not available: {exc}")
    if n == 0:
        pytest.skip("dev database is empty; run `uv run python -m wealth.datagen`")
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def anchor(dev) -> date:
    return dev.execute("SELECT max(as_of_date) FROM holdings").fetchone()[0]


def tool(name, advisor_id, today, **kwargs):
    return execute_tool(name, kwargs, advisor_id=advisor_id, today=today)  # real read_only() pool path


def test_every_advisor_sees_exactly_their_acl_clients(dev, anchor):
    for (advisor_id,) in dev.execute("SELECT id FROM advisors ORDER BY id").fetchall():
        expected = {
            r[0]
            for r in dev.execute(
                """SELECT DISTINCT ca.client_id FROM account_access aa
               JOIN account_access ca ON ca.account_id = aa.account_id AND ca.client_id IS NOT NULL
               WHERE aa.advisor_id = %s""",
                (advisor_id,),
            ).fetchall()
        }
        got = {c["client_id"] for c in tool("get_my_clients", advisor_id, anchor)["clients"]}
        assert got == expected, advisor_id


def test_split_clients_show_only_shared_accounts(dev, anchor):
    # Every (advisor, client) pair where the advisor shares some but not all of the client's accounts.
    pairs = dev.execute(
        """SELECT aa.advisor_id, ca.client_id,
                  array_agg(DISTINCT ca.account_id ORDER BY ca.account_id) AS shared,
                  (SELECT count(*) FROM account_access x WHERE x.client_id = ca.client_id) AS owned
           FROM account_access aa
           JOIN account_access ca ON ca.account_id = aa.account_id AND ca.client_id IS NOT NULL
           WHERE aa.advisor_id IS NOT NULL
           GROUP BY aa.advisor_id, ca.client_id"""
    ).fetchall()
    split = [p for p in pairs if len(p[2]) < p[3]]
    assert len(split) >= 5
    for advisor_id, client_id, shared, _owned in split:
        accounts = tool("get_accounts", advisor_id, anchor, client_id=client_id)["accounts"]
        assert [a["account_id"] for a in accounts] == shared, (advisor_id, client_id)


def test_unshared_account_is_not_found(dev, anchor):
    advisor_id, account_id = dev.execute(
        """SELECT 1, a.id FROM accounts a
           WHERE NOT EXISTS (SELECT 1 FROM account_access x WHERE x.account_id = a.id AND x.advisor_id = 1)
           ORDER BY a.id LIMIT 1"""
    ).fetchone()
    for name in ("get_holdings", "get_performance", "get_transactions"):
        assert tool(name, advisor_id, anchor, account_id=account_id) == {"error": "not found"}


def test_example_question_has_a_real_answer(dev, anchor):
    """'Which of my clients are overweight in tech and have a review due this month?'"""
    days_left = calendar.monthrange(anchor.year, anchor.month)[1] - anchor.day
    found_any = False
    for (advisor_id,) in dev.execute("SELECT id FROM advisors ORDER BY id LIMIT 2").fetchall():
        due = tool("find_reviews_due", advisor_id, anchor, within_days=days_left)["clients"]
        heavy = []
        for c in due:
            h = tool("get_holdings", advisor_id, anchor, client_id=c["client_id"])
            tech = next(
                (s["pct_of_portfolio"] for s in h["sector_summary"] if s["sector"] == "Technology"), 0
            )
            if tech > 40:
                heavy.append(c["client_id"])
        found_any = found_any or bool(heavy)
    assert found_any


def test_market_values_match_holdings(dev, anchor):
    advisor_id = 1
    clients = tool("get_my_clients", advisor_id, anchor)["clients"]
    c = max(clients, key=lambda c: c["accessible_market_value"])
    h = tool("get_holdings", advisor_id, anchor, client_id=c["client_id"])
    assert abs(h["portfolio_market_value"] - c["accessible_market_value"]) < 0.02
    assert abs(sum(s["pct_of_portfolio"] for s in h["sector_summary"]) - 100) < 0.1
