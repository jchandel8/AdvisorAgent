"""The agent loop: send the conversation to Claude, run any tools it asks for, repeat until it answers.

Security: the advisor_id comes from the session (the verified login token; the CLI flag in the terminal).
The model never sees or supplies it. Tools run through a ToolRunner (wealth/mcp/client.py): in the app,
the Portfolio MCP server, which receives the advisor in a signed internal token; in tests and the CLI,
directly. Both end in execute_tool(), which validates the model's input and injects the advisor_id.

Cost controls:
- Answer cache (ours): an exact repeat of a conversation for the same advisor and permissions is answered
  from the database with no model call. See answer_cache.py.
- Prompt caching (Anthropic): the tools + system prompt and the growing conversation are marked cacheable,
  so later requests in the loop re-read them at a fraction of the input price (5-minute TTL).
- At most MAX_TOOL_ROUNDS model calls per question.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import psycopg

from wealth.access import Viewer, accessible_client_name
from wealth.agent.answer_cache import AnswerCache
from wealth.agent.guard import UNVERIFIED_REPLY, ScopeGuard, unverified_figures
from wealth.agent.prompts import SYSTEM_PROMPT, date_note
from wealth.agent.trace import Tracer, usage_of
from wealth.config import get_settings
from wealth.db import connection, read_only
from wealth.mcp.client import LocalToolRunner, McpToolRunner, ToolRunner

MAX_TOOL_ROUNDS = 10  # hard stop on runaway loops (cost control)
MAX_TOKENS = 16000
EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # re-runs a declined request on another model, server-side
# Server-side fallback exists for these models on the Claude API only (not Haiku; not on Bedrock, where the
# Bedrock model IDs never match this set and the provider check below turns it off as well).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-1"}


@dataclass
class ToolCall:
    name: str
    input: dict
    is_error: bool


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    model_calls: int = 0

    def add(self, usage: Any) -> None:
        self.model_calls += 1
        for name in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            setattr(self, name, getattr(self, name) + (getattr(usage, name, 0) or 0))


@dataclass
class TurnResult:
    text: str
    stop_reason: str  # end_turn, max_tokens, refusal, tool_limit, or cache_hit
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    guard_reason: str | None = None  # why a guardrail blocked the question or answer

    @property
    def blocked(self) -> bool:
        return self.stop_reason.startswith("blocked") or self.stop_reason == "guard_error"

    @property
    def from_cache(self) -> bool:
        return self.stop_reason == "cache_hit"


class AdvisorAgent:
    """One conversation for one advisor. `client` is an Anthropic or AnthropicBedrock (or a test fake)."""

    def __init__(
        self,
        advisor_id: int,
        client: Any,
        *,
        model: str | None = None,
        today: date | None = None,
        cache: AnswerCache | None = None,
        conn: psycopg.Connection | None = None,  # tests pass one; otherwise pool connections are used
        history: list[dict] | None = None,  # resume a stored conversation
        transcript: list[str] | None = None,
        guard: ScopeGuard | None = None,  # scope check before the main model (None = off, e.g. some tests)
        advisor_name: str | None = None,  # shown to the scope check so it can spot other advisors' names
        tools: ToolRunner | None = None,  # default: MCP in the app; local when a test connection is given
        trace: Tracer | None = None,  # records every step for the admin portal (None = not traced)
    ):
        self.advisor_id = advisor_id
        self.client = client
        settings = get_settings()
        self.model = model or settings.anthropic_model
        self.fallbacks = settings.llm_provider == "anthropic"  # server-side fallback is Claude API only
        self.today = today or date.today()
        self.cache = cache
        self.guard = guard
        self.advisor_name = advisor_name
        self.conn = conn
        # history: exactly what is sent to the model (append-only, JSON-serializable so it can be stored).
        # transcript: questions and final answers only (the answer-cache key).
        self.history: list[dict] = list(history or [])
        self.transcript: list[str] = list(transcript or [])
        self._system = [
            # Breakpoint at the end of the fixed prefix (tools + system): every request reads it from the cache.
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ]
        self.tools = tools or (LocalToolRunner(conn) if conn is not None else McpToolRunner())
        self._tools = self.tools.definitions()
        self._prompt_fingerprint = hashlib.sha256(
            json.dumps([self._system[0]["text"], self._tools], sort_keys=True).encode()
        ).hexdigest()
        self.trace = trace
        if trace is not None:
            trace.prompt("assistant", SYSTEM_PROMPT, self._tools, main=True)

    @contextmanager
    def _write_conn(self) -> Iterator[psycopg.Connection]:
        if self.conn is not None:
            yield self.conn
            return
        with connection() as c, c.transaction():
            yield c

    @contextmanager
    def _read_conn(self) -> Iterator[psycopg.Connection]:
        if self.conn is not None:
            yield self.conn
            return
        with read_only() as c:
            yield c

    def _focus_client_name(self, client_id: int) -> str | None:
        """The client's name if this advisor shares at least one account with them, else None."""
        with self._read_conn() as c:
            return accessible_client_name(c, Viewer("advisor", self.advisor_id), client_id)

    def ask(self, question: str, *, focus_client_id: int | None = None) -> TurnResult:
        """Answer one question. focus_client_id = the client picked in the UI (verified here, never trusted)."""
        raw_question, focus_name = question, None
        notes = [date_note(self.today)]
        if focus_client_id is not None:
            name = focus_name = self._focus_client_name(focus_client_id)
            if name is None:
                return TurnResult("I can't find that client among the clients you can access.", "not_found")
            notes.append(
                f"[Selected client: {name} (client ID {focus_client_id}). Only this client's data is available. "
                f"If the question is about anyone else, say that {name} is selected and the advisor can choose "
                f"'All your clients' to ask about others.]"
            )
        question = "\n".join(notes) + f"\n\n{question}"
        key = None
        if self.cache is not None:
            with self._write_conn() as c:
                key = self.cache.make_key(
                    c,
                    advisor_id=self.advisor_id,
                    model=self.model,
                    today=self.today,
                    prompt_fingerprint=self._prompt_fingerprint,
                    transcript=[*self.transcript, question],
                )
                cached = self.cache.get(c, key)
            if cached is not None:
                self._record(question, cached, [{"type": "text", "text": cached}])
                if self.trace is not None:
                    self.trace.add(
                        "cache", "answer_cache", request={"question": question}, response={"answer": cached}
                    )
                return TurnResult(cached, "cache_hit")

        # Guardrail 1: scope check. Cached answers above already passed it when they were first asked.
        if self.guard is not None:
            recent = [_without_notes(t) for t in self.transcript[-4:]]
            with _timed(self.trace) as timing:
                verdict = self.guard.check(
                    raw_question, recent=recent, focus=focus_name, advisor=self.advisor_name
                )
            if self.trace is not None:
                self.trace.add(
                    "scope_check",
                    getattr(self.guard, "model", "scope check"),
                    timing=timing,
                    request={"question": raw_question, "recent": recent, "focus": focus_name},
                    response={"category": verdict.category, "reason": verdict.reason},
                    is_error=verdict.category == "error",
                    usage=usage_of(verdict.usage) if verdict.usage is not None else None,
                )
            if not verdict.allowed:
                stop = {"out_of_scope": "blocked_scope", "manipulation": "blocked_manipulation"}.get(
                    verdict.category, "guard_error"
                )
                return TurnResult(verdict.reply, stop, guard_reason=verdict.reason)

        start_history, start_transcript = len(self.history), len(self.transcript)
        result = self._run_model(question, focus_client_id)

        # Guardrail 2: figures in an answer must come from looked-up data. If not, drop the whole turn
        # from the history so the model never builds on it, and reply with a fixed message.
        if result.stop_reason == "end_turn" and unverified_figures(result.text, self._tools_used()):
            if self.trace is not None:
                self.trace.add(
                    "note",
                    "answer_check",
                    response={
                        "blocked": True,
                        "reason": "figures without any data lookup",
                        "answer": result.text,
                    },
                    is_error=True,
                )
            del self.history[start_history:]
            del self.transcript[start_transcript:]
            return TurnResult(
                UNVERIFIED_REPLY,
                "blocked_unverified",
                result.tool_calls,
                result.usage,
                guard_reason="figures without any data lookup",
            )

        if key is not None and result.stop_reason == "end_turn" and result.text:
            with self._write_conn() as c:
                self.cache.put(
                    c, key, advisor_id=self.advisor_id, model=self.model, answer=result.text, today=self.today
                )
        return result

    def _tools_used(self) -> bool:
        """Whether any tool has returned data in this conversation (so figures can come from it)."""
        return any(
            isinstance(m.get("content"), list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"])
            for m in self.history
            if m.get("role") == "user"
        )

    def _record(self, question: str, answer: str, assistant_content: Any) -> None:
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": assistant_content})
        self.transcript += [question, answer]

    def _request_options(self) -> dict:
        options: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": self._system,
            "tools": self._tools,
            "output_config": {"effort": EFFORT},
            # Top-level cache_control caches everything up to the last block of the conversation.
            "cache_control": {"type": "ephemeral"},
        }
        if self.fallbacks and self.model in FALLBACK_MODELS:
            options["betas"] = [FALLBACK_BETA]
            options["fallbacks"] = "default"
        return options

    def _run_model(self, question: str, focus_client_id: int | None = None) -> TurnResult:
        self.history.append({"role": "user", "content": question})
        calls: list[ToolCall] = []
        usage = Usage()
        options = self._request_options()
        sent = len(self.history) - 1  # the trace records only what is new in each request

        for _ in range(MAX_TOOL_ROUNDS):
            with _timed(self.trace) as timing:
                response = self.client.beta.messages.create(messages=self.history, **options)
            usage.add(getattr(response, "usage", None))
            content = [_as_param(b) for b in response.content]
            if self.trace is not None:
                self.trace.add(
                    "model",
                    self.model,
                    timing=timing,
                    request={
                        "new_messages": self.history[sent:],
                        "earlier_messages": sent,
                        "tools": [t["name"] for t in self._tools],
                        "effort": EFFORT,
                    },
                    response={"content": content},
                    stop_reason=response.stop_reason,
                    usage=usage_of(getattr(response, "usage", None)),
                )
            # Append the full content (thinking + text + tool_use blocks) unchanged: history is append-only.
            self.history.append({"role": "assistant", "content": content})
            sent = len(self.history)

            if response.stop_reason == "refusal":
                return self._finish(
                    question, "Sorry, I can't help with that request.", "refusal", calls, usage
                )
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                text = "".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    text += "\n\n[Answer cut off: response length limit reached.]"
                return self._finish(question, text, response.stop_reason, calls, usage)

            # The selected client is re-checked before every round of tool calls (access may have been revoked).
            if focus_client_id is not None and self._focus_client_name(focus_client_id) is None:
                self.history.append({"role": "user", "content": _skipped_results(response.content)})
                text = "Your access to the selected client has changed, so I stopped. Reload and try again."
                return self._finish(question, text, "access_revoked", calls, usage)

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                with _timed(self.trace) as timing:
                    output = self.tools.call(
                        block.name,
                        block.input,
                        advisor_id=self.advisor_id,
                        today=self.today,
                        focus_client_id=focus_client_id,
                    )
                is_error = "error" in output
                if self.trace is not None:
                    self.trace.add(
                        "tool",
                        block.name,
                        timing=timing,
                        request={"input": block.input, "focus_client_id": focus_client_id},
                        response=output,
                        is_error=is_error,
                    )
                calls.append(ToolCall(block.name, dict(block.input or {}), is_error))
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(output),
                        "is_error": is_error,
                    }
                )
            # All results for one assistant turn go back in a single user message.
            self.history.append({"role": "user", "content": results})

        text = f"I stopped after {MAX_TOOL_ROUNDS} rounds of tool calls without finishing. Try a narrower question."
        return self._finish(question, text, "tool_limit", calls, usage)

    def _finish(self, question, text, stop_reason, calls, usage) -> TurnResult:
        self.transcript += [question, text]
        return TurnResult(text, stop_reason, calls, usage)


@contextmanager
def _timed(trace: Tracer | None):
    if trace is None:
        yield None
        return
    with trace.timed() as timing:
        yield timing


def _as_param(block: Any) -> dict:
    """A response content block as a plain dict that can be stored as JSON and sent back to the API."""
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    return {k: v for k, v in vars(block).items() if v is not None}  # test fakes (SimpleNamespace)


def _skipped_results(content: list) -> list[dict]:
    """tool_result blocks for tool calls we refused to run, so the stored history stays valid."""
    return [
        {"type": "tool_result", "tool_use_id": b.id, "content": "not run: access changed", "is_error": True}
        for b in content
        if b.type == "tool_use"
    ]


def _without_notes(text: str) -> str:
    """A stored question without the [Today: ...] / [Selected client: ...] notes the backend added."""
    head, sep, rest = text.partition("\n\n")
    if sep and all(line.startswith("[") and line.endswith("]") for line in head.splitlines()):
        return rest
    return text
