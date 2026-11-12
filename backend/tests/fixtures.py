"""Small hand-built dataset with a known answer for every access rule.

Advisors: A1 (101), A2 (102), A3 (103, no accounts at all)
Clients:  C1 (201), C2 (202), C3 (203), C4 (204, no advisor shares any account with A1)

Account X (301): C1 owner            + A1
Account Y (302): C1 owner            + A2          <- A1 must NOT see this (C1's other account)
Account J (303): C2 owner, C3 joint  + A1 and A2
Account Z (304): C3 owner            + A2          <- A1 must NOT see this
Account K (305): C1 owner            + A1, CLOSED  <- hidden from tools
Account W (306): C4 owner            + A2
"""

from __future__ import annotations

from datetime import date

import psycopg

TODAY = date(2026, 11, 11)
LATEST = date(2026, 11, 10)
PRIOR = date(2026, 10, 31)

A1, A2, A3 = 101, 102, 103
ADMIN = 901
C1, C2, C3, C4 = 201, 202, 203, 204
X, Y, J, Z, K, W = 301, 302, 303, 304, 305, 306
ALL_ACCOUNTS = [X, Y, J, Z, K, W]
ALL_CLIENTS = [C1, C2, C3, C4]
MISSING_ID = 999_999

SECURITIES = [
    ("AAPL", "Apple Inc.", "Technology", "equity"),
    ("MSFT", "Microsoft Corp.", "Technology", "equity"),
    ("JNJ", "Johnson & Johnson", "Health Care", "equity"),
    ("AGG", "iShares Core US Aggregate Bond ETF", "Fixed Income", "fixed_income"),
    ("CASH", "Cash", "Cash", "cash"),
]

# (account, symbol, quantity, cost_basis, price) at LATEST. Market values chosen to be easy to check.
HOLDINGS_LATEST = [
    (X, "AAPL", 10, 1000, 200),  # 2000
    (X, "MSFT", 5, 1500, 400),  # 2000
    (X, "AGG", 10, 1100, 100),  # 1000   -> X total 5000, tech 80%
    (Y, "JNJ", 100, 14000, 150),  # 15000  -> Y total 15000
    (J, "AAPL", 5, 900, 200),  # 1000
    (J, "AGG", 30, 3000, 100),  # 3000   -> J total 4000, tech 25%
    (Z, "MSFT", 50, 15000, 400),  # 20000
    (W, "CASH", 7000, 7000, 1),  # 7000
]
HOLDINGS_PRIOR = [
    (X, "AAPL", 10, 1000, 180),
    (X, "AGG", 10, 1100, 100),
    (J, "AGG", 30, 3000, 100),
]

TRANSACTIONS = [
    # account, date, type, symbol, qty, price, amount, realized_gain
    (X, date(2026, 6, 1), "deposit", None, None, None, 5000, None),
    (X, date(2026, 6, 2), "buy", "AAPL", 10, 100, 1000, None),
    (X, date(2026, 9, 15), "dividend", "AAPL", None, None, 12.5, None),
    (Y, date(2026, 7, 1), "buy", "JNJ", 100, 140, 14000, None),
    (J, date(2026, 8, 1), "sell", "AAPL", 2, 210, 420, 60),
    (Z, date(2026, 8, 5), "buy", "MSFT", 50, 300, 15000, None),
    (K, date(2025, 1, 5), "withdrawal", None, None, None, 300, None),
]

PERFORMANCE = [
    # account, as_of, 1d, 1m, 3m, 6m, ytd, 1y, 2y, 3y, 5y
    (X, PRIOR, 0.001, 0.01, 0.03, 0.05, 0.08, 0.10, None, None, None),
    (X, LATEST, 0.002, 0.02, 0.04, 0.06, 0.09, 0.11, 0.20, None, None),
    (Y, LATEST, -0.01, -0.05, -0.04, -0.03, -0.02, -0.01, 0.0, None, None),
    (J, LATEST, 0.003, 0.03, 0.02, 0.01, 0.05, 0.07, 0.12, 0.2, None),
    (Z, LATEST, 0.004, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.1, 0.5),
]


def load_fixture(conn: psycopg.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO admins (id, username, first_name, last_name, email) OVERRIDING SYSTEM VALUE"
        " VALUES (%s, 'admin901', 'Ada', 'Admin', 'admin901@example.com')",
        (ADMIN,),
    )
    cur.executemany(
        "INSERT INTO advisors (id, username, first_name, last_name, email) OVERRIDING SYSTEM VALUE "
        "VALUES (%s, %s, %s, %s, %s)",
        [(i, f"adv{i}", "Adv", str(i), f"adv{i}@example.com") for i in (A1, A2, A3)],
    )
    reviews = {
        C1: date(2026, 11, 20),  # due in 9 days
        C2: date(2026, 11, 1),  # overdue
        C3: date(2027, 1, 30),  # due in 80 days
        C4: date(2026, 11, 12),  # due tomorrow, but A1 cannot see C4
    }
    cur.executemany(
        "INSERT INTO clients (id, username, first_name, last_name, email, risk_profile, target_allocation,"
        " next_review_date) OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, 'moderate',"
        ' \'{"equity": 0.6, "fixed_income": 0.35, "cash": 0.05}\', %s)',
        [(i, f"cli{i}", "Cli", str(i), f"cli{i}@example.com", reviews[i]) for i in ALL_CLIENTS],
    )
    accounts = [
        (X, "X Individual", "individual", None),
        (Y, "Y IRA", "ira", None),
        (J, "J Joint", "joint", None),
        (Z, "Z Trust", "trust", None),
        (K, "K Closed", "individual", date(2025, 6, 1)),
        (W, "W Individual", "individual", None),
    ]
    cur.executemany(
        "INSERT INTO accounts (id, account_name, account_type, open_date, close_date) OVERRIDING SYSTEM VALUE "
        "VALUES (%s, %s, %s, '2020-01-01', %s)",
        accounts,
    )
    acl = [
        (X, "client", None, C1, "owner"),
        (X, "advisor", A1, None, "advisor"),
        (Y, "client", None, C1, "owner"),
        (Y, "advisor", A2, None, "advisor"),
        (J, "client", None, C2, "owner"),
        (J, "client", None, C3, "joint_owner"),
        (J, "advisor", A1, None, "advisor"),
        (J, "advisor", A2, None, "advisor"),
        (Z, "client", None, C3, "owner"),
        (Z, "advisor", A2, None, "advisor"),
        (K, "client", None, C1, "owner"),
        (K, "advisor", A1, None, "advisor"),
        (W, "client", None, C4, "owner"),
        (W, "advisor", A2, None, "advisor"),
    ]
    cur.executemany(
        "INSERT INTO account_access (account_id, person_type, advisor_id, client_id, role)"
        " VALUES (%s, %s, %s, %s, %s)",
        acl,
    )
    cur.executemany("INSERT INTO securities VALUES (%s, %s, %s, %s)", SECURITIES)
    cur.executemany(
        "INSERT INTO holdings (account_id, symbol, quantity, cost_basis, price, as_of_date)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        [(*h, LATEST) for h in HOLDINGS_LATEST] + [(*h, PRIOR) for h in HOLDINGS_PRIOR],
    )
    cur.executemany(
        "INSERT INTO transactions (account_id, trade_date, type, symbol, quantity, price, amount, realized_gain)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        TRANSACTIONS,
    )
    cur.executemany(
        "INSERT INTO performance (account_id, as_of_date, return_1d, return_1m, return_3m, return_6m,"
        " return_ytd, return_1y, return_2y, return_3y, return_5y)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        PERFORMANCE,
    )
