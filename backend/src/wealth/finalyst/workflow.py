"""The AI Finalyst workflow: several agents and deterministic steps, orchestrated in code.

    note? ── scope check (Haiku) ─┐ blocked -> stop
    facts (code, Portfolio MCP: profile, accounts, holdings, performance, transactions, documents)
      ├── research agent (Sonnet, Market MCP: news search, sector moves)      } in parallel
      └── analytics (code, Analytics MCP: drift, concentration, rebalance)    }
    draft (Opus, structured brief) -> review (code: every figure backed by data; Sonnet: suitability,
    evidence, tone) -> one revision if needed -> final brief with the reviewer's remaining notes

Why code orchestration: each step has one job, a fixed input and a fixed output, so runs are predictable,
testable and cheap. Models decide what to search and what to write; code decides the order of the steps.

Security: the advisor comes from the verified login only (every MCP call carries a signed internal token).
The research agent sees tickers, company names and sectors, never client names or values, and the Market
server refuses queries with client data anyway. Nothing here sends anything to the client.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from wealth.agent.guard import ScopeGuard
from wealth.agent.trace import Tracer, usage_of
from wealth.finalyst.checks import known_numbers, unsupported_figures
from wealth.mcp.client import ToolRunner

log = logging.getLogger(__name__)

BRIEF_TYPES = {
    "portfolio_review": "a portfolio review: how the portfolio stands against the client's plan and what to look at",
    "market_impact": "market impact: how recent market and news developments affect this client's holdings",
    "rebalancing": "rebalancing ideas: where the portfolio has drifted from target and options to bring it back",
    "meeting_prep": "meeting preparation: what to raise at the client's next review, with questions to ask",
}
DISCLAIMER = "Prepared for the advisor's review. Not advice to the client."
MAX_RESEARCH_ROUNDS = 5
MAX_TOKENS = 12000

STAGES = ["checking", "facts", "research", "drafting", "reviewing", "revising", "done"]

# --- prompts (fixed text, so they are cached) ---------------------------------------------------------------

RESEARCH_SYSTEM = """You are the research agent of a wealth-management team. You get a list of securities and \
sectors held in a portfolio, and the kind of brief being prepared. Find recent, relevant market news and \
price moves for those holdings and sectors, using the tools.

Rules:
- Search only for companies, tickers, sectors and market topics. Never put people's names, account numbers or \
any client details in a search.
- Make at most 4 news searches. Prefer the largest holdings and the most concentrated sectors.
- Finish with a short plain-text summary: 3 to 6 findings, each one or two sentences, each naming the holding or \
sector it affects and citing the URL it came from. Say plainly when you found nothing relevant."""

FINALYST_SYSTEM = """You are the AI Finalyst: you prepare a brief for a human financial advisor about one of \
their clients. The advisor decides what to do; you organize the evidence and suggest what to consider.

Rules:
- Use only the facts, analytics, research and documents provided. Every figure you write must come from them; \
do not compute new figures yourself (the analytics already did the math).
- Each suggestion needs evidence: name where it comes from (facts, analytics, news or documents) and give the \
specific detail. News evidence must include the URL it came from.
- Suggestions must suit the client's risk profile and target allocation. Say when something is a trade-off.
- Write for the advisor, never to the client. Suggest what to consider or discuss; do not instruct anyone to buy \
or sell.
- 2 to 4 suggestions. Plain, specific language: write "the review is 14 days overdue", never data field names \
such as days_until_review. confidence reflects how strong the evidence is.
- If a reviewer's notes are included, fix every point they raise."""

REVIEW_SYSTEM = """You review a brief written for a financial advisor about one client, before the advisor sees \
it. Check:
1. Each suggestion suits the client's risk profile and target allocation, or clearly says it is a trade-off.
2. Each suggestion has evidence that actually appears in the provided data or research.
3. News claims cite a URL from the research sources.
4. It is written for the advisor: no instructions to the client, no promises of returns.
Approve only if all four hold. List each problem precisely and briefly."""

EVIDENCE = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "enum": ["facts", "analytics", "news", "documents"]},
        "detail": {"type": "string"},
        "url": {"type": "string", "description": "for news: the article URL; otherwise an empty string"},
    },
    "required": ["source", "detail", "url"],
    "additionalProperties": False,
}
BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "client_snapshot": {"type": "string"},
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "rationale": {"type": "string"},
                    "evidence": {"type": "array", "items": EVIDENCE},
                    "risks": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["title", "rationale", "evidence", "risks", "confidence"],
                "additionalProperties": False,
            },
        },
        "questions_for_meeting": {"type": "array", "items": {"type": "string"}},
        "watch_list": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "client_snapshot", "suggestions", "questions_for_meeting", "watch_list"],
    "additionalProperties": False,
}
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["approved", "issues"],
    "additionalProperties": False,
}

DOC_QUERY = {
    "portfolio_review": "review OR policy OR rebalance OR retire",
    "market_impact": "concentration OR technology OR volatility OR rebalance",
    "rebalancing": "rebalance OR target OR allocation OR policy",
    "meeting_prep": "review OR beneficiary OR college OR retire OR expense",
}


class FinalystError(Exception):
    """The run can't produce a brief (client not accessible, a model refused, malformed output)."""


@dataclass
class BriefResult:
    outcome: str  # done, blocked_scope, blocked_manipulation, guard_error
    brief: dict | None = None
    review: dict = field(default_factory=dict)
    message: str | None = None


def _effort(model: str) -> dict:
    return {} if "haiku-4-5" in model else {"effort": "medium"}


class Finalyst:
    def __init__(
        self,
        llm: Any,
        advisor_id: int,
        *,
        portfolio: ToolRunner,
        analytics: ToolRunner,
        market: ToolRunner,
        trace: Tracer,
        finalyst_model: str,
        research_model: str,
        guard: ScopeGuard | None = None,
        today: date | None = None,
        on_stage: Callable[[str], None] | None = None,
    ):
        self.llm = llm
        self.advisor_id = advisor_id
        self.portfolio, self.analytics, self.market = portfolio, analytics, market
        self.trace = trace
        self.finalyst_model, self.research_model = finalyst_model, research_model
        self.guard = guard
        self.today = today or date.today()
        self.on_stage = on_stage or (lambda stage: None)
        trace.prompt("finalyst", FINALYST_SYSTEM, None, main=True)
        trace.prompt("finalyst_research", RESEARCH_SYSTEM, None)
        trace.prompt("finalyst_review", REVIEW_SYSTEM, None)

    # --- helpers ---------------------------------------------------------------------------------------

    def _tool(self, runner: ToolRunner, name: str, args: dict, focus: int | None = None) -> dict:
        with self.trace.timed() as timing:
            out = runner.call(name, args, advisor_id=self.advisor_id, today=self.today, focus_client_id=focus)
        self.trace.add(
            "tool", name, timing=timing, request={"input": args}, response=out, is_error="error" in out
        )
        return out

    def _model(
        self, role: str, model: str, system: str, messages: list, schema: dict | None = None, **kw
    ) -> Any:
        options: dict = {"model": model, "max_tokens": MAX_TOKENS, "messages": messages, **kw}
        options["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        output_config = _effort(model)
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if output_config:
            options["output_config"] = output_config
        with self.trace.timed() as timing:
            response = self.llm.messages.create(**options)
        content = [_block(b) for b in response.content]
        self.trace.add(
            "model",
            model,
            timing=timing,
            request={
                "role": role,
                "messages": messages[-1:],
                "tools": [t["name"] for t in kw.get("tools", [])],
            },
            response={"content": content},
            stop_reason=response.stop_reason,
            usage=usage_of(getattr(response, "usage", None)),
        )
        if response.stop_reason == "refusal":
            raise FinalystError(f"the {role} model declined this request")
        return response

    @staticmethod
    def _json(response: Any) -> dict:
        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            return json.loads(text)
        except ValueError as exc:
            raise FinalystError("a model returned malformed output") from exc

    # --- steps -------------------------------------------------------------------------------------------

    def gather_facts(self, client_id: int, brief_type: str) -> dict:
        profile = self._tool(self.portfolio, "get_client_profile", {"client_id": client_id})
        if "error" in profile:
            raise FinalystError("client not found")
        holdings = self._tool(self.portfolio, "get_holdings", {"client_id": client_id})
        return {
            "client": profile,
            "accounts": self._tool(self.portfolio, "get_accounts", {"client_id": client_id}),
            "holdings": holdings,
            "performance": self._tool(self.portfolio, "get_performance", {"client_id": client_id}),
            "recent_transactions": self._tool(
                self.portfolio,
                "get_transactions",
                {"client_id": client_id, "start_date": (self.today - timedelta(days=90)).isoformat()},
            ),
            "documents": self._tool(
                self.portfolio,
                "search_documents",
                {"client_id": client_id, "query": DOC_QUERY[brief_type], "limit": 5},
            ),
        }

    def run_analytics(self, facts: dict) -> dict:
        client = facts["client"]
        positions = facts["holdings"].get("holdings") or []
        weights = {
            p["symbol"]: p["pct_of_portfolio"] for p in positions if p.get("pct_of_portfolio") is not None
        }
        total = float(
            facts["holdings"].get("portfolio_market_value") or client.get("accessible_market_value") or 0
        )
        current, target = client["current_allocation_pct"], client["target_allocation_pct"]
        out = {
            "allocation_drift": self._tool(
                self.analytics, "allocation_drift", {"current_pct": current, "target_pct": target}
            )
        }
        if weights:
            out["concentration"] = self._tool(self.analytics, "concentration", {"weights_pct": weights})
        if total > 0:
            out["rebalance_preview"] = self._tool(
                self.analytics,
                "rebalance_preview",
                {"total_value": total, "current_pct": current, "target_pct": target},
            )
        return out

    def research(self, facts: dict, brief_type: str) -> dict:
        """The research agent: a short tool-use loop over the Market server. Sees holdings, not the client."""
        positions = facts["holdings"].get("holdings") or []
        top = sorted(positions, key=lambda p: -(p.get("pct_of_portfolio") or 0))[:6]
        sectors = facts["holdings"].get("sector_summary") or []
        watch = {
            "top_holdings": [
                {
                    "symbol": p["symbol"],
                    "name": p.get("description"),
                    "sector": p.get("sector"),
                    "weight_pct": p.get("pct_of_portfolio"),
                }
                for p in top
            ],
            "sectors": [{"sector": s.get("sector"), "pct": s.get("pct_of_portfolio")} for s in sectors],
            "brief": BRIEF_TYPES[brief_type],
            "today": self.today.isoformat(),
        }
        tools = self.market.definitions()
        messages: list = [{"role": "user", "content": json.dumps(watch)}]
        sources: list[dict] = []
        results: list[dict] = []
        summary = ""
        for _ in range(MAX_RESEARCH_ROUNDS):
            response = self._model("research", self.research_model, RESEARCH_SYSTEM, messages, tools=tools)
            messages.append({"role": "assistant", "content": [_block(b) for b in response.content]})
            if response.stop_reason != "tool_use":
                summary = "".join(b.text for b in response.content if b.type == "text").strip()
                break
            replies = []
            for b in response.content:
                if b.type != "tool_use":
                    continue
                out = self._tool(self.market, b.name, dict(b.input or {}))
                results.append({"tool": b.name, "input": dict(b.input or {}), "output": out})
                for item in out.get("results", []) if isinstance(out, dict) else []:
                    sources.append({k: item.get(k) for k in ("title", "url", "source", "published")})
                replies.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": json.dumps(out),
                        "is_error": "error" in out,
                    }
                )
            messages.append({"role": "user", "content": replies})
        else:
            summary = "Research stopped after the round limit."
        return {"summary": summary, "sources": sources, "tool_results": results, "watch_list_sent": watch}

    def draft(
        self, context: str, brief_type: str, note: str | None, previous: dict | None, issues: list[str]
    ) -> dict:
        task = f"Prepare {BRIEF_TYPES[brief_type]}."
        if note:
            task += f"\nThe advisor's note: {note}"
        content: list[dict] = [
            # The large, shared part first and marked cacheable: the revision call reads it from the cache.
            {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": task},
        ]
        if previous is not None:
            content.append(
                {
                    "type": "text",
                    "text": "Your previous draft:\n"
                    + json.dumps(previous)
                    + "\n\nReviewer's notes to fix:\n- "
                    + "\n- ".join(issues),
                }
            )
        response = self._model(
            "finalyst",
            self.finalyst_model,
            FINALYST_SYSTEM,
            [{"role": "user", "content": content}],
            BRIEF_SCHEMA,
        )
        return self._json(response)

    def review(self, context: str, brief: dict, known: list[float]) -> dict:
        figures = unsupported_figures(brief, known)
        response = self._model(
            "review",
            self.research_model,
            REVIEW_SYSTEM,
            [{"role": "user", "content": context + "\n\n<brief>\n" + json.dumps(brief) + "\n</brief>"}],
            REVIEW_SCHEMA,
        )
        verdict = self._json(response)
        issues = list(verdict.get("issues", [])) + figures
        approved = bool(verdict.get("approved")) and not figures
        self.trace.add(
            "note",
            "review",
            response={"approved": approved, "issues": issues, "unsupported_figures": figures},
            is_error=not approved,
        )
        return {"approved": approved, "issues": issues, "unsupported_figures": figures}

    # --- the run -----------------------------------------------------------------------------------------

    def run(self, client_id: int, brief_type: str, note: str | None = None) -> BriefResult:
        if brief_type not in BRIEF_TYPES:
            raise FinalystError("unknown brief type")
        self.on_stage("checking")
        if note and self.guard is not None:
            with self.trace.timed() as timing:
                verdict = self.guard.check(note)
            self.trace.add(
                "scope_check",
                getattr(self.guard, "model", "scope check"),
                timing=timing,
                request={"note": note},
                response={"category": verdict.category, "reason": verdict.reason},
                is_error=verdict.category == "error",
                usage=usage_of(verdict.usage) if verdict.usage is not None else None,
            )
            if not verdict.allowed:
                stop = {"out_of_scope": "blocked_scope", "manipulation": "blocked_manipulation"}.get(
                    verdict.category, "guard_error"
                )
                return BriefResult(stop, message=verdict.reply)

        self.on_stage("facts")
        facts = self.gather_facts(client_id, brief_type)

        self.on_stage("research")
        with ThreadPoolExecutor(max_workers=2) as pool:
            research_job = pool.submit(self.research, facts, brief_type)
            analytics_job = pool.submit(self.run_analytics, facts)
            analytics, research = analytics_job.result(), research_job.result()

        context = (
            "<facts>\n" + json.dumps(facts, default=str) + "\n</facts>\n"
            "<analytics>\n" + json.dumps(analytics, default=str) + "\n</analytics>\n"
            "<research_summary>\n" + research["summary"] + "\n</research_summary>\n"
            "<research_sources>\n" + json.dumps(research["sources"], default=str) + "\n</research_sources>"
        )
        known = known_numbers(facts, analytics, research["tool_results"], research["summary"])

        self.on_stage("drafting")
        brief = self.draft(context, brief_type, note, None, [])
        self.on_stage("reviewing")
        review = self.review(context, brief, known)
        revised = False
        if not review["approved"]:
            self.on_stage("revising")
            brief = self.draft(context, brief_type, note, brief, review["issues"])
            review = self.review(context, brief, known)
            revised = True

        brief["disclaimer"] = DISCLAIMER
        brief["sources"] = _cited_sources(brief, research["sources"])
        return BriefResult("done", brief, {**review, "revised": revised})


def _cited_sources(brief: dict, sources: list[dict]) -> list[dict]:
    """The news articles the brief actually cites, once each (not every search result)."""
    cited = {
        e.get("url") for s in brief.get("suggestions", []) for e in s.get("evidence", []) if e.get("url")
    }
    seen, out = set(), []
    for s in sources:
        if s.get("url") in cited and s["url"] not in seen:
            seen.add(s["url"])
            out.append(s)
    return out


def _block(block: Any) -> dict:
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    return {k: v for k, v in vars(block).items() if v is not None}
