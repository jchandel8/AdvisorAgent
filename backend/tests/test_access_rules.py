"""The permission model, tested through every tool against the hand-built fixture (see tests/fixtures.py)."""

from __future__ import annotations

from datetime import date

import pytest

from tests.fixtures import (
    A1,
    A2,
    A3,
    ALL_ACCOUNTS,
    ALL_CLIENTS,
    C1,
    C2,
    C3,
    C4,
    MISSING_ID,
    TODAY,
    J,
    K,
    X,
    Y,
    Z,
)
from wealth.tools.registry import TOOLS, execute_tool, tool_definitions

NOT_FOUND = {"error": "not found"}


def run(conn, advisor_id, name, **kwargs):
    return execute_tool(name, kwargs, advisor_id=advisor_id, today=TODAY, conn=conn)


# --- clients -------------------------------------------------------------------------------------


def test_advisor_sees_only_clients_sharing_an_account(conn):
    result = run(conn, A1, "get_my_clients")
    assert {c["client_id"] for c in result["clients"]} == {C1, C2, C3}  # never C4


def test_client_totals_count_only_shared_accounts(conn):
    by_id = {c["client_id"]: c for c in run(conn, A1, "get_my_clients")["clients"]}
    assert by_id[C1]["accessible_market_value"] == 5000  # X only; not Y (15000), not closed K
    assert by_id[C1]["accessible_account_count"] == 1
    assert by_id[C3]["accessible_market_value"] == 4000  # J only; not Z (20000)


def test_advisor_without_acl_rows_sees_no_clients(conn):
    assert run(conn, A3, "get_my_clients") == {"client_count": 0, "clients": []}


# --- accounts ------------------------------------------------------------------------------------


def test_shared_client_shows_only_shared_accounts(conn):
    result = run(conn, A1, "get_accounts", client_id=C1)
    assert [a["account_id"] for a in result["accounts"]] == [X]  # not Y (A2 only), not K (closed)


def test_joint_account_visible_for_both_clients_but_not_their_other_accounts(conn):
    assert [a["account_id"] for a in run(conn, A1, "get_accounts", client_id=C2)["accounts"]] == [J]
    c3 = run(conn, A1, "get_accounts", client_id=C3)
    assert [a["account_id"] for a in c3["accounts"]] == [J]  # not Z
    assert c3["accounts"][0]["client_role"] == "joint_owner"
    assert c3["total_market_value"] == 4000


def test_second_advisor_sees_their_own_set(conn):
    assert [a["account_id"] for a in run(conn, A2, "get_accounts", client_id=C1)["accounts"]] == [Y]
    assert [a["account_id"] for a in run(conn, A2, "get_accounts", client_id=C3)["accounts"]] == [J, Z]


def test_unshared_client_is_not_found_same_as_missing(conn):
    assert run(conn, A1, "get_accounts", client_id=C4) == NOT_FOUND
    assert run(conn, A1, "get_accounts", client_id=MISSING_ID) == NOT_FOUND


# --- holdings ------------------------------------------------------------------------------------


def test_forbidden_account_looks_exactly_like_missing_account(conn):
    forbidden = run(conn, A1, "get_holdings", account_id=Y)
    missing = run(conn, A1, "get_holdings", account_id=MISSING_ID)
    assert forbidden == missing == NOT_FOUND


def test_closed_account_is_hidden(conn):
    assert run(conn, A1, "get_holdings", account_id=K) == NOT_FOUND


def test_client_holdings_include_only_shared_accounts(conn):
    result = run(conn, A1, "get_holdings", client_id=C1)
    assert [a["account_id"] for a in result["accounts"]] == [X]
    assert result["portfolio_market_value"] == 5000
    assert "JNJ" not in {h["symbol"] for h in result["holdings"]}  # JNJ lives in Y


def test_holdings_math(conn):
    result = run(conn, A1, "get_holdings", account_id=X)
    sectors = {s["sector"]: s["pct_of_portfolio"] for s in result["sector_summary"]}
    assert sectors["Technology"] == 80.0
    aapl = next(h for h in result["holdings"] if h["symbol"] == "AAPL")
    assert (
        aapl["market_value"] == 2000 and aapl["unrealized_gain"] == 1000 and aapl["pct_of_portfolio"] == 40.0
    )
    assert result["selection"]["cost_basis"] == 3600


def test_holdings_as_of_uses_latest_snapshot_on_or_before(conn):
    result = run(conn, A1, "get_holdings", account_id=X, as_of_date="2026-11-01")
    assert result["accounts"][0]["as_of_date"] == "2026-10-31"
    assert result["portfolio_market_value"] == 2800  # 10 AAPL @180 + 10 AGG @100


def test_joint_holdings_combined_by_symbol_for_a2(conn):
    result = run(conn, A2, "get_holdings", client_id=C3)  # J + Z
    msft = next(h for h in result["holdings"] if h["symbol"] == "MSFT")
    assert msft["market_value"] == 20000
    assert result["portfolio_market_value"] == 24000


# --- transactions --------------------------------------------------------------------------------


def test_client_transactions_include_only_shared_accounts(conn):
    result = run(conn, A1, "get_transactions", client_id=C1, start_date="2020-01-01", end_date="2026-12-31")
    assert {t["account_id"] for t in result["transactions"]} == {X}  # not Y, not closed K
    assert len(result["transactions"]) == 3


def test_transactions_summary_and_realized_gain(conn):
    result = run(conn, A1, "get_transactions", account_id=J, start_date="2026-01-01", end_date="2026-12-31")
    assert result["summary_by_type"] == [
        {"type": "sell", "count": 1, "total_amount": 420.0, "realized_gain": 60.0}
    ]


def test_transactions_date_order_validated(conn):
    result = run(conn, A1, "get_transactions", account_id=X, start_date="2026-12-01", end_date="2026-01-01")
    assert result["error"] == "invalid input"


# --- performance ---------------------------------------------------------------------------------


def test_performance_is_market_value_weighted_over_shared_accounts(conn):
    a1 = run(conn, A1, "get_performance", client_id=C3)  # J only
    assert a1["combined_market_value_weighted"]["return_1m_pct"] == 3.0
    a2 = run(conn, A2, "get_performance", client_id=C3)  # J (4000 @3%) + Z (20000 @4%)
    assert a2["combined_market_value_weighted"]["return_1m_pct"] == round(
        100 * (0.03 * 4000 + 0.04 * 20000) / 24000, 2
    )
    # 5Y: only Z has a figure, so the combined figure is Z's alone
    assert a2["combined_market_value_weighted"]["return_5y_pct"] == 50.0


def test_performance_forbidden_account(conn):
    assert run(conn, A1, "get_performance", account_id=Z) == NOT_FOUND


# --- reviews -------------------------------------------------------------------------------------


def test_reviews_due_only_for_visible_clients(conn):
    result = run(conn, A1, "find_reviews_due", within_days=30)
    assert [c["client_id"] for c in result["clients"]] == [C2, C1]  # C2 overdue first; never C4
    assert result["clients"][0]["overdue"] is True
    assert result["clients"][1]["days_until_review"] == 9


def test_reviews_window_widens(conn):
    result = run(conn, A1, "find_reviews_due", within_days=90)
    assert {c["client_id"] for c in result["clients"]} == {C1, C2, C3}


def test_other_advisor_sees_their_review(conn):
    assert C4 in {c["client_id"] for c in run(conn, A2, "find_reviews_due", within_days=7)["clients"]}


# --- generic guards: these fail automatically if a new tool forgets the ACL join -------------------


def _calls_for(tool_name):
    if tool_name == "get_my_clients":
        return [{}]
    if tool_name == "find_reviews_due":
        return [{"within_days": 365}]
    if tool_name == "get_accounts":
        return [{"client_id": c} for c in ALL_CLIENTS]
    calls = [{"account_id": a} for a in ALL_ACCOUNTS] + [{"client_id": c} for c in ALL_CLIENTS]
    if tool_name == "get_transactions":
        for c in calls:
            c.update(start_date="2000-01-01", end_date="2030-12-31")
    return calls


@pytest.mark.parametrize("tool_name", sorted(TOOLS))
def test_advisor_with_no_access_gets_nothing_from_any_tool(conn, tool_name):
    for args in _calls_for(tool_name):
        result = run(conn, A3, tool_name, **args)
        assert result == NOT_FOUND or result.get("clients") == [], (tool_name, args, result)


@pytest.mark.parametrize("tool_name", sorted(TOOLS))
def test_every_tool_rejects_model_supplied_advisor_id(conn, tool_name):
    model_input = {**_calls_for(tool_name)[0], "advisor_id": A2}
    result = execute_tool(tool_name, model_input, advisor_id=A1, today=TODAY, conn=conn)
    assert result["error"] == "invalid input"
    assert any("advisor_id" in d for d in result["details"])


def test_no_tool_schema_mentions_advisor_id():
    for definition in tool_definitions():
        assert "advisor_id" not in str(definition["input_schema"]), definition["name"]


def test_tool_definitions_are_complete():
    names = {d["name"] for d in tool_definitions()}
    assert names == {
        "get_my_clients",
        "get_accounts",
        "get_holdings",
        "get_transactions",
        "get_performance",
        "find_reviews_due",
    }


def test_scope_requires_exactly_one_of_account_or_client(conn):
    assert run(conn, A1, "get_holdings")["error"] == "invalid input"
    assert run(conn, A1, "get_holdings", account_id=X, client_id=C1)["error"] == "invalid input"


def test_unknown_tool(conn):
    assert run(conn, A1, "drop_tables") == {"error": "unknown tool 'drop_tables'"}


def test_fixture_today_is_after_every_snapshot():
    assert TODAY >= date(2026, 11, 10)


# --- filters and detail levels --------------------------------------------------------------------


def test_sector_filter_returns_only_that_sector(conn):
    result = run(conn, A1, "get_holdings", account_id=X, sectors=["Technology"])
    assert result["portfolio_market_value"] == 5000
    assert result["selection"]["market_value"] == 4000
    assert result["selection"]["pct_of_portfolio"] == 80.0
    assert {h["symbol"] for h in result["holdings"]} == {"AAPL", "MSFT"}
    assert [s["sector"] for s in result["sector_summary"]] == ["Technology"]


def test_asset_class_and_currency_filters(conn):
    fi = run(conn, A1, "get_holdings", account_id=X, asset_classes=["fixed_income"])
    assert [h["symbol"] for h in fi["holdings"]] == ["AGG"] and fi["selection"]["pct_of_portfolio"] == 20.0
    usd = run(conn, A1, "get_holdings", account_id=X, currencies=["USD"])
    assert usd["selection"]["market_value"] == 5000


def test_filters_that_match_nothing_return_zero(conn):
    result = run(
        conn, A1, "get_holdings", account_id=X, sectors=["Technology"], asset_classes=["fixed_income"]
    )
    assert result["selection"]["market_value"] == 0 and result["holdings"] == []
    assert result["sector_summary"] == [] and result["portfolio_market_value"] == 5000


def test_filters_never_widen_access(conn):
    # JNJ (Health Care) is only in account Y, which A1 cannot see.
    result = run(conn, A1, "get_holdings", client_id=C1, sectors=["Health Care"])
    assert result["selection"]["market_value"] == 0
    assert [a["account_id"] for a in result["accounts"]] == [X]


def test_unknown_filter_values_are_rejected(conn):
    assert run(conn, A1, "get_holdings", account_id=X, sectors=["Crypto"])["error"] == "invalid input"
    assert run(conn, A1, "get_holdings", account_id=X, currencies=["EUR"])["error"] == "invalid input"
    assert run(conn, A1, "get_holdings", account_id=X, sectors=[])["error"] == "invalid input"


def test_detail_levels(conn):
    totals = run(conn, A1, "get_holdings", account_id=X, detail="totals")
    assert totals["holdings"] == [] and totals["selection"]["positions"] == 3
    full = run(conn, A1, "get_holdings", account_id=X, detail="full")
    assert len(full["holdings"]) == 3


def test_transaction_filters(conn):
    window = {"start_date": "2020-01-01", "end_date": "2026-12-31"}
    buys = run(conn, A1, "get_transactions", account_id=X, types=["buy"], **window)
    assert [t["type"] for t in buys["transactions"]] == ["buy"]
    tech = run(conn, A1, "get_transactions", account_id=X, sectors=["Technology"], **window)
    assert {t["type"] for t in tech["transactions"]} == {"buy", "dividend"}  # the deposit has no security
    assert (
        run(conn, A1, "get_transactions", account_id=X, types=["transfer"], **window)["error"]
        == "invalid input"
    )


@pytest.mark.parametrize("tool_name", ["get_holdings", "get_transactions"])
def test_filtered_calls_give_nothing_to_advisor_without_access(conn, tool_name):
    for args in _calls_for(tool_name):
        result = run(conn, A3, tool_name, sectors=["Technology"], asset_classes=["equity"], **args)
        assert result == NOT_FOUND, (tool_name, args, result)


def test_performance_flags_periods_missing_for_some_accounts(conn):
    a2 = run(conn, A2, "get_performance", client_id=C3)  # J has no 5Y figure, Z does
    assert "5y" in a2["partial_periods"] and "1m" not in a2["partial_periods"]
    assert run(conn, A1, "get_performance", account_id=X)["partial_periods"] == []


# --- Assistant focus: a selected client is a hard scope ---------------------------------------------------


def focused(conn, advisor_id, focus, name, **kwargs):
    return execute_tool(name, kwargs, advisor_id=advisor_id, today=TODAY, conn=conn, focus_client_id=focus)


def test_focus_client_list_is_only_the_selected_client(conn):
    # A2 shares joint account J with C2 and C3; with C3 selected, co-owner C2 must not appear.
    clients = focused(conn, A2, C3, "get_my_clients")["clients"]
    assert [c["client_id"] for c in clients] == [C3]
    assert clients[0]["accessible_market_value"] == 24000  # J + Z, both C3's


def test_focus_reviews_only_the_selected_client(conn):
    due = focused(conn, A2, C1, "find_reviews_due", within_days=365)["clients"]
    assert [c["client_id"] for c in due] == [C1]


@pytest.mark.parametrize("tool_name", ["get_accounts", "get_holdings", "get_performance"])
def test_focus_refuses_other_clients_by_id(conn, tool_name):
    result = focused(conn, A2, C3, tool_name, client_id=C2)  # C2 is A2's client, but not the selected one
    assert result["error"] == "outside selected client"


@pytest.mark.parametrize(
    "tool_name,extra",
    [("get_holdings", {}), ("get_performance", {}), ("get_transactions", {"start_date": "2000-01-01"})],
)
def test_focus_hides_other_clients_accounts(conn, tool_name, extra):
    # Y is C1's account, which A2 can normally see; with C3 selected it is out of reach.
    assert focused(conn, A2, C3, tool_name, account_id=Y, **extra) == NOT_FOUND
    # A1 with C1 selected cannot reach joint account J (C2 and C3's).
    assert focused(conn, A1, C1, tool_name, account_id=J, **extra) == NOT_FOUND


def test_focus_still_answers_about_the_selected_client(conn):
    h = focused(conn, A2, C3, "get_holdings", client_id=C3)
    assert [a["account_id"] for a in h["accounts"]] == [J, Z]
    assert focused(conn, A2, C3, "get_holdings", account_id=Z)["portfolio_market_value"] == 20000


def test_no_focus_is_unchanged(conn):
    clients = focused(conn, A2, None, "get_my_clients")["clients"]
    assert {c["client_id"] for c in clients} == {C1, C2, C3, C4}
