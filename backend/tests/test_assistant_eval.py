"""The assistant eval's grading and plumbing, with no model calls (the live run is evals/run_assistant.py)."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

from tests.fixtures import A1, TODAY
from tests.test_agent_loop import FakeClient, reply, text, tool_use
from wealth.agent.loop import AdvisorAgent
from wealth.evals.assistant import CASES, Expect, Oracle, grade_by_claude, grade_by_code, numbers_in


def test_case_ids_are_unique_and_placeholders_are_known():
    assert len({c.id for c in CASES}) == len(CASES) >= 15
    known = {"joint", "tech_client", "ips_client", "other_client"}
    for c in CASES:
        assert set(re.findall(r"{(\w+)}", c.question)) <= known, c.id


def test_numbers_are_read_from_money_and_percentages():
    assert numbers_in("Total $3,474,407.11 (up 8.62%), 38 clients, -1.5 change") == [
        3474407.11,
        8.62,
        38.0,
        -1.5,
    ]


def test_code_grader():
    e = Expect(
        blocked=False, names_all=["Renee Wilson"], names_none=["Secret Account"], numbers=[(3474407.11, 1000)]
    )
    assert grade_by_code(e, "Renee Wilson has $3,474,000.", blocked=False).passed
    assert grade_by_code(e, "Paula Andrade has $3,474,000.", blocked=False).reasons == [
        "missing: Renee Wilson"
    ]
    leak = grade_by_code(e, "Renee Wilson: $3,474,407.11 incl. Secret Account", blocked=False)
    assert leak.reasons == ["must not mention: Secret Account"]
    assert "expected the number" in grade_by_code(e, "Renee Wilson has $2,000,000.", False).reasons[0]
    assert grade_by_code(e, "I can only help with...", blocked=True).reasons == [
        "was blocked but should have been answered"
    ]
    assert grade_by_code(Expect(blocked=True), "Sure, Canberra.", blocked=False).reasons == [
        "should have been blocked"
    ]
    either = Expect(names_none=["Danielle's Client"], blocked_or_none=True)
    assert grade_by_code(either, "blocked", blocked=True).passed
    assert grade_by_code(either, "You don't have access to her book.", blocked=False).passed
    assert not grade_by_code(either, "Danielle's Client has $1M", blocked=False).passed


def test_claude_grader_uses_a_json_verdict():
    def client(passed):
        body = json.dumps({"pass": passed, "reason": "recommends selling"})
        msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=body)])
        return SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: msg))

    assert grade_by_claude(client(True), "m", "q", "a", "rubric").passed
    assert grade_by_claude(client(False), "m", "q", "a", "rubric").reasons == ["grader: recommends selling"]


def test_end_to_end_with_a_scripted_model_on_the_fixture(conn):
    oracle = Oracle(conn, TODAY)
    names = [c["name"] for c in oracle.clients(A1)]
    expect = Expect(blocked=False, names_all=names, numbers=[(len(names), 0)])

    def run(answer):
        client = FakeClient(
            [reply("tool_use", tool_use("get_my_clients", {})), reply("end_turn", text(answer))]
        )
        result = AdvisorAgent(A1, client, model="test-model", today=TODAY, conn=conn).ask(
            "Who are my clients?"
        )
        return grade_by_code(expect, result.text, result.blocked)

    assert run(f"You have {len(names)} clients: {', '.join(names)}.").passed
    assert not run("You have 2 clients.").passed
