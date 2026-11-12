"""Live evaluation of the assistant's scope check (calls the real model; costs about $0.01 per run).

Usage: uv run python evals/run_scope_guard.py
Scores allow/block decisions against evals/scope_guard_cases.json and lists every mistake.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic

from wealth.agent.guard import ScopeGuard
from wealth.config import get_settings


def main() -> None:
    cases = json.loads((Path(__file__).parent / "scope_guard_cases.json").read_text())
    guard = ScopeGuard(anthropic.Anthropic(api_key=get_settings().anthropic_api_key))
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=6) as pool:
        verdicts = list(
            pool.map(lambda c: guard.check(c["q"], recent=c.get("recent"), advisor="Anthony Gonzalez"), cases)
        )

    false_blocks, misses, errors = [], [], []
    for case, v in zip(cases, verdicts, strict=True):
        if v.category == "error":
            errors.append((case, v))  # fail closed: an error blocks the question
        if case["expect"] == "allow" and not v.allowed:
            false_blocks.append((case, v))
        elif case["expect"] == "block" and v.allowed:
            misses.append((case, v))

    n_allow = sum(c["expect"] == "allow" for c in cases)
    print(f"{len(cases)} cases in {time.monotonic() - started:.1f}s")
    print(f"  in-scope allowed:       {n_allow - len(false_blocks)}/{n_allow}")
    print(f"  off-topic/abuse blocked: {len(cases) - n_allow - len(misses)}/{len(cases) - n_allow}")
    print(f"  guard errors (blocked, fail closed): {len(errors)}")
    for label, rows in (("FALSE BLOCK", false_blocks), ("MISS", misses), ("ERROR (blocked)", errors)):
        for case, v in rows:
            print(f"  {label}: {case['q'][:80]!r} -> {v.category} ({v.reason})")


if __name__ == "__main__":
    main()
