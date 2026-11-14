"""The AI Finalyst: workflow, review and revision, the figure check, access rules, reuse and limits.

No real model calls: a fake Claude answers by role (research agent, Finalyst, reviewer). Portfolio tools run
on the test fixture, analytics are the real functions, and the Market server is a fake with canned news.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.fixtures import A1, A2, C1, C4, X
from tests.test_api import as_user
from tests.test_guard import FakeGuard
from wealth.api import deps, routes_advisor, routes_finalyst
from wealth.api.main import create_app
from wealth.config import get_settings
from wealth.finalyst import workflow
from wealth.finalyst.checks import figures_in, known_numbers, supported, unsupported_figures
from wealth.mcp import analytics
from wealth.mcp.client import LocalToolRunner

NEWS_URL = "https://news.example.com/chips"


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(name, inp, id_="tu_1"):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


def reply(stop, *blocks):
    return SimpleNamespace(stop_reason=stop, content=list(blocks), usage=None)


def brief(figure="80", url=NEWS_URL):
    return {
        "summary": f"Technology is {figure}% of the portfolio against a 60% equity target.",
        "client_snapshot": "Moderate risk profile.",
        "suggestions": [
            {
                "title": "Review technology concentration",
                "rationale": "Equity is above target.",
                "evidence": [
                    {"source": "analytics", "detail": "Equity drift is 20 percentage points.", "url": ""},
                    {"source": "news", "detail": "Chip stocks rallied this week.", "url": url},
                ],
                "risks": "Selling could realize gains.",
                "confidence": "medium",
            }
        ],
        "questions_for_meeting": ["Is the client comfortable with the current risk?"],
        "watch_list": ["AAPL", "MSFT"],
    }


class FakeLLM:
    """Answers by the system prompt's role. drafts / reviews are consumed in order."""

    def __init__(self, drafts=None, reviews=None, refuse=False):
        self.drafts = list(drafts or [brief()])
        self.reviews = list(reviews or [{"approved": True, "issues": []}])
        self.refuse = refuse
        self.calls = []
        self.research_round = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        system = kw["system"][0]["text"]
        self.calls.append(kw)
        if system == workflow.RESEARCH_SYSTEM:
            self.research_round += 1
            if self.research_round == 1:
                return reply("tool_use", tool_use("search_news", {"query": "semiconductor stocks"}))
            return reply("end_turn", text(f"Chip stocks rallied this week ({NEWS_URL})."))
        if self.refuse:
            return reply("refusal")
        if system == workflow.FINALYST_SYSTEM:
            return reply("end_turn", text(json.dumps(self.drafts.pop(0))))
        if system == workflow.REVIEW_SYSTEM:
            return reply("end_turn", text(json.dumps(self.reviews.pop(0))))
        raise AssertionError("unexpected model call")


class LocalAnalytics:
    def definitions(self):
        return []

    def call(self, name, raw_input, **_):
        return {
            "allocation_drift": analytics.allocation_drift,
            "concentration": analytics.concentration,
            "rebalance_preview": analytics.rebalance_preview,
        }[name](**raw_input)


class FakeMarket:
    def __init__(self):
        self.queries = []

    def definitions(self):
        return [{"name": "search_news", "description": "news", "input_schema": {"type": "object"}}]

    def call(self, name, raw_input, **_):
        self.queries.append(raw_input)
        return {
            "results": [
                {
                    "title": "Chipmakers rally",
                    "url": NEWS_URL,
                    "source": "example.com",
                    "published": "Fri, 13 Nov 2026",
                    "snippet": "Chip stocks rose 4.2% this week.",
                }
            ]
        }


@pytest.fixture
def setup(conn, monkeypatch):
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_settings.cache_clear()
    state = SimpleNamespace(llm=FakeLLM(), market=FakeMarket(), guard=None)

    @contextmanager
    def store():
        yield conn

    def factory():
        def make(advisor_id, trace, on_stage):
            return workflow.Finalyst(
                state.llm,
                advisor_id,
                portfolio=LocalToolRunner(conn),
                analytics=LocalAnalytics(),
                market=state.market,
                trace=trace,
                finalyst_model="claude-opus-5-5",
                research_model="claude-sonnet-5-5",
                guard=state.guard,
                on_stage=on_stage,
            )

        return make

    app = create_app()
    app.dependency_overrides[deps.get_conn] = lambda: conn
    app.dependency_overrides[deps.get_write_conn] = lambda: conn
    app.dependency_overrides[routes_advisor.get_store] = lambda: store
    app.dependency_overrides[routes_finalyst.get_finalyst_factory] = factory
    app.dependency_overrides[routes_finalyst.get_launcher] = lambda: lambda job: job()  # run inline
    with TestClient(app) as client:
        state.api = client
        yield state
    get_settings.cache_clear()


def start(state, advisor=A1, **body):
    return state.api.post(
        "/api/advisor/finalyst/briefs",
        headers=as_user("advisor", advisor),
        json={"client_id": C1, "brief_type": "portfolio_review", **body},
    )


def get(state, brief_id, advisor=A1):
    return state.api.get(f"/api/advisor/finalyst/briefs/{brief_id}", headers=as_user("advisor", advisor))


# --- the workflow --------------------------------------------------------------------------------------------


def test_a_brief_runs_every_step_and_is_traced(setup, conn):
    r = start(setup)
    assert r.status_code == 202 and r.json()["status"] == "running"
    b = get(setup, r.json()["id"]).json()
    assert b["status"] == "done" and b["stage"] == "done" and b["client_name"] == "Cli 201"
    assert b["brief"]["disclaimer"] == workflow.DISCLAIMER
    assert b["brief"]["sources"] == [
        {
            "title": "Chipmakers rally",
            "url": NEWS_URL,
            "source": "example.com",
            "published": "Fri, 13 Nov 2026",
        }
    ]
    assert b["review"]["approved"] and not b["review"]["revised"]

    run = conn.execute("SELECT * FROM agent_runs WHERE feature = 'finalyst'").fetchone()
    assert run["focus_client_id"] == C1 and run["outcome"] == "answered"
    names = [
        s["name"]
        for s in conn.execute(
            "SELECT name FROM agent_steps WHERE run_id = %s ORDER BY seq", (run["id"],)
        ).fetchall()
    ]
    for expected in (
        "get_client_profile",
        "get_holdings",
        "search_documents",
        "allocation_drift",
        "search_news",
        "claude-opus-5-5",
        "review",
    ):
        assert expected in names, expected


def test_the_research_agent_never_sees_who_the_client_is(setup):
    start(setup)
    research = [c for c in setup.llm.calls if c["system"][0]["text"] == workflow.RESEARCH_SYSTEM]
    first = json.dumps(research[0]["messages"][0])
    assert (
        "Cli 201" not in first and str(C1) not in json.loads(research[0]["messages"][0]["content"]).values()
    )
    assert "AAPL" in first  # it does see the holdings it should research
    assert setup.market.queries == [{"query": "semiconductor stocks"}]


def test_an_unsupported_figure_triggers_one_revision(setup):
    setup.llm.drafts = [brief(figure="93.7"), brief()]
    setup.llm.reviews = [{"approved": True, "issues": []}, {"approved": True, "issues": []}]
    b = get(setup, start(setup).json()["id"]).json()
    assert b["review"]["revised"] and b["review"]["approved"]
    drafts = [c for c in setup.llm.calls if c["system"][0]["text"] == workflow.FINALYST_SYSTEM]
    assert len(drafts) == 2 and "93.7 is not in the data" in json.dumps(drafts[1]["messages"])
    # The shared context is the first, cacheable block of both drafting calls.
    assert drafts[0]["messages"][0]["content"][0] == drafts[1]["messages"][0]["content"][0]
    assert drafts[0]["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_issues_left_after_the_revision_are_shown_to_the_advisor(setup):
    setup.llm.drafts = [brief(), brief()]
    setup.llm.reviews = [{"approved": False, "issues": ["Too aggressive for a moderate client."]}] * 2
    b = get(setup, start(setup).json()["id"]).json()
    assert b["status"] == "done" and not b["review"]["approved"]
    assert b["review"]["issues"] == ["Too aggressive for a moderate client."]


def test_off_topic_note_is_blocked_before_any_model_writes(setup):
    setup.guard = FakeGuard("out_of_scope")
    b = get(setup, start(setup, note="write me a poem").json()["id"]).json()
    assert b["status"] == "failed" and "I can only help" in b["error"]
    assert not [c for c in setup.llm.calls if c["system"][0]["text"] == workflow.FINALYST_SYSTEM]


def test_a_model_refusal_fails_the_brief_cleanly(setup):
    setup.llm.refuse = True
    b = get(setup, start(setup).json()["id"]).json()
    assert b["status"] == "failed" and "declined" in b["error"]


# --- access, reuse, limits -----------------------------------------------------------------------------------


def test_only_clients_you_share_an_account_with(setup):
    assert start(setup, client_id=C4).status_code == 404
    brief_id = start(setup).json()["id"]
    assert get(setup, brief_id, advisor=A2).status_code == 404  # another advisor's brief


def test_revoking_access_hides_the_brief(setup, conn):
    brief_id = start(setup).json()["id"]
    conn.execute("DELETE FROM account_access WHERE account_id = %s AND advisor_id = %s", (X, A1))
    assert get(setup, brief_id).status_code == 404
    listing = setup.api.get("/api/advisor/finalyst/briefs", headers=as_user("advisor", A1)).json()
    assert brief_id not in [b["id"] for b in listing["briefs"]]


def test_an_identical_brief_today_is_reused_unless_refreshed(setup):
    first = start(setup).json()["id"]
    again = start(setup).json()
    assert again == {"id": first, "status": "done", "reused": True}
    setup.llm.drafts.append(brief())
    setup.llm.reviews.append({"approved": True, "issues": []})
    setup.llm.research_round = 0
    fresh = start(setup, refresh=True).json()
    assert fresh["id"] != first and not fresh["reused"]


def test_hourly_limit(setup, monkeypatch):
    monkeypatch.setenv("FINALYST_PER_HOUR", "1")
    get_settings.cache_clear()
    assert start(setup).status_code == 202
    assert start(setup, refresh=True).status_code == 429


def test_clients_and_other_roles_cannot_use_the_finalyst(setup):
    for who in (as_user("client", C1), as_user("admin", 901)):
        r = setup.api.post(
            "/api/advisor/finalyst/briefs", headers=who, json={"client_id": C1, "brief_type": "rebalancing"}
        )
        assert r.status_code == 403
    r = setup.api.post(
        "/api/advisor/finalyst/briefs",
        headers=as_user("advisor", A1),
        json={"client_id": C1, "brief_type": "rebalancing", "advisor_id": A2},
    )
    assert r.status_code == 422


# --- the figure check ----------------------------------------------------------------------------------------


def test_figures_skip_dates_years_and_small_counts():
    t = "On 2026-11-21, 3 accounts ($1.85M, up 8.62% since 2025) and a -2.5 drift."
    assert figures_in(t) == [1_850_000.0, 8.62, -2.5]


def test_supported_figures_allow_rounding_only():
    known = known_numbers({"mv": 1854511.57, "pct": 79.64, "text": "rose 4.2% this week"})
    assert supported(1_850_000, known) and supported(79.6, known) and supported(80, known)  # within 1%
    assert supported(4.2, known) and not supported(93.7, known)
    assert unsupported_figures(brief(figure="93.7"), known_numbers({"x": 60, "y": 20})) == [
        "summary: the figure 93.7 is not in the data"
    ]
