"""Invariants of the generated mock data. Pure Python: no database needed."""

from __future__ import annotations

import calendar
import hashlib
from collections import Counter, defaultdict
from datetime import date

import pytest

from wealth.datagen.generate import MAX_POSITIONS, MIN_POSITIONS, Dataset, generate
from wealth.datagen.securities import BY_SYMBOL, TECH

ANCHOR = date(2026, 11, 11)


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return generate(ANCHOR)


def _fingerprint(d: Dataset) -> str:
    h = hashlib.sha256()
    for part in (
        d.advisors,
        d.clients,
        d.accounts,
        d.access,
        d.holdings,
        d.transactions,
        d.performance,
        d.documents,
    ):
        h.update(repr(part).encode())
    return h.hexdigest()


def test_same_seed_and_anchor_give_identical_data(ds):
    assert _fingerprint(generate(ANCHOR)) == _fingerprint(ds)


def test_volumes(ds):
    assert len(ds.advisors) == 10
    assert len(ds.clients) == 200
    assert 320 <= len(ds.accounts) <= 380
    assert 55 <= len(ds.securities) <= 70
    docs = Counter(d[0] for d in ds.documents)
    assert all(1 <= docs[a["id"]] <= 3 for a in ds.accounts)


def test_joint_and_shared_advisor_rates(ds):
    n = len(ds.accounts)
    joint = sum(a["account_type"] == "joint" for a in ds.accounts)
    advisors_per_account = Counter(r["account_id"] for r in ds.access if r["person_type"] == "advisor")
    two_advisors = sum(v == 2 for v in advisors_per_account.values())
    assert 0.12 <= joint / n <= 0.18
    assert 0.06 <= two_advisors / n <= 0.14
    assert max(advisors_per_account.values()) <= 2


def test_every_account_has_owners_and_an_advisor(ds):
    by_account = defaultdict(list)
    for r in ds.access:
        by_account[r["account_id"]].append(r)
    for acct in ds.accounts:
        rows = by_account[acct["id"]]
        client_roles = sorted(r["role"] for r in rows if r["person_type"] == "client")
        assert any(r["person_type"] == "advisor" for r in rows), acct
        if acct["account_type"] == "joint":
            assert client_roles == ["joint_owner", "owner"], acct
        else:
            assert client_roles == ["owner"], acct


def test_acl_rows_are_well_formed_and_unique(ds):
    seen = set()
    for r in ds.access:
        if r["person_type"] == "advisor":
            assert (
                r["advisor_id"] is not None and r["client_id"] is None and r["role"] in ("advisor", "viewer")
            )
            key = ("a", r["account_id"], r["advisor_id"])
        else:
            assert r["client_id"] is not None and r["advisor_id"] is None
            assert r["role"] in ("owner", "joint_owner", "viewer")
            key = ("c", r["account_id"], r["client_id"])
        assert key not in seen, r
        seen.add(key)


def test_everyone_has_an_account(ds):
    clients_with = {r["client_id"] for r in ds.access if r["client_id"]}
    advisors_with = {r["advisor_id"] for r in ds.access if r["advisor_id"]}
    assert clients_with == {c["id"] for c in ds.clients}
    assert advisors_with == {a["id"] for a in ds.advisors}


def test_some_clients_are_split_across_advisors(ds):
    advisors_by_client = defaultdict(lambda: defaultdict(set))
    acct_advisors = defaultdict(set)
    for r in ds.access:
        if r["advisor_id"]:
            acct_advisors[r["account_id"]].add(r["advisor_id"])
    for r in ds.access:
        if r["client_id"]:
            for adv in acct_advisors[r["account_id"]]:
                advisors_by_client[r["client_id"]][adv].add(r["account_id"])
    client_accounts = Counter(r["client_id"] for r in ds.access if r["client_id"])
    split = [
        cid
        for cid, by_adv in advisors_by_client.items()
        if any(len(accts) < client_accounts[cid] for accts in by_adv.values())
    ]
    assert len(split) >= 5
    split_demo = [
        cid for cid, note in ds.demo["clients"].items() if note.startswith("Has accounts with two advisors")
    ][0]
    assert split_demo in split


def test_positions_per_snapshot_within_range(ds):
    counts = Counter((h[0], h[5]) for h in ds.holdings if h[1] != "CASH")
    assert counts and all(MIN_POSITIONS <= c <= MAX_POSITIONS for c in counts.values()), min(counts.values())
    assert all(h[2] > 0 and h[3] >= 0 and h[4] > 0 for h in ds.holdings)


def test_every_account_has_a_latest_snapshot(ds):
    latest = {h[0] for h in ds.holdings if h[5] == ANCHOR}
    assert latest == {a["id"] for a in ds.accounts}


def test_holdings_equal_replayed_transactions(ds):
    """Quantity, cash, and average-cost basis in the latest snapshot match the transaction history."""
    qty = defaultdict(float)
    cost = defaultdict(float)
    cash = defaultdict(float)
    for acct, d, kind, sym, q, _price, amount, realized in ds.transactions:
        assert d <= ANCHOR
        if kind == "buy":
            qty[acct, sym] += q
            cost[acct, sym] += amount
            cash[acct] -= amount
        elif kind == "sell":
            qty[acct, sym] -= q
            cost[acct, sym] -= amount - realized  # cost removed = proceeds - realized gain
            cash[acct] += amount
        elif kind in ("deposit", "dividend"):
            cash[acct] += amount
        else:
            cash[acct] -= amount

    snap = {(h[0], h[1]): h for h in ds.holdings if h[5] == ANCHOR}
    for (acct, sym), q in qty.items():
        assert q >= 0, (acct, sym)
        if q == 0:
            assert (acct, sym) not in snap
            continue
        h = snap[acct, sym]
        assert h[2] == q, (acct, sym)
        assert abs(h[3] - cost[acct, sym]) < 0.05, (acct, sym, h[3], cost[acct, sym])
    for acct, c in cash.items():
        snap_cash = snap[acct, "CASH"][2] if (acct, "CASH") in snap else 0.0
        assert c > -0.01 and abs(snap_cash - c) < 0.01, (acct, snap_cash, c)


def test_transactions_cover_about_two_years(ds):
    dates = [t[1] for t in ds.transactions]
    span = (max(dates) - min(dates)).days
    assert 700 <= span <= 750


def test_performance_rows_and_nulls(ds):
    per_account = Counter(p[0] for p in ds.performance)
    assert max(per_account.values()) == 24
    open_dates = {a["id"]: a["open_date"] for a in ds.accounts}
    for row in ds.performance:
        acct, as_of, *returns = row
        assert returns[0] is not None and returns[1] is not None or (as_of - open_dates[acct]).days < 40
        assert all(r is None or -0.95 < r < 20 for r in returns), row
        if (as_of - open_dates[acct]).days < 5 * 365:
            assert returns[-1] is None, row  # 5Y needs 5 years of history
    with_5y = sum(1 for p in ds.performance if p[1] == ANCHOR and p[-1] is not None)
    assert with_5y > 50


def test_review_dates_spread(ds):
    reviews = [c["next_review_date"] for c in ds.clients]
    assert all(-30 <= (r - ANCHOR).days <= 90 for r in reviews)
    overdue = sum(r < ANCHOR for r in reviews) / len(reviews)
    assert 0.04 <= overdue <= 0.20


def _tech_weight(ds: Dataset, client_id: int) -> float:
    accounts = {r["account_id"] for r in ds.access if r["client_id"] == client_id}
    mv = tech = 0.0
    for acct, sym, q, _c, price, d in ds.holdings:
        if acct in accounts and d == ANCHOR:
            mv += q * price
            if BY_SYMBOL[sym].sector == TECH:
                tech += q * price
    return tech / mv


def test_tech_overweight_clients_have_reviews_this_month(ds):
    month_end = date(ANCHOR.year, ANCHOR.month, calendar.monthrange(ANCHOR.year, ANCHOR.month)[1])
    clients = {c["id"]: c for c in ds.clients}
    flagged = ds.demo["tech_overweight_client_ids"]
    assert len(flagged) >= 6
    for cid in flagged:
        assert ANCHOR <= clients[cid]["next_review_date"] <= month_end
        assert _tech_weight(ds, cid) > 0.40, cid


def test_typical_client_is_not_tech_heavy(ds):
    flagged = set(ds.demo["tech_overweight_client_ids"])
    weights = sorted(_tech_weight(ds, c["id"]) for c in ds.clients if c["id"] not in flagged)
    assert weights[len(weights) // 2] < 0.30  # median
