"""Answer cache: reuse a finished answer when the same advisor asks the exact same thing again.

A hit costs nothing (no model call). The cache key is a SHA-256 over:
  - the advisor ID: answers are never shared between advisors;
  - a fingerprint of the accounts the advisor can see right now: granting or revoking access changes the
    key, so an answer built on old permissions can never be served;
  - a fingerprint of the prompt and tool definitions: changing either retires old answers;
  - the model and today's date;
  - the conversation so far plus the new question (whitespace and case normalized).

Eviction: an entry expires after the TTL or at the next local midnight, whichever is first. On every
write, expired rows are deleted and, above max_entries, the least recently used rows are deleted.
Reloading the mock data (python -m wealth.datagen) empties the cache.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

import psycopg

from wealth.access import VISIBLE, Viewer

KEY_VERSION = 1


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AnswerCache:
    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(hours=24),
        max_entries: int = 1000,
        clock: Callable[[], datetime] = _utcnow,
    ):
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.ttl = ttl
        self.max_entries = max_entries
        self.clock = clock

    def make_key(
        self,
        conn: psycopg.Connection,
        *,
        advisor_id: int,
        model: str,
        today: date,
        prompt_fingerprint: str,
        transcript: list[str],
    ) -> str:
        row = conn.execute(
            f"WITH {VISIBLE} SELECT coalesce(string_agg(account_id::text, ',' ORDER BY account_id), '') AS ids"
            " FROM visible",
            Viewer("advisor", advisor_id).params(),
        ).fetchone()
        access = row["ids"] if isinstance(row, dict) else row[0]
        payload = json.dumps(
            {
                "v": KEY_VERSION,
                "advisor_id": advisor_id,
                "access": hashlib.sha256(access.encode()).hexdigest(),
                "prompt": prompt_fingerprint,
                "model": model,
                "today": today.isoformat(),
                "transcript": [_normalize(t) for t in transcript],
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, conn: psycopg.Connection, key: str) -> str | None:
        """Return the cached answer and mark it as recently used, or None on a miss or an expired entry."""
        row = conn.execute(
            "UPDATE answer_cache SET last_used_at = %(now)s, hit_count = hit_count + 1"
            " WHERE cache_key = %(key)s AND expires_at > %(now)s RETURNING answer",
            {"key": key, "now": self.clock()},
        ).fetchone()
        if row is None:
            return None
        return row["answer"] if isinstance(row, dict) else row[0]

    def put(
        self, conn: psycopg.Connection, key: str, *, advisor_id: int, model: str, answer: str, today: date
    ):
        now = self.clock()
        # Next local midnight by the real clock. Not by `today`: that can be a pinned data date in the past
        # (DATA_ANCHOR_DATE), which would make every entry expire as soon as it is written.
        local_now = now.astimezone()
        next_midnight = datetime.combine(
            local_now.date() + timedelta(days=1), time.min, tzinfo=local_now.tzinfo
        )
        expires = min(now + self.ttl, next_midnight)
        conn.execute(
            """INSERT INTO answer_cache (cache_key, advisor_id, model, answer, created_at, last_used_at, expires_at)
               VALUES (%(key)s, %(advisor_id)s, %(model)s, %(answer)s, %(now)s, %(now)s, %(expires)s)
               ON CONFLICT (cache_key) DO UPDATE
               SET answer = EXCLUDED.answer, created_at = EXCLUDED.created_at,
                   last_used_at = EXCLUDED.last_used_at, expires_at = EXCLUDED.expires_at, hit_count = 0""",
            {
                "key": key,
                "advisor_id": advisor_id,
                "model": model,
                "answer": answer,
                "now": now,
                "expires": expires,
            },
        )
        self.evict(conn)

    def evict(self, conn: psycopg.Connection) -> None:
        conn.execute("DELETE FROM answer_cache WHERE expires_at <= %s", (self.clock(),))
        conn.execute(
            """DELETE FROM answer_cache WHERE cache_key IN (
                   SELECT cache_key FROM answer_cache
                   ORDER BY last_used_at DESC, created_at DESC
                   OFFSET %s)""",
            (self.max_entries,),
        )
