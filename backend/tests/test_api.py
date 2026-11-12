"""API tests against the hand-built fixture (see tests/fixtures.py), with a fake Claude client."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from tests.fixtures import A1, A2, A3, C1, C2, C3, C4, J, K, X, Y, Z
from tests.test_agent_loop import FakeClient, reply, text, tool_use
from tests.test_guard import FakeGuard
from wealth.api import deps, routes_advisor
from wealth.api.main import create_app
from wealth.config import get_settings


def as_user(kind: str, person_id: int) -> dict:
    return {"X-Demo-User": f"{kind}:{person_id}"}


@pytest.fixture
def fake_llm():
    return FakeClient([])


@pytest.fixture
def fake_guard():
    return FakeGuard("in_scope")


@pytest.fixture
def api(conn, fake_llm, fake_guard, monkeypatch):
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    for name in ("ECS_CONTAINER_METADATA_URI_V4", "ECS_CONTAINER_METADATA_URI", "AWS_EXECUTION_ENV"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()

    @contextmanager
    def store():
        yield conn

    app = create_app()
    app.dependency_overrides[deps.get_conn] = lambda: conn
    app.dependency_overrides[deps.get_agent_conn] = lambda: conn
    app.dependency_overrides[deps.get_llm_client] = lambda: fake_llm
    app.dependency_overrides[routes_advisor.get_store] = lambda: store
    app.dependency_overrides[routes_advisor.get_guard] = lambda: fake_guard
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def ids(rows, key="account_id"):
    return [r[key] for r in rows]


# --- sign-in stand-in ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header", [None, "", "admin:1", "client:abc", "client:0", "client:999999", "advisor:1;drop"]
)
def test_bad_or_missing_user_is_401(api, header):
    headers = {} if header is None else {"X-Demo-User": header}
    assert api.get("/api/me", headers=headers).status_code == 401


def test_me(api):
    assert api.get("/api/me", headers=as_user("client", C1)).json()["portal"] == "/client"
    assert api.get("/api/me", headers=as_user("advisor", A1)).json()["portal"] == "/advisor"


def test_portals_are_role_checked(api):
    assert api.get("/api/advisor/clients", headers=as_user("client", C1)).status_code == 403
    assert api.get("/api/client/accounts", headers=as_user("advisor", A1)).status_code == 403


def test_demo_login_refused_on_aws(api, monkeypatch):
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4/x")
    assert api.get("/api/me", headers=as_user("client", C1)).status_code == 401
    assert api.get("/api/demo/users").status_code == 404


def test_app_will_not_start_on_aws_with_demo_login(monkeypatch):
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AWS_EXECUTION_ENV", "AWS_ECS_FARGATE")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="not allowed on AWS"):
            with TestClient(create_app()):
                pass
    finally:
        get_settings.cache_clear()


def test_demo_login_off_by_default(api, monkeypatch):
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "false")
    get_settings.cache_clear()
    assert api.get("/api/me", headers=as_user("client", C1)).status_code == 401


def test_demo_users_listed(api, conn):
    conn.execute(
        "INSERT INTO demo_users (person_type, advisor_id, client_id, note, sort_order)"
        " VALUES ('advisor', %s, NULL, 'demo advisor', 1), ('client', NULL, %s, 'demo client', 2)",
        (A1, C1),
    )
    users = api.get("/api/demo/users").json()["users"]
    assert [(u["kind"], u["id"]) for u in users] == [("advisor", A1), ("client", C1)]
    assert users[0]["client_count"] == 3


# --- client portal ---------------------------------------------------------------------------------------


def test_client_sees_only_own_open_accounts(api):
    c1 = api.get("/api/client/accounts", headers=as_user("client", C1)).json()
    assert sorted(ids(c1["accounts"])) == [X, Y]  # not closed K
    c3 = api.get("/api/client/accounts", headers=as_user("client", C3)).json()
    assert sorted(ids(c3["accounts"])) == [J, Z]
    assert c3["total_market_value"] == 24000


def test_joint_account_shared_by_both_owners_only(api):
    for client_id in (C2, C3):
        assert (
            api.get(f"/api/client/holdings?account_id={J}", headers=as_user("client", client_id)).status_code
            == 200
        )
    assert api.get(f"/api/client/holdings?account_id={J}", headers=as_user("client", C1)).status_code == 404


@pytest.mark.parametrize("path", ["holdings", "transactions", "gains", "performance"])
@pytest.mark.parametrize("account_id", [Z, K, 999999])
def test_client_cannot_open_other_or_closed_accounts(api, path, account_id):
    r = api.get(f"/api/client/{path}?account_id={account_id}", headers=as_user("client", C1))
    assert r.status_code == 404


def test_client_holdings_all_accounts(api):
    h = api.get("/api/client/holdings", headers=as_user("client", C1)).json()
    assert h["portfolio_market_value"] == 20000  # X 5000 + Y 15000
    assert len(h["holdings"]) == 4  # full detail


def test_client_transactions_paging_and_filter(api):
    page = api.get("/api/client/transactions?page_size=2", headers=as_user("client", C1)).json()
    assert page["total_rows"] == 4 and len(page["transactions"]) == 2  # X: 3, Y: 1; never K
    buys = api.get("/api/client/transactions?types=buy", headers=as_user("client", C1)).json()
    assert {t["type"] for t in buys["transactions"]} == {"buy"} and buys["total_rows"] == 2
    assert (
        api.get("/api/client/transactions?types=transfer", headers=as_user("client", C1)).status_code == 422
    )
    assert api.get("/api/client/transactions?page_size=500", headers=as_user("client", C1)).status_code == 422


def test_client_gains(api):
    g = api.get("/api/client/gains", headers=as_user("client", C1)).json()
    assert g["realized_total"] == 0  # C1 has no sells
    assert g["unrealized_total"] == 2400  # X: 1000 + 500 - 100 = 1400, Y: 1000
    g2 = api.get("/api/client/gains", headers=as_user("client", C2)).json()
    assert g2["realized_total"] == 60 and g2["realized_by_month"][0]["realized_gain"] == 60


def test_client_performance_includes_growth(api):
    p = api.get(f"/api/client/performance?account_id={X}", headers=as_user("client", C1)).json()
    assert [g["as_of_date"] for g in p["growth"]] == ["2026-10-31", "2026-11-10"]
    assert p["growth"][0]["growth_index"] == 100
    assert p["growth"][1]["growth_index"] == 102.0  # +2% 1M return at the second point


def test_client_profile_is_own(api):
    assert api.get("/api/client/profile", headers=as_user("client", C2)).json()["id"] == C2


# --- advisor portal --------------------------------------------------------------------------------------


def test_advisor_clients_and_book_total(api):
    r = api.get("/api/advisor/clients", headers=as_user("advisor", A1)).json()
    assert sorted(ids(r["clients"], "client_id")) == [C1, C2, C3]
    assert r["total_market_value"] == 9000  # X + J, J counted once though it has two clients
    assert api.get("/api/advisor/clients", headers=as_user("advisor", A3)).json()["clients"] == []


def test_advisor_sees_only_shared_accounts_of_a_client(api):
    r = api.get(f"/api/advisor/clients/{C1}/accounts", headers=as_user("advisor", A1)).json()
    assert ids(r["accounts"]) == [X]
    assert api.get(f"/api/advisor/clients/{C4}/accounts", headers=as_user("advisor", A1)).status_code == 404


# --- assistant -------------------------------------------------------------------------------------------


def ask(api, advisor_id, **body):
    return api.post("/api/advisor/assistant/messages", headers=as_user("advisor", advisor_id), json=body)


def test_assistant_runs_tools_as_signed_in_advisor(api, fake_llm):
    fake_llm.responses += [
        reply("tool_use", tool_use("get_accounts", {"client_id": C1})),
        reply("end_turn", text("C1 has account X.")),
    ]
    r = ask(api, A1, message="Accounts for client 201?").json()
    assert r["answer"] == "C1 has account X." and r["tool_calls"][0]["name"] == "get_accounts"
    sent = fake_llm.requests[-1]["messages"][-1]["content"][0]["content"]
    assert f'"account_id": {Y}' not in sent  # A1 never sees Y


def test_assistant_conversation_continues(api, fake_llm, conn):
    fake_llm.responses += [reply("end_turn", text("first")), reply("end_turn", text("second"))]
    first = ask(api, A1, message="hello").json()
    second = ask(api, A1, message="and again", conversation_id=first["conversation_id"]).json()
    assert second["conversation_id"] == first["conversation_id"] and second["answer"] == "second"
    sent = fake_llm.requests[-1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    row = conn.execute("SELECT transcript FROM agent_conversations").fetchone()
    assert row["transcript"] == ["hello", "first", "and again", "second"]


def test_assistant_conversation_of_another_advisor_is_404(api, fake_llm):
    fake_llm.responses += [reply("end_turn", text("mine"))]
    conv = ask(api, A1, message="hello").json()["conversation_id"]
    assert ask(api, A2, message="read it", conversation_id=conv).status_code == 404


def test_assistant_focus_client_must_be_accessible(api, fake_llm):
    assert ask(api, A1, message="tell me about them", client_id=C4).status_code == 404
    assert fake_llm.requests == []  # rejected before any model call


def test_assistant_focus_client_is_sent_as_context(api, fake_llm):
    fake_llm.responses += [reply("end_turn", text("ok"))]
    ask(api, A1, message="How are they doing?", client_id=C1)
    first_message = fake_llm.requests[0]["messages"][0]["content"]
    assert first_message.startswith(f"[Selected client: Cli {C1} (client ID {C1}).")


def test_assistant_stops_if_access_is_revoked_mid_answer(api, fake_llm, conn):
    def revoke_then_call_tool(**kwargs):
        fake_llm.requests.append(kwargs)
        conn.execute("DELETE FROM account_access WHERE advisor_id = %s", (A1,))
        return reply("tool_use", tool_use("get_accounts", {"client_id": C1}))

    fake_llm.beta.messages.create = revoke_then_call_tool
    r = ask(api, A1, message="accounts?", client_id=C1).json()
    assert r["stop_reason"] == "access_revoked" and r["tool_calls"] == []


def test_assistant_rejects_unknown_fields_and_long_messages(api):
    url, headers = "/api/advisor/assistant/messages", as_user("advisor", A1)
    assert api.post(url, headers=headers, json={"message": "hi", "advisor_id": A2}).status_code == 422
    assert ask(api, A1, message="x" * 2001).status_code == 422
    assert (
        api.post(
            "/api/advisor/assistant/messages", headers=as_user("client", C1), json={"message": "hi"}
        ).status_code
        == 403
    )


# --- guardrails ------------------------------------------------------------------------------------------


def events(conn):
    return conn.execute("SELECT outcome, question, reason FROM assistant_events ORDER BY id").fetchall()


def test_off_topic_question_is_blocked_and_logged(api, fake_llm, fake_guard, conn):
    fake_guard.category = "out_of_scope"
    r = ask(api, A1, message="What is the diameter of the moon?").json()
    assert r["blocked"] is True and r["stop_reason"] == "blocked_scope" and fake_llm.requests == []
    assert events(conn) == [
        {
            "outcome": "blocked_scope",
            "question": "What is the diameter of the moon?",
            "reason": "fake out_of_scope",
        }
    ]


def test_answered_question_is_logged(api, fake_llm, conn):
    fake_llm.responses += [reply("end_turn", text("hello"))]
    assert ask(api, A1, message="hi").json()["blocked"] is False
    assert [e["outcome"] for e in events(conn)] == ["answered"]


def test_per_minute_limit(api, fake_llm, conn, monkeypatch):
    monkeypatch.setenv("ASSISTANT_PER_MINUTE", "2")
    get_settings.cache_clear()
    fake_llm.responses += [reply("end_turn", text("a")), reply("end_turn", text("b"))]
    assert ask(api, A1, message="one").status_code == 200
    assert ask(api, A1, message="two").status_code == 200
    third = ask(api, A1, message="three")
    assert third.status_code == 429 and third.headers["Retry-After"] == "60"
    assert "a minute" in third.json()["detail"]
    assert [e["outcome"] for e in events(conn)] == ["answered", "answered", "rate_limited"]
    # Limits are per advisor.
    fake_llm.responses += [reply("end_turn", text("c"))]
    assert ask(api, A2, message="other advisor").status_code == 200


def test_daily_cap(api, conn, monkeypatch):
    monkeypatch.setenv("ASSISTANT_PER_DAY", "3")
    get_settings.cache_clear()
    conn.execute(
        "INSERT INTO assistant_events (advisor_id, created_at, outcome, question)"
        " SELECT %s, now() - interval '30 minutes', 'answered', 'q' FROM generate_series(1, 3)",
        (A1,),
    )
    r = ask(api, A1, message="one more")
    assert r.status_code == 429 and "today's limit" in r.json()["detail"]
    assert int(r.headers["Retry-After"]) > 0


def test_rate_limited_attempts_do_not_count(api, fake_llm, conn, monkeypatch):
    monkeypatch.setenv("ASSISTANT_PER_MINUTE", "1")
    get_settings.cache_clear()
    conn.execute(
        "INSERT INTO assistant_events (advisor_id, outcome, question)"
        " SELECT %s, 'rate_limited', 'spam' FROM generate_series(1, 50)",
        (A1,),
    )
    fake_llm.responses += [reply("end_turn", text("ok"))]
    assert ask(api, A1, message="real question").status_code == 200


def test_assistant_focus_scopes_every_tool_call(api, fake_llm):
    # With C1 selected, the model asks for the whole client list: it must only get C1 back.
    fake_llm.responses += [
        reply("tool_use", tool_use("get_my_clients", {})),
        reply("end_turn", text("Only C1.")),
    ]
    r = ask(api, A1, message="list my clients", client_id=C1).json()
    sent = json.loads(fake_llm.requests[-1]["messages"][-1]["content"][0]["content"])
    assert [c["client_id"] for c in sent["clients"]] == [C1]
    assert r["answer"] == "Only C1."
