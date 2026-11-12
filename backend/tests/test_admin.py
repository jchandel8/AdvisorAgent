"""Admin portal API: users, accounts, permissions and the audit log."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from tests.fixtures import A1, A2, A3, ADMIN, C1, C2, C3, J, K, X, Y
from wealth.api import deps, routes_admin
from wealth.api.main import create_app


class FakeLogins(routes_admin.Logins):
    def __init__(self):
        self.created = []
        self.fail = False

    def create(self, *, username, email, name, group):
        if self.fail:
            raise RuntimeError("Cognito said no")
        self.created.append({"username": username, "group": group})


@pytest.fixture
def logins():
    return FakeLogins()


@pytest.fixture
def admin_api(conn, logins):
    @contextmanager
    def tx():
        with conn.transaction():  # a savepoint per request, like the real per-request transaction
            yield conn

    def write_conn():
        with tx() as c:
            yield c

    app = create_app()
    app.dependency_overrides[deps.get_conn] = lambda: conn
    app.dependency_overrides[deps.get_write_conn] = write_conn
    app.dependency_overrides[routes_admin.get_logins] = lambda: logins
    with TestClient(app) as client:
        yield client


ADMIN_H = {"X-Demo-User": f"admin:{ADMIN}"}


def audit(conn):
    return conn.execute("SELECT action, summary, admin_name FROM permission_audit ORDER BY id").fetchall()


def advisor_sees(admin_api, advisor_id):
    r = admin_api.get("/api/advisor/clients", headers={"X-Demo-User": f"advisor:{advisor_id}"}).json()
    return {c["client_id"] for c in r["clients"]}


# --- access to the admin portal --------------------------------------------------------------------------


@pytest.mark.parametrize("header", [f"advisor:{A1}", f"client:{C1}"])
def test_only_admins_reach_admin_routes(admin_api, header):
    assert admin_api.get("/api/admin/users", headers={"X-Demo-User": header}).status_code == 403


def test_admin_cannot_use_the_portfolio_portals(admin_api):
    assert admin_api.get("/api/advisor/clients", headers=ADMIN_H).status_code == 403
    assert admin_api.get("/api/client/accounts", headers=ADMIN_H).status_code == 403
    assert admin_api.get("/api/me", headers=ADMIN_H).json()["portal"] == "/admin"


# --- users -------------------------------------------------------------------------------------------


def test_list_and_search_users(admin_api):
    advisors = admin_api.get("/api/admin/users?kind=advisor", headers=ADMIN_H).json()["users"]
    assert {a["id"] for a in advisors} == {A1, A2, A3}
    a1 = next(a for a in advisors if a["id"] == A1)
    assert (a1["account_count"], a1["client_count"]) == (3, 3)  # X, J, closed K; C1, C2, C3
    found = admin_api.get("/api/admin/users?kind=client&q=cli202", headers=ADMIN_H).json()["users"]
    assert [c["id"] for c in found] == [C2]


def test_create_user_makes_db_row_login_and_audit(admin_api, logins, conn):
    r = admin_api.post(
        "/api/admin/users",
        headers=ADMIN_H,
        json={"kind": "advisor", "first_name": "Priya", "last_name": "Shah", "email": "Priya@Example.com"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "priya.shah"
    assert logins.created == [{"username": "priya.shah", "group": "advisors"}]
    row = conn.execute("SELECT email FROM advisors WHERE id = %s", (body["id"],)).fetchone()
    assert row["email"] == "priya@example.com"
    assert audit(conn)[-1]["action"] == "create_user" and audit(conn)[-1]["admin_name"] == "Ada Admin"


def test_duplicate_username_or_email_is_409(admin_api):
    r = admin_api.post(
        "/api/admin/users",
        headers=ADMIN_H,
        json={"kind": "client", "first_name": "X", "last_name": "Y", "email": "z@e.co", "username": "adv101"},
    )
    assert r.status_code == 409


def test_failed_login_creation_saves_nothing(admin_api, logins, conn):
    logins.fail = True
    r = admin_api.post(
        "/api/admin/users",
        headers=ADMIN_H,
        json={"kind": "client", "first_name": "Lost", "last_name": "Login", "email": "lost@example.com"},
    )
    assert r.status_code == 502
    assert (
        conn.execute("SELECT count(*) AS n FROM clients WHERE username = 'lost.login'").fetchone()["n"] == 0
    )
    assert audit(conn) == []


@pytest.mark.parametrize(
    "bad",
    [
        {"email": "not-an-email"},
        {"username": "Has Spaces"},
        {"kind": "admin"},
        {"advisor_id": 5},
    ],
)
def test_bad_user_input_is_422(admin_api, bad):
    body = {"kind": "client", "first_name": "A", "last_name": "B", "email": "a@b.co", **bad}
    assert admin_api.post("/api/admin/users", headers=ADMIN_H, json=body).status_code == 422


# --- accounts ----------------------------------------------------------------------------------------


def test_create_joint_account_grants_owners_and_advisor(admin_api, conn):
    r = admin_api.post(
        "/api/admin/accounts",
        headers=ADMIN_H,
        json={
            "account_name": "Cli Family Joint",
            "account_type": "joint",
            "owner_client_ids": [C1, C2],
            "advisor_ids": [A3],
        },
    )
    assert r.status_code == 201
    acct = r.json()["account_id"]
    access = admin_api.get(f"/api/admin/accounts/{acct}/access", headers=ADMIN_H).json()["access"]
    assert sorted((a["person_type"], a["person_id"], a["role"]) for a in access) == [
        ("advisor", A3, "advisor"),
        ("client", C1, "owner"),
        ("client", C2, "joint_owner"),
    ]
    assert [a["action"] for a in audit(conn)] == ["create_account", "grant", "grant", "grant"]
    assert advisor_sees(admin_api, A3) == {C1, C2}  # A3 had no clients before


@pytest.mark.parametrize(
    "bad",
    [
        {"account_type": "joint", "owner_client_ids": [C1]},
        {"account_type": "individual", "owner_client_ids": [C1, C2]},
        {"advisor_ids": []},
        {"owner_client_ids": [C1, C1], "account_type": "joint"},
    ],
)
def test_bad_account_input_is_422(admin_api, bad):
    body = {
        "account_name": "Test",
        "account_type": "individual",
        "owner_client_ids": [C1],
        "advisor_ids": [A1],
        **bad,
    }
    assert admin_api.post("/api/admin/accounts", headers=ADMIN_H, json=body).status_code == 422


def test_account_with_unknown_person_is_404(admin_api):
    body = {
        "account_name": "Test",
        "account_type": "individual",
        "owner_client_ids": [999999],
        "advisor_ids": [A1],
    }
    assert admin_api.post("/api/admin/accounts", headers=ADMIN_H, json=body).status_code == 404


# --- permissions -------------------------------------------------------------------------------------


def test_grant_is_visible_to_the_advisor_immediately(admin_api, conn):
    assert C1 not in advisor_sees(admin_api, A3)
    r = admin_api.post(
        "/api/admin/access",
        headers=ADMIN_H,
        json={"account_id": X, "person_type": "advisor", "person_id": A3, "role": "advisor"},
    )
    assert r.status_code == 201
    assert advisor_sees(admin_api, A3) == {C1}
    assert audit(conn)[-1]["summary"].startswith("Granted Adv 103 (advisor) advisor access to X Individual")


def test_revoke_is_visible_to_the_advisor_immediately(admin_api, conn):
    access = admin_api.get(f"/api/admin/accounts/{J}/access", headers=ADMIN_H).json()["access"]
    a1_row = next(a for a in access if a["person_type"] == "advisor" and a["person_id"] == A1)
    assert admin_api.delete(f"/api/admin/access/{a1_row['access_id']}", headers=ADMIN_H).status_code == 200
    assert advisor_sees(admin_api, A1) == {C1}  # C2 and C3 were only reachable through J
    assert audit(conn)[-1]["action"] == "revoke"


def test_cannot_remove_the_last_owner_or_last_advisor(admin_api):
    access = admin_api.get(f"/api/admin/accounts/{Y}/access", headers=ADMIN_H).json()["access"]
    owner = next(a for a in access if a["role"] == "owner")
    advisor = next(a for a in access if a["person_type"] == "advisor")
    assert admin_api.delete(f"/api/admin/access/{owner['access_id']}", headers=ADMIN_H).status_code == 409
    assert admin_api.delete(f"/api/admin/access/{advisor['access_id']}", headers=ADMIN_H).status_code == 409


def test_grant_errors(admin_api):
    def grant(**kw):
        body = {"account_id": X, "person_type": "advisor", "person_id": A2, "role": "advisor", **kw}
        return admin_api.post("/api/admin/access", headers=ADMIN_H, json=body).status_code

    assert grant(person_id=A1) == 409  # already has access
    assert grant(role="owner") == 422  # advisors can't own accounts
    assert grant(account_id=K) == 409  # closed account
    assert grant(person_id=999999) == 404
    assert grant(account_id=999999) == 404


def test_people_search_for_grant_form(admin_api):
    people = admin_api.get("/api/admin/people?q=adv10", headers=ADMIN_H).json()["people"]
    assert {(p["person_type"], p["person_id"]) for p in people} == {
        ("advisor", A1),
        ("advisor", A2),
        ("advisor", A3),
    }
    assert admin_api.get(f"/api/admin/people?q={C3}", headers=ADMIN_H).json()["people"][0]["person_id"] == C3


# --- logs --------------------------------------------------------------------------------------------


def test_audit_log_lists_changes_newest_first(admin_api):
    admin_api.post(
        "/api/admin/access",
        headers=ADMIN_H,
        json={"account_id": X, "person_type": "client", "person_id": C3, "role": "viewer"},
    )
    log = admin_api.get("/api/admin/audit", headers=ADMIN_H).json()
    assert log["total_rows"] == 1 and log["events"][0]["action"] == "grant"


def test_assistant_log_shows_blocked_questions(admin_api, conn):
    conn.execute(
        "INSERT INTO assistant_events (advisor_id, outcome, question, reason) VALUES"
        " (%s, 'blocked_scope', 'moon?', 'off topic'), (%s, 'answered', 'fine', NULL)",
        (A1, A1),
    )
    blocked = admin_api.get("/api/admin/assistant-events", headers=ADMIN_H).json()["events"]
    assert [e["question"] for e in blocked] == ["moon?"]
    everything = admin_api.get("/api/admin/assistant-events?blocked_only=false", headers=ADMIN_H).json()
    assert everything["total_rows"] == 2
