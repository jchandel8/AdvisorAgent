"""The agent loop: send the conversation to Claude, run any tools it asks for, repeat until it answers.

Security: the advisor_id comes from the session (the CLI flag now, the verified login token later).
The model never sees or supplies it. Every tool call goes through execute_tool(), which validates the
model's input and injects the session's advisor_id.

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

from wealth.agent.answer_cache import AnswerCache
from wealth.agent.prompts import system_prompt
from wealth.config import get_settings
from wealth.db import connection
from wealth.tools.registry import execute_tool, tool_definitions

MAX_TOOL_ROUNDS = 10  # hard stop on runaway loops (cost control)
MAX_TOKENS = 16000
EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # re-runs a declined request on another model, server-side
# Server-side fallback exists for these models on the Claude API (not Haiku; not on Bedrock).
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

    @property
    def from_cache(self) -> bool:
        return self.stop_reason == "cache_hit"


class AdvisorAgent:
    """One conversation for one advisor. `client` is an anthropic.Anthropic (or a test fake)."""

    def __init__(
        self,
        advisor_id: int,
        client: Any,
        *,
        model: str | None = None,
        today: date | None = None,
        cache: AnswerCache | None = None,
        conn: psycopg.Connection | None = None,  # tests pass one; otherwise pool connections are used
    ):
        self.advisor_id = advisor_id
        self.client = client
        self.model = model or get_settings().anthropic_model
        self.today = today or date.today()
        self.cache = cache
        self.conn = conn
        self.history: list[dict] = []  # exactly what is sent to the model (append-only)
        self.transcript: list[str] = []  # questions and final answers only (the answer-cache key)
        self._system = [
            {"type": "text", "text": system_prompt(self.today), "cache_control": {"type": "ephemeral"}}
        ]
        self._tools = tool_definitions()
        self._prompt_fingerprint = hashlib.sha256(
            json.dumps([self._system[0]["text"], self._tools], sort_keys=True).encode()
        ).hexdigest()

    @contextmanager
    def _write_conn(self) -> Iterator[psycopg.Connection]:
        if self.conn is not None:
            yield self.conn
            return
        with connection() as c, c.transaction():
            yield c

    def ask(self, question: str) -> TurnResult:
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
                return TurnResult(cached, "cache_hit")

        result = self._run_model(question)

        if key is not None and result.stop_reason == "end_turn" and result.text:
            with self._write_conn() as c:
                self.cache.put(
                    c, key, advisor_id=self.advisor_id, model=self.model, answer=result.text, today=self.today
                )
        return result

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
        if self.model in FALLBACK_MODELS:
            options["betas"] = [FALLBACK_BETA]
            options["fallbacks"] = "default"
        return options

    def _run_model(self, question: str) -> TurnResult:
        self.history.append({"role": "user", "content": question})
        calls: list[ToolCall] = []
        usage = Usage()
        options = self._request_options()

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.beta.messages.create(messages=self.history, **options)
            usage.add(getattr(response, "usage", None))
            # Append the full content (thinking + text + tool_use blocks) unchanged: history is append-only.
            self.history.append({"role": "assistant", "content": response.content})

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

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                output = execute_tool(
                    block.name, block.input, advisor_id=self.advisor_id, today=self.today, conn=self.conn
                )
                is_error = "error" in output
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
