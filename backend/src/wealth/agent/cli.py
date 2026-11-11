"""Terminal chat with the advisor agent.

Usage: uv run wealth-agent --advisor-id 1

In week 1 the --advisor-id flag stands in for the verified login token. It is chosen at startup by
whoever runs the program, never by the model, and it is checked against the database.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import anthropic

from wealth.access import advisor_exists
from wealth.agent.answer_cache import AnswerCache
from wealth.agent.loop import AdvisorAgent
from wealth.config import get_settings
from wealth.db import close_pools, read_only


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the wealth-advisor agent.")
    parser.add_argument(
        "--advisor-id", type=int, required=True, help="the logged-in advisor (stand-in for login)"
    )
    parser.add_argument("--today", type=date.fromisoformat, help="override today's date (YYYY-MM-DD)")
    parser.add_argument("--model", help="override ANTHROPIC_MODEL for this session")
    parser.add_argument(
        "--no-cache", action="store_true", help="always call the model (skip the answer cache)"
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is not set (put it in .env).")

    with read_only() as conn:
        if not advisor_exists(conn, args.advisor_id):
            sys.exit(f"No advisor with id {args.advisor_id}. See demo_users.csv.")
        name = conn.execute(
            "SELECT first_name || ' ' || last_name AS name FROM advisors WHERE id = %s", (args.advisor_id,)
        ).fetchone()["name"]

    cache = None
    if settings.answer_cache_enabled and not args.no_cache:
        cache = AnswerCache(
            ttl=timedelta(hours=settings.answer_cache_ttl_hours),
            max_entries=settings.answer_cache_max_entries,
        )
    agent = AdvisorAgent(
        args.advisor_id,
        anthropic.Anthropic(api_key=settings.anthropic_api_key),
        model=args.model,
        today=args.today,
        cache=cache,
    )
    print(f"Signed in as advisor {args.advisor_id} ({name}). Model: {agent.model}. Today: {agent.today}.")
    print("Ask a question, or type 'exit'.\n")

    try:
        while True:
            try:
                question = input("you> ").strip()
            except EOFError:
                break
            if question.lower() in {"exit", "quit"}:
                break
            if not question:
                continue
            try:
                result = agent.ask(question)
            except anthropic.RateLimitError:
                print("Rate limited by the API. Wait a moment and try again.\n")
                continue
            except anthropic.APIStatusError as exc:
                print(f"API error {exc.status_code}: {exc.message}\n")
                continue
            except anthropic.APIConnectionError:
                print("Could not reach the API. Check your network.\n")
                continue
            for call in result.tool_calls:
                flag = "  (error)" if call.is_error else ""
                print(f"  [tool] {call.name}({call.input}){flag}")
            u = result.usage
            if result.from_cache:
                print("  [answer cache hit: no model call]")
            else:
                print(
                    f"  [{u.model_calls} model calls | input {u.input_tokens} + cache read "
                    f"{u.cache_read_input_tokens} + cache write {u.cache_creation_input_tokens} | "
                    f"output {u.output_tokens} tokens]"
                )
            print(f"\nagent> {result.text}\n")
    except KeyboardInterrupt:
        print()
    finally:
        close_pools()


if __name__ == "__main__":
    main()
