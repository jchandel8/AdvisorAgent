"""Live evaluation of the advisor assistant against the seeded demo database.

Usage:
    uv run python evals/run_assistant.py --dry-run        # show each question and what counts as right (free)
    uv run python evals/run_assistant.py                  # run every case (real model calls)
    uv run python evals/run_assistant.py --case client_count --case off_topic

Each case runs as a fresh conversation with the scope check on and the answer cache off. Tools run in-process
on the database in DATABASE_URL (read-only). Costs about $0.01-0.03 a case with the 5.5 models; the report
prints the measured cost and cache hit rate from the run traces. A JSON report is written to evals/results/.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from wealth.agent.guard import ScopeGuard
from wealth.agent.loop import AdvisorAgent
from wealth.agent.trace import Tracer
from wealth.config import get_settings
from wealth.evals.assistant import CASES, Oracle, fill, grade_by_claude, grade_by_code
from wealth.llm import make_client
from wealth.mcp.client import LocalToolRunner


def run_case(case, oracle, client, settings):
    question = fill(case.question, oracle)
    expect = case.expect(oracle)
    focus = case.focus(oracle) if case.focus else None
    trace = Tracer("assistant", case.advisor_id, question, focus_client_id=focus)
    agent = AdvisorAgent(
        case.advisor_id,
        client,
        guard=ScopeGuard(client),
        tools=LocalToolRunner(),
        trace=trace,
        advisor_name={1: "Danielle Johnson", 2: "Anthony Gonzalez"}.get(case.advisor_id),
    )
    started = time.monotonic()
    result = agent.ask(question, focus_client_id=focus)
    grade = grade_by_code(expect, result.text, result.blocked)
    if grade.passed and expect.rubric and not result.blocked:
        grade = grade_by_claude(client, settings.guard_model, question, result.text, expect.rubric)
    return {
        "id": case.id,
        "question": question,
        "answer": result.text,
        "outcome": result.stop_reason,
        "passed": grade.passed,
        "reasons": grade.reasons,
        "seconds": round(time.monotonic() - started, 1),
        "tools": [c.name for c in result.tool_calls],
        **{k: (float(v) if v is not None and k == "cost_usd" else v) for k, v in trace.totals().items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--case", action="append", help="run only this case id (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="print the questions and expectations only")
    args = parser.parse_args()

    settings = get_settings()
    oracle = Oracle()
    cases = [c for c in CASES if not args.case or c.id in args.case]
    if args.dry_run:
        for c in cases:
            print(f"{c.id}: {fill(c.question, oracle)}\n    {c.expect(oracle)}")
        return

    print(f"Running {len(cases)} cases with {settings.anthropic_model} (about $0.01-0.03 each)...")
    client = make_client(settings)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda c: run_case(c, oracle, client, settings), cases))

    passed = sum(r["passed"] for r in rows)
    cost = sum(r["cost_usd"] or 0 for r in rows)
    read = sum(r["cache_read_tokens"] for r in rows)
    total_in = sum(r["input_tokens"] + r["cache_read_tokens"] + r["cache_write_tokens"] for r in rows)
    for r in rows:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"{mark}  {r['id']:32} {r['seconds']:5.1f}s  {', '.join(r['reasons'])}")
    print(
        f"\n{passed}/{len(rows)} passed. Cost ${cost:.4f}. Cache hit {100 * read / max(total_in, 1):.1f}% of input."
    )

    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    path = out / f"assistant-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"model": settings.anthropic_model, "rows": rows}, indent=2, default=str))
    print(f"Report: {path}")


if __name__ == "__main__":
    main()
