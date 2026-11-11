"""Storage for assistant conversations (one row per conversation, owned by one advisor).

The agent call can take several seconds, so no connection or row lock is held while it runs. Instead the
row's updated_at is read with the conversation and checked on save (optimistic locking): if another
request changed the conversation in the meantime, the save affects no rows and the caller reports a conflict.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb


def load(conn: psycopg.Connection, conversation_id: uuid.UUID, advisor_id: int) -> dict | None:
    """The conversation if it belongs to this advisor, else None (treated as not found)."""
    return conn.execute(
        "SELECT id, history, transcript, updated_at FROM agent_conversations WHERE id = %s AND advisor_id = %s",
        (conversation_id, advisor_id),
    ).fetchone()


def create(
    conn: psycopg.Connection, *, advisor_id: int, focus_client_id: int | None, history: list, transcript: list
) -> uuid.UUID:
    row = conn.execute(
        "INSERT INTO agent_conversations (advisor_id, focus_client_id, history, transcript)"
        " VALUES (%s, %s, %s, %s) RETURNING id",
        (advisor_id, focus_client_id, Jsonb(history), Jsonb(transcript)),
    ).fetchone()
    return row["id"]


def update(
    conn: psycopg.Connection,
    conversation_id: uuid.UUID,
    *,
    advisor_id: int,
    expected_updated_at: datetime,
    focus_client_id: int | None,
    history: list,
    transcript: list,
) -> bool:
    """Save if nobody else changed the conversation since it was loaded. Returns False on a conflict."""
    cur = conn.execute(
        "UPDATE agent_conversations"
        " SET history = %s, transcript = %s, focus_client_id = %s, updated_at = clock_timestamp()"
        " WHERE id = %s AND advisor_id = %s AND updated_at = %s",
        (
            Jsonb(history),
            Jsonb(transcript),
            focus_client_id,
            conversation_id,
            advisor_id,
            expected_updated_at,
        ),
    )
    return cur.rowcount == 1
