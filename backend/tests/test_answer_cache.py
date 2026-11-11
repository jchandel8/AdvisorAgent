"""Answer cache: hits, misses, isolation between advisors, access changes, expiry and LRU eviction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from tests.fixtures import A1, A2, TODAY, W
from tests.test_agent_loop import FakeClient, reply, text, tool_use
from wealth.agent.answer_cache import AnswerCache
from wealth.agent.loop import AdvisorAgent

QUESTION = "Which clients have reviews due this month?"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)

    def __call__(self):
        return self.now


def make(conn, advisor_id, responses, cache):
    client = FakeClient(responses)
    return AdvisorAgent(
        advisor_id, client, model="claude-haiku-5-5", today=TODAY, cache=cache, conn=conn
    ), client


def answered(t="Clients 201 and 202."):
    return [reply("tool_use", tool_use("find_reviews_due", {"within_days": 19})), reply("end_turn", text(t))]


def test_repeat_question_is_served_without_a_model_call(conn):
    cache = AnswerCache(clock=Clock())
    first, client1 = make(conn, A1, answered(), cache)
    assert first.ask(QUESTION).stop_reason == "end_turn"

    second, client2 = make(conn, A1, [], cache)  # no scripted responses: any model call would fail
    result = second.ask("  which clients have REVIEWS due this month? ")  # whitespace/case normalized
    assert result.from_cache and result.text == "Clients 201 and 202."
    assert client2.requests == []
    # The cached turn is in the history, so a follow-up question still has context.
    assert second.history[-1] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "Clients 201 and 202."}],
    }


def test_answers_are_never_shared_between_advisors(conn):
    cache = AnswerCache(clock=Clock())
    make(conn, A1, answered(), cache)[0].ask(QUESTION)
    other, client = make(conn, A2, answered("A2's answer."), cache)
    result = other.ask(QUESTION)
    assert not result.from_cache and result.text == "A2's answer." and len(client.requests) == 2


def test_access_change_retires_cached_answers(conn):
    cache = AnswerCache(clock=Clock())
    make(conn, A1, answered(), cache)[0].ask(QUESTION)
    # Admin grants A1 access to account W: the old answer must not be reused.
    conn.execute(
        "INSERT INTO account_access (account_id, person_type, advisor_id, role) VALUES (%s, 'advisor', %s, 'advisor')",
        (W, A1),
    )
    again, client = make(conn, A1, answered("Now including client 204."), cache)
    result = again.ask(QUESTION)
    assert not result.from_cache and result.text == "Now including client 204."


def test_follow_up_depends_on_conversation(conn):
    cache = AnswerCache(clock=Clock())
    a, _ = make(conn, A1, [*answered(), reply("end_turn", text("Follow-up answer."))], cache)
    a.ask(QUESTION)
    a.ask("And their market values?")
    # The same follow-up asked as a first question is a different conversation: a miss.
    fresh, client = make(conn, A1, [reply("end_turn", text("Standalone answer."))], cache)
    assert fresh.ask("And their market values?").text == "Standalone answer."
    assert len(client.requests) == 1


def test_entries_expire_after_ttl(conn):
    clock = Clock()
    cache = AnswerCache(ttl=timedelta(minutes=30), clock=clock)
    make(conn, A1, answered(), cache)[0].ask(QUESTION)
    clock.now += timedelta(minutes=31)
    a, client = make(conn, A1, answered("Fresh."), cache)
    assert a.ask(QUESTION).text == "Fresh."
    assert len(client.requests) == 2


def test_entries_expire_at_local_midnight(conn):
    clock = Clock()
    cache = AnswerCache(ttl=timedelta(days=7), clock=clock)
    make(conn, A1, answered(), cache)[0].ask(QUESTION)
    expires = conn.execute("SELECT expires_at FROM answer_cache").fetchone()["expires_at"]
    local_midnight = datetime.combine(TODAY + timedelta(days=1), datetime.min.time()).astimezone()
    assert expires == local_midnight


def test_least_recently_used_entries_are_evicted(conn):
    clock = Clock()
    cache = AnswerCache(max_entries=2, clock=clock)
    for i, q in enumerate(["q1", "q2"]):
        clock.now += timedelta(seconds=1)
        make(conn, A1, [reply("end_turn", text(f"a{i + 1}"))], cache)[0].ask(q)
    clock.now += timedelta(seconds=1)
    assert make(conn, A1, [], cache)[0].ask("q1").from_cache  # q1 is now the most recently used
    clock.now += timedelta(seconds=1)
    make(conn, A1, [reply("end_turn", text("a3"))], cache)[0].ask("q3")  # evicts q2, the least recent

    answers = {r["answer"] for r in conn.execute("SELECT answer FROM answer_cache").fetchall()}
    assert answers == {"a1", "a3"}


def test_failed_turns_are_not_cached(conn):
    cache = AnswerCache(clock=Clock())
    make(conn, A1, [reply("refusal")], cache)[0].ask(QUESTION)
    make(conn, A1, [reply("max_tokens", text("partial"))], cache)[0].ask("another question")
    assert conn.execute("SELECT count(*) AS n FROM answer_cache").fetchone()["n"] == 0


def test_cache_disabled_always_calls_the_model(conn):
    a, client = make(conn, A1, [*answered(), *answered()], None)
    a.ask(QUESTION)
    b = AdvisorAgent(A1, client, model="claude-haiku-5-5", today=TODAY, cache=None, conn=conn)
    b.ask(QUESTION)
    assert len(client.requests) == 4


def test_usage_is_summed_across_model_calls(conn):
    usage = SimpleNamespace(
        input_tokens=100, output_tokens=10, cache_read_input_tokens=50, cache_creation_input_tokens=5
    )
    responses = answered()
    for r in responses:
        r.usage = usage
    result = make(conn, A1, responses, None)[0].ask(QUESTION)
    assert (result.usage.model_calls, result.usage.input_tokens, result.usage.cache_read_input_tokens) == (
        2,
        200,
        100,
    )
