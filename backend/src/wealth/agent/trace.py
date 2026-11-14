"""Full traces of agent runs, for the admin portal's Agent runs screen.

A Tracer collects every step of one run in memory (scope check, each model call, each tool call with its exact
arguments and result, notes such as an answer-cache hit) and saves the run and its steps in one transaction
at the end. Admins can then see exactly what the agent did, with real values, for any question.

What is stored and what isn't:
- stored: arguments the model sent, results the tools returned (client data included), text the model wrote,
  tool calls it asked for, stop reasons, tokens, cache use, timings, errors;
- never stored: internal MCP tokens, API keys, passwords (keys with those names are removed before saving),
  and model "signature" blobs (opaque, large, useless to a reader);
- system prompts are stored once per version in agent_prompts, not in every run;
- each payload is capped at 64 KB (marked truncated); runs older than TRACE_RETENTION_DAYS are deleted.

Opening a trace in the admin portal is itself audited (see routes_admin.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg

MAX_PAYLOAD_BYTES = 64 * 1024
SECRET_KEYS = {
    "authorization",
    "api_key",
    "x-api-key",
    "access_token",
    "id_token",
    "token",
    "password",
    "secret",
}

# USD per million tokens: (input, output, cache read). Cache writes (5-minute TTL) cost 1.25x input.
# Source: the Claude API model reference (Claude API prices). Models not listed (for example the Bedrock
# models used on AWS) are recorded without a cost rather than with a guessed one.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),  # prompts up to 100K tokens
}
CACHE_WRITE_MULTIPLIER = 1.25


def retention_days() -> int:
    return int(os.environ.get("TRACE_RETENTION_DAYS", "").strip() or 30)


def cost_usd(model: str, usage: dict) -> Decimal | None:
    price = PRICES.get(model)
    if price is None:
        return None
    inp, out, read = price
    total = (
        usage.get("input_tokens", 0) * inp
        + usage.get("output_tokens", 0) * out
        + usage.get("cache_read_tokens", 0) * read
        + usage.get("cache_write_tokens", 0) * inp * CACHE_WRITE_MULTIPLIER
    ) / 1_000_000
    return Decimal(str(round(total, 6)))


def usage_of(response_usage: Any) -> dict:
    """Token counts from an API usage object (or a test fake) as plain ints."""

    def get(name: str) -> int:
        return int(getattr(response_usage, name, 0) or 0) if response_usage is not None else 0

    return {
        "input_tokens": get("input_tokens"),
        "output_tokens": get("output_tokens"),
        "cache_read_tokens": get("cache_read_input_tokens"),
        "cache_write_tokens": get("cache_creation_input_tokens"),
    }


def clean(value: Any) -> Any:
    """A JSON-safe copy without secrets or signature blobs."""
    if isinstance(value, dict):
        if value.get("type") == "redacted_thinking":  # an encrypted blob: nothing readable to keep
            return {"type": "redacted_thinking"}
        out = {}
        for k, v in value.items():
            key = str(k)
            if key.lower() in SECRET_KEYS:
                out[key] = "[removed]"
            elif key == "signature" and value.get("type") == "thinking":
                continue  # opaque, large, useless to a reader
            else:
                out[key] = clean(v)
        return out
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "model_dump"):
        return clean(value.model_dump(mode="json", exclude_none=True))
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return clean({k: v for k, v in vars(value).items() if not k.startswith("_")})
    return str(value)


def capped(value: Any) -> tuple[Any, bool]:
    """(payload, truncated). Over 64 KB, the payload becomes a preview string of its JSON."""
    if value is None:
        return None, False
    cleaned = clean(value)
    text = json.dumps(cleaned, ensure_ascii=False)
    if len(text.encode()) <= MAX_PAYLOAD_BYTES:
        return cleaned, False
    return {"truncated_preview": text.encode()[:MAX_PAYLOAD_BYTES].decode(errors="ignore")}, True


def prompt_hash(role: str, text: str, tools: list | None) -> str:
    return hashlib.sha256(json.dumps([role, text, tools], sort_keys=True).encode()).hexdigest()


@dataclass
class Step:
    kind: str
    name: str
    started_at: datetime
    duration_ms: int
    request: Any = None
    response: Any = None
    is_error: bool = False
    stop_reason: str | None = None
    usage: dict | None = None


@dataclass
class Tracer:
    feature: str
    advisor_id: int
    question: str
    focus_client_id: int | None = None
    steps: list[Step] = field(default_factory=list)
    prompts: dict[str, tuple[str, str, list | None]] = field(default_factory=dict)
    prompt_ref: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def prompt(self, role: str, text: str, tools: list | None = None, *, main: bool = False) -> str:
        h = prompt_hash(role, text, tools)
        self.prompts[h] = (role, text, tools)
        if main:
            self.prompt_ref = h
        return h

    @contextmanager
    def timed(self):
        """with tracer.timed() as t: ...  then tracer.add(..., timing=t)"""
        timing = {"started_at": datetime.now(UTC), "t0": time.perf_counter()}
        yield timing
        timing["duration_ms"] = int((time.perf_counter() - timing["t0"]) * 1000)

    def add(self, kind: str, name: str, *, timing: dict | None = None, **fields) -> None:
        timing = timing or {"started_at": datetime.now(UTC), "duration_ms": 0}
        self.steps.append(
            Step(
                kind=kind,
                name=name,
                started_at=timing["started_at"],
                duration_ms=timing.get("duration_ms", 0),
                **fields,
            )
        )

    def totals(self) -> dict:
        t = {"model_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0}
        t |= {"cache_read_tokens": 0, "cache_write_tokens": 0}
        cost: Decimal | None = Decimal(0)
        for s in self.steps:
            if s.kind == "tool":
                t["tool_calls"] += 1
            if s.kind in ("model", "scope_check") and s.usage:
                t["model_calls"] += 1
                for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
                    t[k] += s.usage.get(k, 0)
                step_cost = cost_usd(s.name, s.usage)
                cost = None if cost is None or step_cost is None else cost + step_cost
        t["cost_usd"] = cost if t["model_calls"] else None
        return t

    def save(
        self,
        conn: psycopg.Connection,
        *,
        outcome: str,
        answer: str | None = None,
        model: str | None = None,
        assistant_event_id: int | None = None,
        conversation_id: Any = None,
    ) -> int:
        conn.execute(
            "DELETE FROM agent_runs WHERE started_at < now() - make_interval(days => %s)", (retention_days(),)
        )
        for h, (role, text, tools) in self.prompts.items():
            conn.execute(
                "INSERT INTO agent_prompts (hash, role, text, tools) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (hash) DO NOTHING",
                (h, role, text, json.dumps(tools) if tools is not None else None),
            )
        t = self.totals()
        run_id = conn.execute(
            """INSERT INTO agent_runs (feature, advisor_id, focus_client_id, assistant_event_id, conversation_id,
                   prompt_hash, question, answer, outcome, model, started_at, finished_at, model_calls, tool_calls,
                   input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd)
               VALUES (%(feature)s, %(advisor)s, %(focus)s, %(event)s, %(conv)s, %(prompt)s, %(question)s,
                   %(answer)s, %(outcome)s, %(model)s, %(started)s, now(), %(model_calls)s, %(tool_calls)s,
                   %(input_tokens)s, %(output_tokens)s, %(cache_read_tokens)s, %(cache_write_tokens)s, %(cost_usd)s)
               RETURNING id""",
            {
                "feature": self.feature,
                "advisor": self.advisor_id,
                "focus": self.focus_client_id,
                "event": assistant_event_id,
                "conv": conversation_id,
                "prompt": self.prompt_ref,
                "question": self.question[:4000],
                "answer": answer,
                "outcome": outcome,
                "model": model,
                "started": self.started_at,
                **t,
            },
        ).fetchone()
        run_id = run_id["id"] if isinstance(run_id, dict) else run_id[0]
        rows = []
        for seq, s in enumerate(self.steps, start=1):
            request, cut_req = capped(s.request)
            response, cut_resp = capped(s.response)
            u = s.usage or {}
            rows.append(
                (
                    run_id,
                    seq,
                    s.kind,
                    s.name,
                    s.started_at,
                    s.duration_ms,
                    json.dumps(request) if request is not None else None,
                    json.dumps(response) if response is not None else None,
                    cut_req or cut_resp,
                    s.is_error,
                    s.stop_reason,
                    u.get("input_tokens"),
                    u.get("output_tokens"),
                    u.get("cache_read_tokens"),
                    u.get("cache_write_tokens"),
                )
            )
        if rows:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO agent_steps (run_id, seq, kind, name, started_at, duration_ms, request, response,
                           truncated, is_error, stop_reason, input_tokens, output_tokens, cache_read_tokens,
                           cache_write_tokens)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    rows,
                )
        return run_id
