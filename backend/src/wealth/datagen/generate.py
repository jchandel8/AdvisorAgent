"""Deterministic mock-data generator. Pure: returns a Dataset and never touches the database.

How the numbers stay consistent:
- Every account is SIMULATED: an opening deposit, initial buys, then about 2 years of monthly events
  (dividends, deposits, withdrawals, buys, sells) priced from the seeded PriceBook.
- Holdings snapshots are the simulated positions on each as-of date, so they always equal the
  replayed transactions. cost_basis uses the average-cost method; sells record realized gain.
- Performance is time-weighted: each period's return is the buy-and-hold return of the positions held
  at the start of the period (so deposits and withdrawals don't count as gains), chained across periods.
  Before an account's transaction history starts, its initial portfolio is "back-cast" over the price
  history so 3Y/5Y returns exist for older accounts. Periods before open_date are NULL.

Dates are relative to the anchor date (DATA_ANCHOR_DATE, default today). Same seed + same anchor = same data.
"""

from __future__ import annotations

import calendar
import math
import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from faker import Faker

from wealth.datagen.prices import HISTORY_MONTHS, PriceBook, months_before
from wealth.datagen.securities import BY_SYMBOL, EQUITIES, FIXED_INCOME, SECURITIES, TECH, Security

SEED = 42
N_ADVISORS = 10
N_COUPLES = 52  # each couple shares one joint account -> ~15% of accounts are joint
N_SINGLES = 96  # 2 * 52 + 96 = 200 clients
SNAPSHOT_MONTHS = 24  # holdings snapshots / performance rows: anchor and the 23 months before it
SECOND_ADVISOR_RATE = 0.10
SPLIT_RATE = 0.15  # single clients with an account moved to a different advisor
TECH_FLAGGED_PER_DEMO_ADVISOR = 3
MIN_POSITIONS, MAX_POSITIONS = 10, 30

ALLOCATIONS = {
    "conservative": {"equity": 0.35, "fixed_income": 0.55, "cash": 0.10},
    "moderate": {"equity": 0.60, "fixed_income": 0.35, "cash": 0.05},
    "growth": {"equity": 0.75, "fixed_income": 0.20, "cash": 0.05},
    "aggressive": {"equity": 0.90, "fixed_income": 0.07, "cash": 0.03},
}
FI_COUNT = {"conservative": (3, 4), "moderate": (2, 3), "growth": (1, 2), "aggressive": (1, 1)}
CERTIFICATIONS = ["CFP", "CFA", "ChFC", "CPA", "CIMA", "CPWA"]
EVENT_ORDER = {"deposit": 0, "dividend": 1, "sell": 2, "buy": 3, "withdrawal": 4}


@dataclass
class Dataset:
    anchor: date
    advisors: list[dict]
    clients: list[dict]
    accounts: list[dict]
    access: list[dict]  # account_id, person_type, advisor_id, client_id, role
    securities: list[Security]
    holdings: list[tuple]  # account_id, symbol, quantity, cost_basis, price, as_of_date
    transactions: list[tuple]  # account_id, trade_date, type, symbol, quantity, price, amount, realized_gain
    performance: list[tuple]  # account_id, as_of_date, return_1d .. return_5y
    documents: list[tuple]  # account_id, title, doc_type, text, size_kb, created_date
    demo: dict = field(default_factory=dict)
    admins: list[dict] = field(default_factory=list)


@dataclass
class Household:
    advisor_id: int
    client_ids: list[int]
    risk_profile: str
    tech_flagged: bool = False
    account_ids: list[int] = field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------------------------------


class _Usernames:
    def __init__(self):
        self.taken: set[str] = set()

    def make(self, first: str, last: str) -> str:
        base = re.sub(r"[^a-z]", "", first.lower()) + "." + re.sub(r"[^a-z]", "", last.lower())
        name, n = base, 1
        while name in self.taken:
            n += 1
            name = f"{base}{n}"
        self.taken.add(name)
        return name


def _make_advisors(fake: Faker, rng: random.Random, names: _Usernames) -> list[dict]:
    advisors = []
    for i in range(1, N_ADVISORS + 1):
        first, last = fake.first_name(), fake.last_name()
        username = names.make(first, last)
        advisors.append(
            {
                "id": i,
                "username": username,
                "first_name": first,
                "last_name": last,
                "email": f"{username}@example.com",
                "phone": fake.numerify("###-###-####"),
                "certifications": sorted(rng.sample(CERTIFICATIONS, rng.randint(1, 2))),
                "city": fake.city(),
                "state": fake.state_abbr(include_territories=False),
            }
        )
    return advisors


def _review_date(rng: random.Random, anchor: date) -> date:
    if rng.random() < 0.10:
        return anchor - timedelta(days=rng.randint(1, 30))  # overdue
    return anchor + timedelta(days=rng.randint(0, 90))


def _review_this_month(rng: random.Random, anchor: date) -> date:
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    return anchor + timedelta(days=rng.randint(0, last_day - anchor.day))


def _make_clients(fake, rng, names, anchor) -> tuple[list[dict], list[Household]]:
    # Uneven advisor books so client counts vary (the CSV shows a range).
    advisor_weights = [14, 12, 11, 10, 9, 8, 7, 6, 5, 4]
    kinds = ["couple"] * N_COUPLES + ["single"] * N_SINGLES
    rng.shuffle(kinds)

    clients: list[dict] = []
    households: list[Household] = []
    for kind in kinds:
        advisor_id = rng.choices(range(1, N_ADVISORS + 1), weights=advisor_weights)[0]
        risk = rng.choices(list(ALLOCATIONS), weights=[20, 40, 28, 12])[0]
        last = fake.last_name()
        street, city, state = fake.street_address(), fake.city(), fake.state_abbr(include_territories=False)
        review = _review_date(rng, anchor)
        members = []
        for _ in range(2 if kind == "couple" else 1):
            first = fake.first_name()
            cid = len(clients) + 1
            username = names.make(first, last)
            clients.append(
                {
                    "id": cid,
                    "username": username,
                    "first_name": first,
                    "last_name": last,
                    "email": f"{username}@example.com",
                    "phone": fake.numerify("###-###-####"),
                    "address": street,
                    "city": city,
                    "state": state,
                    "risk_profile": risk,
                    "target_allocation": ALLOCATIONS[risk],
                    "next_review_date": review,
                }
            )
            members.append(cid)
        households.append(Household(advisor_id=advisor_id, client_ids=members, risk_profile=risk))
    return clients, households


# --------------------------------------------------------------------------------------------------
# Accounts and ACL
# --------------------------------------------------------------------------------------------------


def _open_date(rng: random.Random, history_start: date, anchor: date) -> date:
    if rng.random() < 0.85:  # opened before the 2-year transaction window
        return history_start - timedelta(days=rng.randint(30, 10 * 365))
    latest = anchor - timedelta(days=120)
    return history_start + timedelta(days=rng.randint(0, (latest - history_start).days))


def _make_accounts(rng, households, clients_by_id, history_start, anchor):
    accounts: list[dict] = []
    access: list[dict] = []

    names_by_owner: dict[int, set[str]] = {}

    def add_account(hh: Household, kind: str, owners: list[int]) -> int:
        aid = len(accounts) + 1
        c0 = clients_by_id[owners[0]]
        if kind == "joint":
            name, desc = f"{c0['last_name']} Joint Brokerage", "Joint taxable brokerage account"
        elif kind == "ira":
            flavor = rng.choice(["Traditional IRA", "Roth IRA", "Rollover IRA"])
            name, desc = f"{c0['first_name']} {c0['last_name']} {flavor}", f"{flavor} retirement account"
        elif kind == "trust":
            name, desc = f"{c0['last_name']} Family Trust", "Revocable living trust account"
        else:
            name, desc = (
                f"{c0['first_name']} {c0['last_name']} Individual",
                "Individual taxable brokerage account",
            )
        # A client with two accounts of the same kind gets "... 2" so names stay distinguishable.
        seen = names_by_owner.setdefault(owners[0], set())
        base, n = name, 1
        while name in seen:
            n += 1
            name = f"{base} {n}"
        seen.add(name)
        accounts.append(
            {
                "id": aid,
                "account_name": name,
                "account_type": kind,
                "description": desc,
                "open_date": _open_date(rng, history_start, anchor),
                "close_date": None,
            }
        )
        for i, cid in enumerate(owners):
            role = "owner" if i == 0 else "joint_owner"
            access.append(
                {
                    "account_id": aid,
                    "person_type": "client",
                    "advisor_id": None,
                    "client_id": cid,
                    "role": role,
                }
            )
        access.append(
            {
                "account_id": aid,
                "person_type": "advisor",
                "advisor_id": hh.advisor_id,
                "client_id": None,
                "role": "advisor",
            }
        )
        hh.account_ids.append(aid)
        return aid

    for hh in households:
        if len(hh.client_ids) == 2:
            add_account(hh, "joint", hh.client_ids)
            for cid in hh.client_ids:
                if rng.random() < 0.80:
                    add_account(hh, "ira", [cid])
                if rng.random() < 0.20:
                    add_account(hh, "individual", [cid])
        else:
            cid = hh.client_ids[0]
            add_account(hh, "individual", [cid])
            if rng.random() < 0.60:
                add_account(hh, "ira", [cid])
            if rng.random() < 0.25:
                add_account(hh, "trust", [cid])
            if rng.random() < 0.15:
                add_account(hh, "individual", [cid])
    return accounts, access


def _advisor_rows(access: list[dict], account_id: int) -> list[dict]:
    return [r for r in access if r["account_id"] == account_id and r["person_type"] == "advisor"]


def _other_advisor(rng: random.Random, exclude: set[int]) -> int:
    return rng.choice([a for a in range(1, N_ADVISORS + 1) if a not in exclude])


def _split_account(rng, access, hh: Household) -> int:
    """Move one of a single client's accounts (not the first) away from the client's primary advisor."""
    moved = hh.account_ids[-1]
    rows = _advisor_rows(access, moved)
    current = {r["advisor_id"] for r in rows}
    primary_row = next(r for r in rows if r["advisor_id"] == hh.advisor_id)
    if len(rows) > 1:
        access.remove(primary_row)  # another advisor already covers this account
    else:
        primary_row["advisor_id"] = _other_advisor(rng, current)
    return moved


# --------------------------------------------------------------------------------------------------
# Account simulation
# --------------------------------------------------------------------------------------------------


@dataclass
class _Pos:
    qty: int
    cost: float


class _Sim:
    def __init__(self, account_id: int, prices: PriceBook, rng: random.Random):
        self.account_id = account_id
        self.prices = prices
        self.rng = rng
        self.cash = 0.0
        self.pos: dict[str, _Pos] = {}
        self.txns: list[tuple] = []

    def value(self, d: date) -> float:
        return self.cash + sum(p.qty * self.prices.price(s, d) for s, p in self.pos.items())

    def deposit(self, d: date, amount: float) -> None:
        amount = round(amount, 2)
        self.cash = round(self.cash + amount, 2)
        self.txns.append((self.account_id, d, "deposit", None, None, None, amount, None))

    def withdraw(self, d: date, amount: float) -> None:
        amount = round(min(amount, self.cash), 2)
        if amount < 100:
            return
        self.cash = round(self.cash - amount, 2)
        self.txns.append((self.account_id, d, "withdrawal", None, None, None, amount, None))

    def buy(self, d: date, symbol: str, dollars: float) -> bool:
        price = self.prices.price(symbol, d)
        shares = int(min(dollars, self.cash) // price)
        if shares < 1:
            return False
        amount = round(shares * price, 2)
        if amount > self.cash:
            return False
        self.cash = round(self.cash - amount, 2)
        p = self.pos.setdefault(symbol, _Pos(0, 0.0))
        p.qty += shares
        p.cost = round(p.cost + amount, 2)
        self.txns.append((self.account_id, d, "buy", symbol, shares, price, amount, None))
        return True

    def sell(self, d: date, symbol: str, shares: int) -> None:
        p = self.pos[symbol]
        shares = min(shares, p.qty)
        if shares < 1:
            return
        price = self.prices.price(symbol, d)
        amount = round(shares * price, 2)
        cost_removed = p.cost if shares == p.qty else round(p.cost * shares / p.qty, 2)  # average cost
        realized = round(amount - cost_removed, 2)
        p.qty -= shares
        p.cost = round(p.cost - cost_removed, 2)
        if p.qty == 0:
            del self.pos[symbol]
        self.cash = round(self.cash + amount, 2)
        self.txns.append((self.account_id, d, "sell", symbol, shares, price, amount, realized))

    def pay_dividends(self, d: date) -> None:
        for symbol, p in list(self.pos.items()):
            y = BY_SYMBOL[symbol].dividend_yield
            amount = round(p.qty * self.prices.price(symbol, d) * y / 4, 2)
            if amount >= 0.01:
                self.cash = round(self.cash + amount, 2)
                self.txns.append((self.account_id, d, "dividend", symbol, None, None, amount, None))

    def state(self) -> tuple[dict[str, tuple[int, float]], float]:
        return {s: (p.qty, p.cost) for s, p in self.pos.items()}, self.cash


def _weighted_sample(
    rng: random.Random, items: list[Security], weights: list[float], k: int
) -> list[Security]:
    items, weights, chosen = list(items), list(weights), []
    for _ in range(min(k, len(items))):
        i = rng.choices(range(len(items)), weights=weights)[0]
        chosen.append(items.pop(i))
        weights.pop(i)
    return chosen


def _equity_weight(sec: Security, tech_flagged: bool) -> float:
    return 5.0 if (tech_flagged and sec.sector == TECH) else 1.0


def _pick_new_security(rng, sim: _Sim, alloc: dict, tech_flagged: bool) -> Security | None:
    asset_class = rng.choices(["equity", "fixed_income"], weights=[alloc["equity"], alloc["fixed_income"]])[0]
    pool = [s for s in (EQUITIES if asset_class == "equity" else FIXED_INCOME) if s.symbol not in sim.pos]
    if not pool:
        return None
    return _weighted_sample(rng, pool, [_equity_weight(s, tech_flagged) for s in pool], 1)[0]


def _initial_portfolio(rng, sim: _Sim, d: date, deposit: float, hh: Household) -> None:
    alloc = ALLOCATIONS[hh.risk_profile]
    sim.deposit(d, deposit)
    lo, hi = FI_COUNT[hh.risk_profile]
    fi = rng.sample(FIXED_INCOME, rng.randint(lo, hi))
    eq_budget = deposit * alloc["equity"]
    max_eq = max(MIN_POSITIONS - len(fi), min(MAX_POSITIONS - len(fi), int(eq_budget // 2500)))
    n_eq = min(max_eq, max(MIN_POSITIONS - len(fi), rng.randint(9, 26)))
    eq = _weighted_sample(rng, EQUITIES, [_equity_weight(s, hh.tech_flagged) for s in EQUITIES], n_eq)

    for group, budget in ((eq, eq_budget), (fi, deposit * alloc["fixed_income"])):
        tilt = [rng.uniform(0.5, 1.5) * (3.0 if hh.tech_flagged and s.sector == TECH else 1.0) for s in group]
        total = sum(tilt)
        for sec, w in zip(group, tilt, strict=True):
            sim.buy(d, sec.symbol, budget * w / total)

    # Guarantee the minimum number of positions (whole shares can round a small slice to zero).
    for sec in sorted(FIXED_INCOME + EQUITIES, key=lambda s: sim.prices.price(s.symbol, d)):
        if len(sim.pos) >= MIN_POSITIONS:
            break
        if sec.symbol not in sim.pos:
            sim.buy(d, sec.symbol, sim.prices.price(sec.symbol, d) * 2)


def _events(rng: random.Random, sim_start: date, anchor: date) -> list[tuple[date, str]]:
    events: list[tuple[date, str]] = []
    for k in range(SNAPSHOT_MONTHS, 0, -1):
        a, b = months_before(anchor, k), months_before(anchor, k - 1)
        lo = max(a, sim_start)
        if b <= lo:
            continue

        def day() -> date:
            return lo + timedelta(days=rng.randint(1, (b - lo).days))  # noqa: B023 (lo/b are per-iteration)

        if b.month in (3, 6, 9, 12):
            events.append((b, "dividend"))
        if rng.random() < 0.12:
            events.append((day(), "deposit"))
        if rng.random() < 0.06:
            events.append((day(), "withdrawal"))
        if rng.random() < 0.30:
            events.append((day(), "sell"))
        if rng.random() < 0.45:
            events.append((day(), "buy"))
    events.sort(key=lambda e: (e[0], EVENT_ORDER[e[1]]))
    return events


def _apply_event(rng, sim: _Sim, d: date, kind: str, hh: Household) -> None:
    alloc = ALLOCATIONS[hh.risk_profile]
    if kind == "dividend":
        sim.pay_dividends(d)
    elif kind == "deposit":
        sim.deposit(d, max(1000.0, round(sim.value(d) * rng.uniform(0.01, 0.08), -2)))
    elif kind == "withdrawal":
        sim.withdraw(d, round(sim.value(d) * rng.uniform(0.01, 0.04), -2))
    elif kind == "sell":
        held = sorted(sim.pos)
        if not held:
            return
        symbol = rng.choice(held)
        qty = sim.pos[symbol].qty
        shares = max(1, int(qty * rng.uniform(0.2, 1.0)))
        if shares >= qty and len(sim.pos) <= MIN_POSITIONS:
            shares = qty // 2  # keep at least MIN_POSITIONS positions
        sim.sell(d, symbol, shares)
    elif kind == "buy":
        excess = sim.cash - alloc["cash"] * sim.value(d)
        if excess < 2000:
            return
        spend = excess * rng.uniform(0.5, 0.9)
        target: Security | None = None
        if len(sim.pos) < MAX_POSITIONS and rng.random() < 0.35:
            target = _pick_new_security(rng, sim, alloc, hh.tech_flagged)
        if target is None:
            held = [BY_SYMBOL[s] for s in sorted(sim.pos)]
            target = _weighted_sample(rng, held, [_equity_weight(s, hh.tech_flagged) for s in held], 1)[0]
        sim.buy(d, target.symbol, spend)


def _period_return(prices, held, a: date, b: date, dividends: float) -> float | None:
    if held is None:
        return None
    positions, cash = held
    va = cash + sum(q * prices.price(s, a) for s, (q, _) in positions.items())
    vb = cash + sum(q * prices.price(s, b) for s, (q, _) in positions.items())
    if va <= 0:
        return None
    return (vb + dividends) / va - 1


def _simulate_account(rng, prices: PriceBook, acct: dict, hh: Household, history_start: date, anchor: date):
    sim = _Sim(acct["id"], prices, rng)
    open_date: date = acct["open_date"]
    sim_start = max(open_date, history_start)

    base = math.exp(rng.gauss(math.log(300_000), 0.8))
    if acct["account_type"] == "trust":
        base *= 2
    elif acct["account_type"] == "ira":
        base *= 0.6
    deposit = round(min(max(base, 80_000), 4_000_000), -2)
    _initial_portfolio(rng, sim, sim_start, deposit, hh)
    initial_state = sim.state()

    snapshot_dates = [months_before(anchor, k) for k in range(SNAPSHOT_MONTHS - 1, -1, -1)]
    grid = [months_before(anchor, k) for k in range(HISTORY_MONTHS, -1, -1)]
    year_ends = [
        date(y, 12, 31) for y in range(grid[0].year, anchor.year) if grid[0] <= date(y, 12, 31) < anchor
    ]
    eval_points = sorted(set(grid) | set(year_ends))
    checkpoints = [d for d in eval_points if d >= sim_start]

    recorded: dict[date, tuple] = {}
    events = _events(rng, sim_start, anchor)
    ei = 0
    for cp in checkpoints:
        while ei < len(events) and events[ei][0] <= cp:
            _apply_event(rng, sim, events[ei][0], events[ei][1], hh)
            ei += 1
        recorded[cp] = sim.state()

    holdings = []
    for d in snapshot_dates:
        if d not in recorded:
            continue
        positions, cash = recorded[d]
        for symbol, (qty, cost) in positions.items():
            holdings.append((acct["id"], symbol, qty, round(cost, 2), prices.price(symbol, d), d))
        if cash >= 0.01:
            holdings.append((acct["id"], "CASH", round(cash, 2), round(cash, 2), 1.0, d))

    def held_at(d: date):
        if d >= sim_start:
            return recorded[d]
        if d >= open_date:
            return initial_state  # back-cast: the opening portfolio held through earlier history
        return None

    dividends_by_date: dict[date, float] = {}
    for t in sim.txns:
        if t[2] == "dividend":
            dividends_by_date[t[1]] = dividends_by_date.get(t[1], 0.0) + t[6]

    period: dict[date, float | None] = {}  # return for (previous eval point, this eval point]
    for a, b in zip(eval_points, eval_points[1:], strict=False):
        divs = sum(v for d, v in dividends_by_date.items() if a < d <= b) if a >= sim_start else 0.0
        period[b] = _period_return(prices, held_at(a), a, b, divs)

    def chain(start: date, end: date) -> float | None:
        if held_at(start) is None:
            return None
        total = 1.0
        for p in eval_points:
            if start < p <= end:
                r = period[p]
                if r is None:
                    return None
                total *= 1 + r
        return round(total - 1, 6)

    performance = []
    for k in range(SNAPSHOT_MONTHS - 1, -1, -1):
        t = months_before(anchor, k)
        if t not in recorded:
            continue
        positions, cash = recorded[t]
        v_now = cash + sum(q * prices.price(s, t) for s, (q, _) in positions.items())
        v_prev = cash + sum(q * prices.prev_day_price(s, t) for s, (q, _) in positions.items())
        r1d = round(v_now / v_prev - 1, 6) if v_prev > 0 else None
        ytd_start = date(t.year - 1, 12, 31)
        performance.append(
            (
                acct["id"],
                t,
                r1d,
                chain(months_before(anchor, k + 1), t),
                chain(months_before(anchor, k + 3), t),
                chain(months_before(anchor, k + 6), t),
                chain(ytd_start, t) if ytd_start in eval_points else None,
                chain(months_before(anchor, k + 12), t),
                chain(months_before(anchor, k + 24), t),
                chain(months_before(anchor, k + 36), t),
                chain(months_before(anchor, k + 60), t),
            )
        )

    values_by_date = {
        d: round(st[1] + sum(q * prices.price(s, d) for s, (q, _) in st[0].items()), 2)
        for d, st in recorded.items()
        if d in snapshot_dates
    }
    return holdings, sim.txns, performance, sim_start, values_by_date


# --------------------------------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------------------------------


OBJECTIVES = {
    "conservative": "preserve capital and produce steady income, accepting lower long-term growth",
    "moderate": "balance long-term growth with income and moderate year-to-year swings",
    "growth": "grow the portfolio over the long term while keeping some income and stability",
    "aggressive": "maximize long-term growth and accept large short-term swings in value",
}
CONSTRAINTS = [
    "No single stock may exceed 10% of the account.",
    "Avoid tobacco and firearms companies.",
    "Prefer municipal bonds in taxable accounts for tax efficiency.",
    "Keep at least six months of planned withdrawals in cash.",
    "No leverage, options or private placements.",
    "Coordinate trades with the client's other accounts to avoid wash sales.",
]
CHILDREN = ["Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Mia", "Lucas", "Sofia", "Mason"]
EXPENSES = [
    "a home renovation",
    "a daughter's wedding",
    "a new car",
    "a second home down payment",
    "a long trip abroad",
]


def _documents(fake, rng, acct, owners: list[dict], hh: Household, sim_start, anchor, values_by_date):
    """1 to 3 documents per account with realistic text built from the account's own facts.

    The main `rng` draws below are unchanged from earlier versions (kinds, dates, fee, size), so changing the
    wording never shifts the portfolio simulation. All wording choices use a separate, per-account generator.
    """
    names = " and ".join(f"{c['first_name']} {c['last_name']}" for c in owners)
    first = owners[0]["first_name"]
    alloc = ALLOCATIONS[hh.risk_profile]
    words = random.Random(f"documents:{acct['id']}")  # wording only; deterministic per account
    kinds = rng.sample(["ips", "review_notes", "statement", "agreement"], rng.randint(1, 3))
    docs = []
    for kind in kinds:
        created = sim_start + timedelta(days=rng.randint(0, max(0, (anchor - sim_start).days)))
        if kind == "ips":
            title = f"Investment Policy Statement - {acct['account_name']}"
            text = _ips(words, acct, names, hh.risk_profile, alloc, created)
        elif kind == "review_notes":
            title = f"Review notes {created.isoformat()} - {acct['account_name']}"
            text = _review_notes(words, acct, names, first, hh, alloc, created, values_by_date)
        elif kind == "statement":
            as_of = max((d for d in values_by_date if d <= created), default=None) or min(values_by_date)
            title = f"Statement {as_of.isoformat()} - {acct['account_name']}"
            text = _statement(acct, names, as_of, values_by_date)
        else:
            title = f"Advisory agreement - {acct['account_name']}"
            fee = rng.choice(["0.75%", "1.00%", "1.25%"])
            text = _agreement(words, acct, names, fee, created)
        docs.append((acct["id"], title, kind, text, rng.randint(40, 900), created))
    return docs


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _ips(words, acct, names, risk, alloc, created) -> str:
    horizon = words.choice(["more than 10 years", "7 to 10 years", "at least 15 years", "5 to 7 years"])
    liquidity = words.choice(
        [
            "No regular withdrawals are planned.",
            f"Planned withdrawals of about ${words.randrange(2, 9) * 1000:,} a month starting in {created.year + 2}.",
            "An annual withdrawal for charitable giving each December.",
        ]
    )
    rules = " ".join(words.sample(CONSTRAINTS, 2))
    extra = {
        "ira": "As an IRA, the account must meet required minimum distribution rules once they apply.",
        "trust": "The trustee directs this account under the trust agreement; distributions follow its terms.",
        "joint": "Both joint owners approved this statement; either may request changes.",
    }.get(acct["account_type"], "")
    return (
        f"Investment Policy Statement for {names}, account {acct['account_name']}, adopted {created.isoformat()}. "
        f"Risk profile: {risk}. Objective: {OBJECTIVES[risk]}. Time horizon: {horizon}. "
        f"Target allocation: equity {_pct(alloc['equity'])}, fixed income {_pct(alloc['fixed_income'])}, "
        f"cash {_pct(alloc['cash'])}. Rebalancing: review quarterly and rebalance when any asset class drifts more "
        f"than 5 percentage points from target. Liquidity: {liquidity} Constraints: {rules} {extra} "
        f"This statement is reviewed at least once a year or after a major life event."
    ).replace("  ", " ")


def _review_notes(words, acct, names, first, hh, alloc, created, values_by_date) -> str:
    topics = []
    if hh.tech_flagged:
        topics.append(
            "Client asked about the portfolio's concentration in technology stocks; discussed trimming tech "
            "exposure toward the target allocation."
        )
    pool = [
        f"Discussed college savings for their child {words.choice(CHILDREN)}, who starts college in "
        f"{created.year + words.randrange(2, 12)}; reviewed 529 plan contributions of "
        f"${words.randrange(2, 11) * 100:,} a month.",
        f"{first} plans to retire in {created.year + words.randrange(3, 16)}; reviewed retirement income needs "
        f"of about ${words.randrange(6, 19) * 10_000:,} a year.",
        f"Confirmed beneficiary designations. Client will send an updated beneficiary form after "
        f"{words.choice(['a recent marriage', 'the birth of a grandchild', 'updating their will'])}.",
        f"Reviewed allocation against the target of {_pct(alloc['equity'])} equity; agreed to look at "
        f"rebalancing at the next quarterly review.",
        "Reviewed positions with unrealized losses for possible tax-loss harvesting before year end.",
        f"Client expects {words.choice(EXPENSES)} costing about ${words.randrange(3, 16) * 10_000:,} in "
        f"{created.year + 1}; discussed raising cash ahead of it.",
        "Client was worried about market volatility; reviewed the long-term plan and the cash reserve.",
        "Discussed charitable giving, including donating appreciated shares instead of cash.",
    ]
    if acct["account_type"] == "ira":
        pool.append("Reviewed the required minimum distribution schedule and tax withholding.")
    if acct["account_type"] == "trust":
        pool.append("Trustee asked for a summary of distributions made this year.")
    topics += words.sample(pool, 2 if topics else words.randint(2, 3))
    action = words.choice(
        [
            "Advisor to send a rebalancing proposal.",
            "Client to send updated income details.",
            "Advisor to prepare a retirement income projection.",
            "Schedule a follow-up call in six weeks.",
        ]
    )
    return (
        f"Review meeting with {names} on {created.isoformat()} about {acct['account_name']}. "
        + " ".join(topics)
        + f" Action items: {action}"
    )


def _statement(acct, names, as_of, values_by_date) -> str:
    value = values_by_date[as_of]
    earlier = [d for d in values_by_date if d < as_of]
    change = ""
    if earlier:
        prev = values_by_date[max(earlier)]
        diff = value - prev
        change = (
            f" Change since {max(earlier).isoformat()}: {'+' if diff >= 0 else '-'}${abs(diff):,.2f} "
            f"({diff / prev:+.1%}), including deposits, withdrawals and market movement."
            if prev
            else ""
        )
    return (
        f"Account statement for {acct['account_name']} ({names}). Market value as of {as_of.isoformat()}: "
        f"${value:,.2f}.{change} Positions are valued at closing prices on the statement date. Dividends are "
        f"reinvested in cash unless the client instructs otherwise."
    )


def _agreement(words, acct, names, fee, created) -> str:
    authority = words.choice(["discretionary", "non-discretionary"])
    authority_text = (
        "The advisor may buy and sell securities without asking before each trade, within the investment policy."
        if authority == "discretionary"
        else "The advisor recommends trades and the client approves each one before it is placed."
    )
    return (
        f"Advisory agreement between the firm and {names} for {acct['account_name']}, signed {created.isoformat()}. "
        f"Annual advisory fee: {fee} of assets under management, billed quarterly in arrears. "
        f"Authority: {authority}. {authority_text} Either party may end this agreement with 30 days' written "
        f"notice. The client receives quarterly statements and an annual review."
    )


# --------------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------------


def generate(anchor: date, seed: int = SEED) -> Dataset:
    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)

    prices = PriceBook(anchor, rng, seed)
    history_start = months_before(anchor, SNAPSHOT_MONTHS) + timedelta(days=1)

    names = _Usernames()
    advisors = _make_advisors(fake, rng, names)
    clients, households = _make_clients(fake, rng, names, anchor)
    clients_by_id = {c["id"]: c for c in clients}

    # Demo advisors: the two with the most clients. Give each a few tech-heavy clients due this month.
    clients_per_advisor = {a["id"]: 0 for a in advisors}
    for hh in households:
        clients_per_advisor[hh.advisor_id] += len(hh.client_ids)
    demo_advisors = sorted(clients_per_advisor, key=lambda a: (-clients_per_advisor[a], a))[:2]

    tech_clients: list[int] = []
    for adv in demo_advisors:
        candidates = [hh for hh in households if hh.advisor_id == adv]
        for hh in rng.sample(candidates, TECH_FLAGGED_PER_DEMO_ADVISOR):
            hh.tech_flagged = True
            hh.risk_profile = rng.choice(["growth", "aggressive"])
            review = _review_this_month(rng, anchor)
            for cid in hh.client_ids:
                clients_by_id[cid]["risk_profile"] = hh.risk_profile
                clients_by_id[cid]["target_allocation"] = ALLOCATIONS[hh.risk_profile]
                clients_by_id[cid]["next_review_date"] = review
                tech_clients.append(cid)

    accounts, access = _make_accounts(rng, households, clients_by_id, history_start, anchor)

    # Second advisors on ~10% of accounts.
    for acct in accounts:
        if rng.random() < SECOND_ADVISOR_RATE:
            current = {r["advisor_id"] for r in _advisor_rows(access, acct["id"])}
            access.append(
                {
                    "account_id": acct["id"],
                    "person_type": "advisor",
                    "advisor_id": _other_advisor(rng, current),
                    "client_id": None,
                    "role": "advisor",
                }
            )

    # Split clients: one of their accounts is handled by a different advisor only.
    singles_multi = [hh for hh in households if len(hh.client_ids) == 1 and len(hh.account_ids) >= 2]
    demo_split = next(
        (
            hh
            for hh in singles_multi
            if hh.advisor_id == demo_advisors[0]
            and not hh.tech_flagged
            and all(len(_advisor_rows(access, a)) == 1 for a in hh.account_ids)
        ),
        None,
    )
    if demo_split is None:
        raise RuntimeError("no split-client candidate for the demo advisor; change the seed")
    _split_account(rng, access, demo_split)
    for hh in singles_multi:
        if hh is not demo_split and rng.random() < SPLIT_RATE:
            _split_account(rng, access, hh)

    # Simulate every account.
    holdings, transactions, performance, documents = [], [], [], []
    acct_by_id = {a["id"]: a for a in accounts}
    owners_by_account: dict[int, list[dict]] = {}
    for r in access:
        if r["person_type"] == "client":
            owners_by_account.setdefault(r["account_id"], []).append(clients_by_id[r["client_id"]])
    for hh in households:
        for aid in hh.account_ids:
            acct = acct_by_id[aid]
            h, t, p, sim_start, values = _simulate_account(rng, prices, acct, hh, history_start, anchor)
            holdings += h
            transactions += t
            performance += p
            documents += _documents(fake, rng, acct, owners_by_account[aid], hh, sim_start, anchor, values)

    transactions.sort(key=lambda t: (t[0], t[1], EVENT_ORDER[t[2]]))

    joint_hh = next(
        hh
        for hh in households
        if hh.advisor_id == demo_advisors[0] and len(hh.client_ids) == 2 and not hh.tech_flagged
    )
    tech_demo = next(
        c
        for c in tech_clients
        if any(hh.advisor_id == demo_advisors[1] and c in hh.client_ids for hh in households)
    )
    names = {c["id"]: f"{c['first_name']} {c['last_name']}" for c in clients}
    advisor_names = {a["id"]: f"{a['first_name']} {a['last_name']}" for a in advisors}
    spouse = joint_hh.client_ids[1]
    demo = {
        "advisor_ids": demo_advisors,
        "tech_overweight_client_ids": tech_clients,
        "clients": {
            joint_hh.client_ids[0]: (
                f"Shares a joint account with {names[spouse]}. Advisor: {advisor_names[demo_advisors[0]]}."
            ),
            demo_split.client_ids[0]: (
                f"Has accounts with two advisors. {advisor_names[demo_advisors[0]]} sees only some of them."
            ),
            tech_demo: (
                f"Heavy in technology stocks, review due this month. Advisor: {advisor_names[demo_advisors[1]]}."
            ),
        },
    }

    # One fixed demo administrator (not from Faker, so the advisor and client data stay identical).
    admins = [
        {
            "id": 1,
            "username": "morgan.lee",
            "first_name": "Morgan",
            "last_name": "Lee",
            "email": "morgan.lee@example.com",
        }
    ]

    return Dataset(
        admins=admins,
        anchor=anchor,
        advisors=advisors,
        clients=clients,
        accounts=accounts,
        access=access,
        securities=SECURITIES,
        holdings=holdings,
        transactions=transactions,
        performance=performance,
        documents=documents,
        demo=demo,
    )
