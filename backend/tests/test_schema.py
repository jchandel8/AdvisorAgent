"""The database itself rejects malformed ACL rows and transactions."""

from __future__ import annotations

import psycopg
import pytest

from tests.fixtures import A1, C1, MISSING_ID, W, X

ACL_INSERT = (
    "INSERT INTO account_access (account_id, person_type, advisor_id, client_id, role)"
    " VALUES (%s, %s, %s, %s, %s)"
)


@pytest.mark.parametrize(
    "row",
    [
        pytest.param((W, "advisor", A1, C1, "advisor"), id="both-ids-set"),
        pytest.param((W, "advisor", None, None, "advisor"), id="no-id-set"),
        pytest.param((W, "client", A1, None, "owner"), id="id-does-not-match-type"),
        pytest.param((W, "advisor", A1, None, "owner"), id="advisor-with-client-role"),
        pytest.param((W, "client", None, C1, "advisor"), id="client-with-advisor-role"),
        pytest.param((W, "manager", A1, None, "advisor"), id="unknown-person-type"),
    ],
)
def test_bad_acl_rows_are_rejected(conn, row):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(ACL_INSERT, row)


def test_acl_row_for_missing_person_is_rejected(conn):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(ACL_INSERT, (W, "advisor", MISSING_ID, None, "advisor"))


def test_duplicate_acl_row_is_rejected(conn):
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(ACL_INSERT, (X, "advisor", A1, None, "advisor"))


def test_valid_acl_row_is_accepted(conn):
    conn.execute(ACL_INSERT, (W, "advisor", A1, None, "viewer"))


def test_buy_without_symbol_is_rejected(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO transactions (account_id, trade_date, type, quantity, price, amount)"
            " VALUES (%s, '2026-01-01', 'buy', 1, 1, 1)",
            (X,),
        )


def test_view_exposes_person_id(conn):
    rows = conn.execute(
        "SELECT person_type, person_id FROM v_account_access WHERE account_id = %s ORDER BY person_type",
        (X,),
    ).fetchall()
    assert rows == [{"person_type": "advisor", "person_id": A1}, {"person_type": "client", "person_id": C1}]


def test_read_only_transaction_blocks_writes(test_db_url):
    from wealth.db import read_only

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        with read_only(test_db_url) as c:
            c.execute("DELETE FROM documents")


def test_filter_values_match_lookup_tables(conn):
    from wealth.tools.schemas import ASSET_CLASSES, CURRENCIES, SECTORS

    def values(sql):
        return {r["v"].strip() for r in conn.execute(sql).fetchall()}

    assert values("SELECT name AS v FROM sectors") == set(SECTORS)
    assert values("SELECT code AS v FROM asset_classes") == set(ASSET_CLASSES)
    assert values("SELECT code AS v FROM currencies") == set(CURRENCIES)


def test_security_with_unknown_sector_or_currency_is_rejected(conn):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("INSERT INTO securities VALUES ('ZZZ', 'Test', 'Crypto', 'equity', 'USD')")


def test_security_with_unknown_currency_is_rejected(conn):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("INSERT INTO securities VALUES ('ZZZ', 'Test', 'Technology', 'equity', 'EUR')")
