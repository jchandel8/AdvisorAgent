"""Full agent traces: what is recorded, the audited admin view, safety of the stored payloads, and caching."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from tests.fixtures import A1, ADMIN, C1, TODAY, X, Y
from tests.test_agent_loop import FakeClient, reply, text, tool_use
from tests.test_api import api, as_user, fake_guard, fake_llm  # noqa: F401  (pytest fixtures)
from wealth.agent import trace as trace_mod
from wealth.agent.guard import ScopeGuard
from wealth.agent.loop import AdvisorAgent
from wealth.agent.prompts import SYSTEM_PROMPT
from wealth.agent.trace import MAX_PAYLOAD_BYTES, Tracer, capped, clean, cost_usd


def ask(api, **body):  # noqa: F811
    return api.post("/api/advisor/assistant/messages", headers=as_user("advisor", A1), json=body)


def runs(conn):
    return conn.execute("SELECT * FROM agent_runs ORDER BY id").fetchall()


def steps(conn, run_id):
    return conn.execute("SELECT * FROM agent_steps WHERE run_id = %s ORDER BY seq", (run_id,)).fetchall()


# --- what a run records ----------------------------------------------------------------------------------


def test_a_question_records_every_step_with_real_values(api, fake_llm, conn):  # noqa: F811
    fake_llm.responses += [
        reply("tool_use", tool_use("get_accounts", {"client_id": C1})),
        reply("end_turn", text("C1 has account X.")),
    ]
    assert ask(api, message="Accounts for client 201?").status_code == 200
    (run,) = runs(conn)
    assert (run["feature"], run["advisor_id"], run["outcome"], run["answer"]) == (
        "assistant",
        A1,
        "answered",
        "C1 has account X.",
    )
    assert run["tool_calls"] == 1 and run["model_calls"] == 2 and run["conversation_id"] is not None
    event = conn.execute("SELECT id FROM assistant_events ORDER BY id DESC LIMIT 1").fetchone()
    assert run["assistant_event_id"] == event["id"]

    kinds = [(s["kind"], s["name"]) for s in steps(conn, run["id"])]
    assert [k for k, _ in kinds] == ["scope_check", "model", "tool", "model"]
    assert kinds[2][1] == "get_accounts"
    tool = next(s for s in steps(conn, run["id"]) if s["kind"] == "tool")
    assert tool["request"]["input"] == {"client_id": C1}
    assert [a["account_id"] for a in tool["response"]["accounts"]] == [
        X
    ]  # the real result, client data included
    assert f'"account_id": {Y}' not in json.dumps(tool["response"])
    first_model = next(s for s in steps(conn, run["id"]) if s["kind"] == "model")
    assert first_model["stop_reason"] == "tool_use"
    assert "Accounts for client 201?" in json.dumps(first_model["request"]["new_messages"])
    assert first_model["response"]["content"][0]["name"] == "get_accounts"


def test_blocked_question_records_only_the_scope_check(api, fake_guard, conn):  # noqa: F811
    fake_guard.category = "out_of_scope"
    ask(api, message="What is the diameter of the moon?")
    (run,) = runs(conn)
    assert run["outcome"] == "blocked_scope" and run["model_calls"] == 0
    assert [s["kind"] for s in steps(conn, run["id"])] == ["scope_check"]
    assert steps(conn, run["id"])[0]["response"]["category"] == "out_of_scope"


def test_system_prompt_is_stored_once_per_version(api, fake_llm, conn):  # noqa: F811
    for _ in range(2):
        fake_llm.responses.append(reply("end_turn", text("Hello.")))
        ask(api, message="hi")
    prompts = conn.execute("SELECT * FROM agent_prompts WHERE role = 'assistant'").fetchall()
    assert len(prompts) == 1 and prompts[0]["text"] == SYSTEM_PROMPT
    assert {r["prompt_hash"] for r in runs(conn)} == {prompts[0]["hash"]}


def test_a_tracing_failure_never_breaks_the_answer(api, fake_llm, conn, monkeypatch):  # noqa: F811
    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(Tracer, "save", broken)
    fake_llm.responses.append(reply("end_turn", text("Still answered.")))
    r = ask(api, message="hi")
    assert r.status_code == 200 and r.json()["answer"] == "Still answered."


def test_answer_cache_hits_are_recorded(conn):
    from wealth.agent.answer_cache import AnswerCache

    cache = AnswerCache()
    client = FakeClient([reply("end_turn", text("Hello there."))])
    AdvisorAgent(A1, client, model="test-model", today=TODAY, conn=conn, cache=cache).ask("hi")
    t = Tracer("assistant", A1, "hi")
    result = AdvisorAgent(A1, client, model="test-model", today=TODAY, conn=conn, cache=cache, trace=t).ask(
        "hi"
    )
    assert result.from_cache and [s.kind for s in t.steps] == ["cache"]


# --- the admin view ---------------------------------------------------------------------------------------


def test_admin_lists_runs_and_opening_one_is_audited(api, fake_llm, conn):  # noqa: F811
    fake_llm.responses += [
        reply("tool_use", tool_use("get_accounts", {"client_id": C1})),
        reply("end_turn", text("C1 has account X.")),
    ]
    ask(api, message="Accounts for client 201?")
    admin = as_user("admin", ADMIN)
    listing = api.get("/api/admin/agent-runs", headers=admin).json()
    assert listing["total_rows"] == 1 and listing["runs"][0]["question"] == "Accounts for client 201?"
    assert (
        conn.execute("SELECT count(*) AS n FROM permission_audit").fetchone()["n"] == 0
    )  # listing isn't audited

    run_id = listing["runs"][0]["id"]
    detail = api.get(f"/api/admin/agent-runs/{run_id}", headers=admin).json()
    assert detail["system_prompt"] == SYSTEM_PROMPT and len(detail["steps"]) >= 3
    assert any(
        s["kind"] == "tool" and s["response"]["accounts"][0]["account_id"] == X for s in detail["steps"]
    )
    audit = conn.execute("SELECT action, agent_run_id, admin_id FROM permission_audit").fetchall()
    assert [(a["action"], a["agent_run_id"], a["admin_id"]) for a in audit] == [
        ("view_agent_run", run_id, ADMIN)
    ]

    events = api.get("/api/admin/assistant-events?blocked_only=false", headers=admin).json()["events"]
    assert events[0]["run_id"] == run_id
    assert api.get("/api/admin/agent-runs/999999", headers=admin).status_code == 404


def test_only_admins_can_read_traces(api):  # noqa: F811
    for who in (as_user("advisor", A1), as_user("client", C1)):
        assert api.get("/api/admin/agent-runs", headers=who).status_code == 403
        assert api.get("/api/admin/agent-runs/1", headers=who).status_code == 403


def test_runs_filter_by_advisor_and_outcome(api, fake_llm, fake_guard, conn):  # noqa: F811
    fake_llm.responses.append(reply("end_turn", text("Hello.")))
    ask(api, message="hi")
    fake_guard.category = "out_of_scope"
    ask(api, message="weather?")
    admin = as_user("admin", ADMIN)
    assert api.get("/api/admin/agent-runs?outcome=blocked_scope", headers=admin).json()["total_rows"] == 1
    assert api.get(f"/api/admin/agent-runs?advisor_id={A1}", headers=admin).json()["total_rows"] == 2
    assert api.get("/api/admin/agent-runs?advisor_id=102", headers=admin).json()["total_rows"] == 0


# --- stored payloads are safe ----------------------------------------------------------------------------


def test_secrets_and_signature_blobs_are_never_stored():
    payload = {
        "Authorization": "Bearer abc",
        "nested": [{"api_key": "sk-123", "token": "t", "input_tokens": 5}],
        "content": [
            {"type": "thinking", "thinking": "Let me look up accounts.", "signature": "x" * 500},
            {"type": "redacted_thinking", "data": "y" * 500},
        ],
    }
    out = clean(payload)
    assert out["Authorization"] == "[removed]" and out["nested"][0]["api_key"] == "[removed]"
    assert out["nested"][0]["token"] == "[removed]" and out["nested"][0]["input_tokens"] == 5
    assert out["content"][0] == {"type": "thinking", "thinking": "Let me look up accounts."}
    assert out["content"][1] == {"type": "redacted_thinking"}


def test_large_payloads_are_capped_and_marked():
    small, cut = capped({"a": 1})
    assert small == {"a": 1} and not cut
    big, cut = capped({"rows": ["x" * 1000] * 200})
    assert cut and len(big["truncated_preview"].encode()) <= MAX_PAYLOAD_BYTES


def test_old_runs_are_deleted_after_the_retention_period(conn, monkeypatch):
    monkeypatch.setenv("TRACE_RETENTION_DAYS", "30")
    old = Tracer("assistant", A1, "old question")
    old_id = old.save(conn, outcome="answered")
    conn.execute("UPDATE agent_runs SET started_at = now() - interval '31 days' WHERE id = %s", (old_id,))
    Tracer("assistant", A1, "new question").save(conn, outcome="answered")
    assert [r["question"] for r in runs(conn)] == ["new question"]


def test_cost_is_computed_only_for_priced_models():
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    assert cost_usd("claude-sonnet-5-5", usage) == Decimal("3.0")
    assert cost_usd("us.anthropic.claude-sonnet-4-6", usage) is None
    t = Tracer("assistant", A1, "q")
    t.add("model", "claude-haiku-5-5", usage={"input_tokens": 1000, "output_tokens": 0})
    t.add("model", "us.anthropic.claude-sonnet-4-6", usage={"input_tokens": 1000, "output_tokens": 0})
    assert t.totals()["cost_usd"] is None  # one unpriced call makes the run's cost unknown, not understated
    assert trace_mod.PRICES  # prices come from one table


# --- caching ---------------------------------------------------------------------------------------------


def test_cached_prefix_is_identical_on_different_days_and_the_date_moves_to_the_message(conn):
    sent = []
    for day in (date(2026, 11, 11), date(2026, 12, 25)):
        client = FakeClient([reply("end_turn", text("Hi."))])
        AdvisorAgent(A1, client, model="test-model", today=day, conn=conn).ask("hello")
        sent.append(client.requests[0])
    assert sent[0]["system"] == sent[1]["system"] and sent[0]["tools"] == sent[1]["tools"]
    assert sent[0]["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "2026" not in sent[0]["system"][0]["text"]
    assert sent[0]["messages"][0]["content"].startswith("[Today: 2026-11-11")
    assert sent[1]["messages"][0]["content"].startswith("[Today: 2026-12-25")


def test_scope_check_marks_its_fixed_instructions_cacheable():
    captured = {}

    class Client:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                body = json.dumps({"category": "in_scope", "reason": "ok"})
                return SimpleNamespace(
                    stop_reason="end_turn",
                    content=[SimpleNamespace(type="text", text=body)],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=600),
                )

    verdict = ScopeGuard(Client(), model="claude-haiku-5-5").check("hello")
    assert verdict.allowed and verdict.usage.cache_read_input_tokens == 600
    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}
