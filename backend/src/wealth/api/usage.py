"""Per-advisor limits and the audit log for the assistant (table assistant_events).

Every request reserves its event row first, inside a transaction holding a per-advisor advisory lock, so
two requests arriving together can't both slip under the limit. The row's outcome is filled in afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

QUESTION_LOG_CHARS = 500
LOCK_NAMESPACE = 7310  # first key of pg_advisory_xact_lock(int, int); the second is the advisor ID


@dataclass(frozen=True)
class LimitHit:
    message: str
    retry_after_seconds: int


def reserve(
    conn: psycopg.Connection, advisor_id: int, question: str, *, per_minute: int, per_day: int
) -> tuple[int | None, LimitHit | None]:
    """Count recent requests and, if under both limits, record this one. Returns (event_id, None) or
    (None, LimitHit). Must run inside a transaction (the lock is released at commit)."""
    conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", (LOCK_NAMESPACE, advisor_id))
    row = conn.execute(
        """SELECT
             count(*) FILTER (WHERE created_at > now() - interval '1 minute') AS last_minute,
             count(*) FILTER (WHERE created_at >= date_trunc('day', now())) AS today,
             ceil(extract(epoch FROM date_trunc('day', now()) + interval '1 day' - now()))::int AS until_midnight
           FROM assistant_events
           WHERE advisor_id = %s AND outcome <> 'rate_limited'""",
        (advisor_id,),
    ).fetchone()
    last_minute, today, until_midnight = row["last_minute"], row["today"], row["until_midnight"]
    hit = None
    if today >= per_day:
        hit = LimitHit(
            f"You've reached today's limit of {per_day} questions. It resets at midnight UTC.", until_midnight
        )
    elif last_minute >= per_minute:
        hit = LimitHit(f"You can ask up to {per_minute} questions a minute. Try again shortly.", 60)
    if hit:
        _insert(conn, advisor_id, question, "rate_limited", hit.message)
        return None, hit
    return _insert(conn, advisor_id, question, "error", None), None  # outcome is set by finish()


def finish(conn: psycopg.Connection, event_id: int, outcome: str, reason: str | None = None) -> None:
    conn.execute(
        "UPDATE assistant_events SET outcome = %s, reason = %s WHERE id = %s",
        (outcome, (reason or None) and reason[:300], event_id),
    )


def _insert(
    conn: psycopg.Connection, advisor_id: int, question: str, outcome: str, reason: str | None
) -> int:
    return conn.execute(
        "INSERT INTO assistant_events (advisor_id, outcome, question, reason) VALUES (%s, %s, %s, %s) RETURNING id",
        (advisor_id, outcome, question[:QUESTION_LOG_CHARS], reason),
    ).fetchone()["id"]


def outcome_for(stop_reason: str) -> str:
    return {
        "cache_hit": "cached",
        "blocked_scope": "blocked_scope",
        "blocked_manipulation": "blocked_manipulation",
        "blocked_unverified": "blocked_unverified",
        "guard_error": "guard_error",
    }.get(stop_reason, "answered")
