"""MCP servers: the same access rules over MCP, the internal token, and the guard in front of the servers.

A real uvicorn server runs the app on a random loopback port, so these calls go over actual HTTP through
the guard, the token check and the MCP SDK, just as the agent's calls do in production.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date

import httpx2
import jwt
import pytest
import uvicorn

from tests.fixtures import A1, A2, A3, C1, C3, MISSING_ID, TODAY, J, X, Y, Z
from wealth.agent.loop import AdvisorAgent
from wealth.api.main import create_app
from wealth.mcp import analytics, internal_token, portfolio
from wealth.mcp.client import LocalToolRunner, McpToolRunner, _definitions
from wealth.tools.registry import TOOLS, tool_definitions

# --- a live server on a random port ------------------------------------------------------------------


@pytest.fixture
def base_url(conn):
    portfolio.use_connection(conn)  # tools read the rolled-back test transaction
    _definitions.cache_clear()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        assert time.time() < deadline, "test server did not start"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    portfolio.use_connection(None)
    _definitions.cache_clear()


def mcp_call(base_url, name, args, advisor_id, focus=None):
    return McpToolRunner(base_url=base_url).call(
        name, args, advisor_id=advisor_id, today=TODAY, focus_client_id=focus
    )


def account_ids(result):
    return sorted(a["account_id"] for a in result["accounts"])


# --- the tools over MCP --------------------------------------------------------------------------------


def test_tool_list_over_mcp_is_exactly_the_registry(base_url):
    served = McpToolRunner(base_url=base_url).definitions()
    # Byte-identical to the local definitions, so the prompt cache sees the same tools either way.
    assert json.dumps(served) == json.dumps(tool_definitions())
    assert "advisor_id" not in json.dumps(served)


SAMPLE_INPUTS = {
    "get_my_clients": {},
    "get_accounts": {"client_id": C1},
    "get_holdings": {"client_id": C3},
    "get_transactions": {"account_id": X, "start_date": "2025-01-01", "end_date": "2026-11-11"},
    "get_performance": {"client_id": C1},
    "find_reviews_due": {"within_days": 90},
    "search_documents": {"query": "college savings"},
}


def test_every_tool_is_covered():
    assert set(SAMPLE_INPUTS) == set(TOOLS)


@pytest.mark.parametrize("advisor", [A1, A2, A3])
@pytest.mark.parametrize("tool", sorted(SAMPLE_INPUTS))
def test_mcp_returns_exactly_what_the_local_tools_return(base_url, conn, advisor, tool):
    local = LocalToolRunner(conn).call(tool, SAMPLE_INPUTS[tool], advisor_id=advisor, today=TODAY)
    assert mcp_call(base_url, tool, SAMPLE_INPUTS[tool], advisor) == local


def test_shared_one_account_rule_holds_over_mcp(base_url):
    assert account_ids(mcp_call(base_url, "get_accounts", {"client_id": C1}, A1)) == [
        X
    ]  # not Y, not closed K
    assert account_ids(mcp_call(base_url, "get_accounts", {"client_id": C3}, A1)) == [J]  # not Z
    assert account_ids(mcp_call(base_url, "get_accounts", {"client_id": C1}, A2)) == [Y]


def test_forbidden_and_unknown_ids_look_the_same_over_mcp(base_url):
    forbidden = mcp_call(base_url, "get_holdings", {"account_id": Z}, A1)
    unknown = mcp_call(base_url, "get_holdings", {"account_id": MISSING_ID}, A1)
    assert forbidden == unknown and "error" in forbidden


def test_advisor_with_no_access_sees_nothing_over_mcp(base_url):
    assert mcp_call(base_url, "get_my_clients", {}, A3)["clients"] == []
    assert "error" in mcp_call(base_url, "get_accounts", {"client_id": C1}, A3) or not mcp_call(
        base_url, "get_accounts", {"client_id": C1}, A3
    ).get("accounts")


def test_model_supplied_advisor_id_is_rejected_over_mcp(base_url):
    out = mcp_call(base_url, "get_accounts", {"client_id": C1, "advisor_id": A2}, A1)
    assert out["error"] == "invalid input"


def test_selected_client_comes_from_the_token(base_url):
    out = mcp_call(base_url, "get_accounts", {"client_id": C3}, A1, focus=C1)
    assert out["error"] == "outside selected client"
    assert account_ids(mcp_call(base_url, "get_accounts", {"client_id": C1}, A1, focus=C1)) == [X]


def test_unknown_tool_is_an_error(base_url):
    assert "error" in mcp_call(base_url, "drop_tables", {}, A1)


def test_agent_runs_its_tools_over_mcp_as_the_session_advisor(base_url, conn):
    from tests.test_agent_loop import FakeClient, reply, text, tool_use

    client = FakeClient(
        [reply("tool_use", tool_use("get_accounts", {"client_id": C1})), reply("end_turn", text("C1 has X."))]
    )
    agent = AdvisorAgent(
        A1, client, model="test-model", today=TODAY, conn=conn, tools=McpToolRunner(base_url=base_url)
    )
    assert agent.ask("Which accounts does client 201 have?").text == "C1 has X."
    sent = client.requests[-1]["messages"][-1]["content"][0]
    assert [a["account_id"] for a in json.loads(sent["content"])["accounts"]] == [X]
    assert client.requests[0]["tools"] == tool_definitions()


# --- the guard: only calls from inside the process -----------------------------------------------------


def post(base_url, server="portfolio", token=None, headers=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **(headers or {}),
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return httpx2.post(f"{base_url}/mcp/{server}/", json=body, headers=h, timeout=10)


def good_token(server="portfolio"):
    return internal_token.sign(server, advisor_id=A1, today=TODAY)


def test_valid_internal_call_is_accepted(base_url):
    r = post(base_url, token=good_token())
    assert r.status_code == 200 and "get_accounts" in r.text


def test_missing_token_is_refused(base_url):
    assert post(base_url).status_code == 401


def test_token_signed_with_another_key_is_refused(base_url):
    forged = jwt.encode(
        {
            "iss": internal_token.ISSUER,
            "aud": "mcp:portfolio",
            "iat": 1,
            "exp": 4_000_000_000,
            "sub": str(A2),
            "today": "2026-11-11",
        },
        "x" * 32,
        algorithm="HS256",
    )
    assert post(base_url, token=forged).status_code == 401


def test_expired_token_is_refused(base_url):
    now = int(time.time())
    expired = jwt.encode(
        {
            "iss": internal_token.ISSUER,
            "aud": "mcp:portfolio",
            "iat": now - 300,
            "exp": now - 60,
            "sub": str(A1),
            "today": "2026-11-11",
        },
        internal_token._key(),
        algorithm="HS256",
    )
    assert post(base_url, token=expired).status_code == 401


def test_token_for_another_server_is_refused(base_url):
    assert post(base_url, server="portfolio", token=good_token("analytics")).status_code == 401
    assert post(base_url, server="analytics", token=good_token("portfolio")).status_code == 401


def test_unsigned_token_is_refused(base_url):
    unsigned = jwt.encode(
        {
            "iss": internal_token.ISSUER,
            "aud": "mcp:portfolio",
            "iat": 1,
            "exp": 4_000_000_000,
            "sub": str(A1),
            "today": "2026-11-11",
        },
        None,
        algorithm="none",
    )
    assert post(base_url, token=unsigned).status_code == 401


@pytest.mark.parametrize("header", ["X-Forwarded-For", "Forwarded", "X-Real-IP", "X-Forwarded-Proto"])
def test_requests_through_a_proxy_are_refused_even_with_a_valid_token(base_url, header):
    # The AWS load balancer always adds X-Forwarded-For, so outside traffic never reaches the servers.
    r = post(base_url, token=good_token(), headers={header: "127.0.0.1"})
    assert r.status_code == 403


def test_non_loopback_host_header_is_refused(base_url):
    # The MCP SDK's DNS-rebinding protection, on top of our own checks.
    r = post(base_url, token=good_token(), headers={"Host": "advisoragent.example.com"})
    assert r.status_code == 421


def test_portfolio_tools_need_an_advisor_in_the_token(base_url):
    no_advisor = internal_token.sign("portfolio", advisor_id=None, today=TODAY)
    body = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "get_my_clients", "arguments": {}},
    }
    r = httpx2.post(
        f"{base_url}/mcp/portfolio/",
        json=body,
        headers={
            "Authorization": f"Bearer {no_advisor}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        timeout=10,
    )
    assert r.status_code == 200 and "not authorized" in r.text and "clients" not in r.text


def test_mcp_paths_are_not_served_by_the_frontend_fallback(base_url):
    assert httpx2.get(f"{base_url}/mcp", timeout=10).status_code in (403, 404)


# --- the internal token ---------------------------------------------------------------------------------


def test_internal_token_round_trip():
    token = internal_token.sign("portfolio", advisor_id=A1, today=TODAY, focus_client_id=C1)
    who = internal_token.verify(token, "portfolio")
    assert (who.advisor_id, who.focus_client_id, who.today) == (A1, C1, TODAY)


def test_tampered_internal_token_is_refused():
    token = internal_token.sign("portfolio", advisor_id=A1, today=TODAY)
    header, payload, signature = token.split(".")
    other = internal_token.sign("portfolio", advisor_id=A2, today=TODAY).split(".")[1]
    with pytest.raises(internal_token.InternalTokenError):
        internal_token.verify(f"{header}.{other}.{signature}", "portfolio")


def test_unknown_server_cannot_be_signed_for():
    with pytest.raises(ValueError):
        internal_token.sign("crm", advisor_id=A1, today=date.today())


# --- analytics -------------------------------------------------------------------------------------------


def test_allocation_drift():
    out = analytics.allocation_drift(
        {"equity": 72, "fixed_income": 20, "cash": 8}, {"equity": 60, "fixed_income": 35, "cash": 5}
    )
    rows = {r["asset_class"]: r for r in out["classes"]}
    assert rows["equity"]["drift_pct"] == 12 and rows["equity"]["outside_band"]
    assert rows["fixed_income"]["drift_pct"] == -15 and rows["cash"]["outside_band"] is False
    assert out["total_drift_pct"] == 15 and out["needs_rebalance"]


def test_concentration():
    out = analytics.concentration({"AAPL": 30, "MSFT": 20, "NVDA": 10, "JNJ": 40})
    assert out["hhi"] == 3000 and out["effective_positions"] == 3.3
    assert out["top_1_pct"] == 40 and [p["name"] for p in out["over_limit"]] == ["JNJ", "AAPL", "MSFT"]


def test_rebalance_preview_adds_up_to_zero_to_the_cent():
    out = analytics.rebalance_preview(
        100_000.01, {"equity": 70.3333, "cash": 29.6667}, {"equity": 60, "cash": 40}
    )
    assert round(sum(m["amount"] for m in out["moves"]), 2) == 0
    assert out["turnover"] == max(m["amount"] for m in out["moves"])


def test_analytics_over_mcp_validates_and_computes(base_url):
    runner = McpToolRunner("analytics", base_url=base_url)
    names = [t["name"] for t in runner.definitions()]
    assert names == ["allocation_drift", "concentration", "rebalance_preview"]
    out = runner.call(
        "allocation_drift",
        {"current_pct": {"equity": 72, "cash": 28}, "target_pct": {"equity": 60, "cash": 40}},
        advisor_id=A1,
        today=TODAY,
    )
    assert out["total_drift_pct"] == 12
    bad = runner.call("concentration", {"weights_pct": {"AAPL": 140}}, advisor_id=A1, today=TODAY)
    assert "error" in bad or "140" in json.dumps(bad)
