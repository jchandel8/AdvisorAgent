"""Load a generated Dataset into Postgres (replacing all data) and write demo_users.csv.

Everything runs in ONE transaction: if any insert fails, the database keeps its previous data.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from wealth.datagen.generate import Dataset

REPO_ROOT = Path(__file__).resolve().parents[4]
DEMO_USERS_CSV = REPO_ROOT / "demo_users.csv"

TABLES = [
    "permission_audit",
    "assistant_events",
    "agent_conversations",
    "demo_users",
    "answer_cache",
    "documents",
    "performance",
    "transactions",
    "holdings",
    "account_access",
    "securities",
    "accounts",
    "clients",
    "advisors",
    "admins",
]


def _copy(cur: psycopg.Cursor, table: str, columns: list[str], rows: list[tuple]) -> None:
    with cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


def load(conn: psycopg.Connection, ds: Dataset) -> None:
    with conn.transaction():
        cur = conn.cursor()
        cur.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")

        # Small tables keep the generator's IDs (OVERRIDING SYSTEM VALUE), then identities are moved past them.
        cur.executemany(
            "INSERT INTO advisors (id, username, first_name, last_name, email, phone, certifications, city, state)"
            " OVERRIDING SYSTEM VALUE VALUES (%(id)s, %(username)s, %(first_name)s, %(last_name)s, %(email)s,"
            " %(phone)s, %(certifications)s, %(city)s, %(state)s)",
            ds.advisors,
        )
        cur.executemany(
            "INSERT INTO clients (id, username, first_name, last_name, email, phone, address, city, state,"
            " risk_profile, target_allocation, next_review_date) OVERRIDING SYSTEM VALUE VALUES"
            " (%(id)s, %(username)s, %(first_name)s, %(last_name)s, %(email)s, %(phone)s, %(address)s, %(city)s,"
            " %(state)s, %(risk_profile)s, %(target_allocation)s, %(next_review_date)s)",
            [{**c, "target_allocation": Jsonb(c["target_allocation"])} for c in ds.clients],
        )
        cur.executemany(
            "INSERT INTO accounts (id, account_name, account_type, description, open_date, close_date)"
            " OVERRIDING SYSTEM VALUE VALUES (%(id)s, %(account_name)s, %(account_type)s, %(description)s,"
            " %(open_date)s, %(close_date)s)",
            ds.accounts,
        )
        cur.executemany(
            "INSERT INTO admins (id, username, first_name, last_name, email) OVERRIDING SYSTEM VALUE"
            " VALUES (%(id)s, %(username)s, %(first_name)s, %(last_name)s, %(email)s)",
            ds.admins,
        )
        for table in ("advisors", "clients", "accounts", "admins"):
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT max(id) FROM {table}))"
            )

        _copy(
            cur,
            "securities",
            ["symbol", "description", "sector", "asset_class", "currency"],
            [(s.symbol, s.description, s.sector, s.asset_class, "USD") for s in ds.securities],
        )
        _copy(
            cur,
            "account_access",
            ["account_id", "person_type", "advisor_id", "client_id", "role", "granted_by"],
            [
                (r["account_id"], r["person_type"], r["advisor_id"], r["client_id"], r["role"], "seed")
                for r in ds.access
            ],
        )
        _copy(
            cur,
            "holdings",
            ["account_id", "symbol", "quantity", "cost_basis", "price", "as_of_date"],
            ds.holdings,
        )
        _copy(
            cur,
            "transactions",
            ["account_id", "trade_date", "type", "symbol", "quantity", "price", "amount", "realized_gain"],
            ds.transactions,
        )
        _copy(
            cur,
            "performance",
            [
                "account_id",
                "as_of_date",
                "return_1d",
                "return_1m",
                "return_3m",
                "return_6m",
                "return_ytd",
                "return_1y",
                "return_2y",
                "return_3y",
                "return_5y",
            ],
            ds.performance,
        )
        tech_note = "Several clients are heavy in technology stocks with reviews due this month."
        demo_rows = (
            [("advisor", aid, None, None, tech_note, i) for i, aid in enumerate(ds.demo["advisor_ids"])]
            + [
                ("client", None, cid, None, note, 10 + i)
                for i, (cid, note) in enumerate(ds.demo["clients"].items())
            ]
            + [
                (
                    "admin",
                    None,
                    None,
                    a["id"],
                    "Creates users and accounts, and grants or revokes access.",
                    20 + i,
                )
                for i, a in enumerate(ds.admins)
            ]
        )
        _copy(
            cur,
            "demo_users",
            ["person_type", "advisor_id", "client_id", "admin_id", "note", "sort_order"],
            demo_rows,
        )
        _copy(
            cur,
            "documents",
            ["account_id", "title", "doc_type", "text", "size_kb", "created_date"],
            ds.documents,
        )


def analyze(conn: psycopg.Connection) -> None:
    """Refresh planner statistics after a bulk load, so queries use the indexes from the first run."""
    conn.execute(f"ANALYZE {', '.join(TABLES)}")
    conn.commit()


def write_demo_users(conn: psycopg.Connection, ds: Dataset, path: Path = DEMO_USERS_CSV) -> int:
    """Write every user with a suggested-demo note on the first rows. Client counts are computed in SQL."""
    advisor_notes = {
        aid: "DEMO advisor: has tech-overweight clients with reviews due this month"
        for aid in ds.demo["advisor_ids"]
    }
    client_notes = {cid: f"DEMO client: {note}" for cid, note in ds.demo["clients"].items()}

    advisors = conn.execute(
        """SELECT a.id, a.first_name || ' ' || a.last_name AS name, a.email,
                  count(DISTINCT ca.client_id) AS client_count
           FROM advisors a
           LEFT JOIN account_access aa ON aa.advisor_id = a.id
           LEFT JOIN account_access ca ON ca.account_id = aa.account_id AND ca.client_id IS NOT NULL
           GROUP BY a.id ORDER BY a.id"""
    ).fetchall()
    clients = conn.execute(
        "SELECT id, first_name || ' ' || last_name AS name, email FROM clients ORDER BY id"
    ).fetchall()

    rows = [
        {
            "name": r[1],
            "email": r[2],
            "role": "advisor",
            "person_id": r[0],
            "client_count": r[3],
            "demo_note": advisor_notes.get(r[0], ""),
        }
        for r in advisors
    ] + [
        {
            "name": r[1],
            "email": r[2],
            "role": "client",
            "person_id": r[0],
            "client_count": "",
            "demo_note": client_notes.get(r[0], ""),
        }
        for r in clients
    ]
    rows += [
        {
            "name": f"{a['first_name']} {a['last_name']}",
            "email": a["email"],
            "role": "admin",
            "person_id": a["id"],
            "client_count": "",
            "demo_note": "DEMO admin: creates users and accounts, grants and revokes access",
        }
        for a in ds.admins
    ]
    rows.sort(key=lambda r: (r["demo_note"] == "", r["role"], r["person_id"]))

    if not path.parent.is_dir() or not os.access(path.parent, os.W_OK):
        return 0  # e.g. inside the API container, where the repo root isn't mounted
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["name", "email", "role", "person_id", "client_count", "demo_note"]
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
