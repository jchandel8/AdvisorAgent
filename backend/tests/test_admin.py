"""Admin portal API: users, accounts, permissions and the audit log."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from tests.fixtures import A1, A2, A3, ADMIN, C1, C2, C3, D1, D2, MISSING_ID, J, K, W, X, Y, Z
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


# --- drilldowns and documents ------------------------------------------------------------------------

NEW_ADMIN_ROUTES = [
    f"/api/admin/users/client/{C1}",
    f"/api/admin/accounts/{X}",
    "/api/admin/documents",
    f"/api/admin/documents/{D1}",
    f"/api/admin/documents/{D1}/content",
    f"/api/admin/documents/{D1}/download",
]


@pytest.mark.parametrize("path", NEW_ADMIN_ROUTES)
@pytest.mark.parametrize("header", [f"advisor:{A1}", f"client:{C1}"])
def test_drilldowns_and_documents_are_admin_only(admin_api, conn, path, header):
    assert admin_api.get(path, headers={"X-Demo-User": header}).status_code == 403
    assert audit(conn) == []  # a refused request records nothing


def test_client_drilldown_lists_all_their_accounts(admin_api):
    r = admin_api.get(f"/api/admin/users/client/{C1}", headers=ADMIN_H).json()
    assert r["profile"]["username"] == f"cli{C1}" and r["profile"]["risk_profile"] == "moderate"
    accounts = {a["account_id"]: a for a in r["accounts"]}
    assert set(accounts) == {X, Y, K}  # admins see every account, including closed ones
    assert accounts[X]["role"] == "owner" and accounts[X]["advisors"] == "Adv 101"
    assert r["accounts"][-1]["account_id"] == K  # closed accounts last


def test_advisor_drilldown_lists_accounts_and_clients(admin_api):
    r = admin_api.get(f"/api/admin/users/advisor/{A2}", headers=ADMIN_H).json()
    assert {a["account_id"] for a in r["accounts"]} == {Y, J, Z, W}
    joint = next(a for a in r["accounts"] if a["account_id"] == J)
    assert joint["clients"] == "Cli 202, Cli 203" and joint["advisors"] == "Adv 101, Adv 102"
    empty = admin_api.get(f"/api/admin/users/advisor/{A3}", headers=ADMIN_H).json()
    assert empty["accounts"] == []


def test_admin_drilldown_and_their_activity(admin_api):
    r = admin_api.get(f"/api/admin/users/admin/{ADMIN}", headers=ADMIN_H).json()
    assert r["profile"]["username"] == "admin901" and r["accounts"] == []
    admin_api.post(
        "/api/admin/access",
        headers=ADMIN_H,
        json={"account_id": Y, "person_type": "advisor", "person_id": A1, "role": "viewer"},
    )
    mine = admin_api.get(f"/api/admin/audit?admin_id={ADMIN}", headers=ADMIN_H).json()
    assert mine["total_rows"] == 1 and mine["events"][0]["admin_id"] == ADMIN
    other = admin_api.get(f"/api/admin/audit?admin_id={MISSING_ID}", headers=ADMIN_H).json()
    assert other["total_rows"] == 0


@pytest.mark.parametrize("kind", ["advisor", "client", "admin"])
def test_unknown_user_is_404(admin_api, kind):
    assert admin_api.get(f"/api/admin/users/{kind}/{MISSING_ID}", headers=ADMIN_H).status_code == 404


def test_unknown_user_kind_is_422(admin_api):
    assert admin_api.get(f"/api/admin/users/robot/{A1}", headers=ADMIN_H).status_code == 422


def test_account_drilldown_has_users_and_documents_but_no_values(admin_api):
    r = admin_api.get(f"/api/admin/accounts/{J}", headers=ADMIN_H).json()
    assert r["account_name"] == "J Joint" and r["account_type"] == "joint"
    people = {(p["person_type"], p["person_id"], p["role"]) for p in r["access"]}
    assert people == {
        ("client", C2, "owner"),
        ("client", C3, "joint_owner"),
        ("advisor", A1, "advisor"),
        ("advisor", A2, "advisor"),
    }
    assert [d["document_id"] for d in r["documents"]] == [D2]
    assert "market_value" not in str(r)  # admins don't read portfolios
    assert admin_api.get(f"/api/admin/accounts/{MISSING_ID}", headers=ADMIN_H).status_code == 404


def test_documents_list_search_filter_and_uploader(admin_api):
    r = admin_api.get("/api/admin/documents", headers=ADMIN_H).json()
    assert r["total_rows"] == 2 and [d["document_id"] for d in r["documents"]] == [D2, D1]  # newest first
    d1 = r["documents"][1]
    assert d1["uploaded_by"] == "Adv 101" and d1["account_name"] == "X Individual"
    assert "text" not in d1  # the list never carries document text

    def ids(**params):
        res = admin_api.get("/api/admin/documents", headers=ADMIN_H, params=params).json()
        return [d["document_id"] for d in res["documents"]]

    assert ids(q="policy") == [D1]
    assert ids(q="joint") == [D2]  # account name
    assert ids(q=str(X)) == [D1]  # account ID
    assert ids(doc_type="review_notes") == [D2]
    assert ids(doc_type="ips", q="review") == []
    assert admin_api.get("/api/admin/documents?doc_type=memo", headers=ADMIN_H).status_code == 422


def test_document_detail_is_not_audited_and_has_no_text(admin_api, conn):
    r = admin_api.get(f"/api/admin/documents/{D1}", headers=ADMIN_H).json()
    assert r["title"] == "Investment policy statement" and r["created_date"] == "2026-03-02"
    assert r["uploaded_by_id"] == A1 and r["access_log"] == []
    assert "text" not in r
    assert audit(conn) == []
    assert admin_api.get(f"/api/admin/documents/{MISSING_ID}", headers=ADMIN_H).status_code == 404


def test_preview_and_download_are_recorded(admin_api, conn):
    r = admin_api.get(f"/api/admin/documents/{D1}/content", headers=ADMIN_H)
    assert r.json()["text"] == "Target 60/40.\nRebalance yearly."

    dl = admin_api.get(f"/api/admin/documents/{D1}/download", headers=ADMIN_H)
    assert dl.status_code == 200 and dl.text == "Target 60/40.\nRebalance yearly."
    assert dl.headers["content-type"].startswith("text/plain")
    assert dl.headers["content-disposition"] == f'attachment; filename="investment-policy-statement-{D1}.txt"'
    assert dl.headers["cache-control"] == "no-store"

    rows = conn.execute(
        "SELECT action, document_id, account_id, admin_id FROM permission_audit ORDER BY id"
    ).fetchall()
    assert [(x["action"], x["document_id"], x["account_id"], x["admin_id"]) for x in rows] == [
        ("view_document", D1, X, ADMIN),
        ("download_document", D1, X, ADMIN),
    ]
    detail = admin_api.get(f"/api/admin/documents/{D1}", headers=ADMIN_H).json()
    assert [(e["action"], e["person_type"], e["person_id"]) for e in detail["access_log"]] == [
        ("download", "admin", ADMIN),
        ("view", "admin", ADMIN),
    ]
    log = admin_api.get("/api/admin/audit", headers=ADMIN_H).json()["events"]
    assert (
        log[0]["summary"] == f"Downloaded document Investment policy statement (#{D1}) of X Individual (#{X})"
    )


def test_missing_document_content_records_nothing(admin_api, conn):
    assert admin_api.get(f"/api/admin/documents/{MISSING_ID}/content", headers=ADMIN_H).status_code == 404
    assert admin_api.get(f"/api/admin/documents/{MISSING_ID}/download", headers=ADMIN_H).status_code == 404
    assert audit(conn) == []
