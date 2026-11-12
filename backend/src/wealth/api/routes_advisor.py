"""Advisor portal API. The advisor is always the signed-in user.

A client_id in a URL or request body is only a selection: every query still goes through the advisor's
account_access rows, and a client the advisor shares no account with is 404.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import date, timedelta
from typing import Any

import anthropic
import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from wealth.access import ToolContext, accessible_client_name
from wealth.agent.answer_cache import AnswerCache
from wealth.agent.guard import ScopeGuard
from wealth.agent.loop import AdvisorAgent
from wealth.api import conversations, queries, usage
from wealth.api.deps import CurrentUser, get_agent_conn, get_conn, get_llm_client, require_advisor
from wealth.config import get_settings
from wealth.db import connection
from wealth.tools.clients import get_my_clients
from wealth.tools.schemas import NoInput

router = APIRouter(prefix="/api/advisor", tags=["advisor"])


@router.get("/profile")
def profile(user: CurrentUser = Depends(require_advisor), conn=Depends(get_conn)):
    return queries.advisor_profile(conn, user.viewer.id)


@router.get("/clients")
def clients(user: CurrentUser = Depends(require_advisor), conn=Depends(get_conn)):
    today = date.today()
    result = get_my_clients(ToolContext(conn=conn, viewer=user.viewer, today=today), NoInput())
    return {**result, **queries.book_total(conn, user.viewer, today)}


@router.get("/clients/{client_id}/accounts")
def client_accounts(client_id: int, user: CurrentUser = Depends(require_advisor), conn=Depends(get_conn)):
    name = accessible_client_name(conn, user.viewer, client_id)
    if name is None:
        raise HTTPException(404, "Client not found.")
    return {
        "client_id": client_id,
        "name": name,
        **queries.account_list(conn, user.viewer, date.today(), client_id=client_id),
    }


# --- Advanced Assistant -------------------------------------------------------------------------------


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
    client_id: int | None = Field(default=None, gt=0, description="Client selected in the dropdown, if any.")


@contextmanager
def _transaction() -> Iterator[psycopg.Connection]:
    with connection() as conn, conn.transaction():
        yield conn


def get_store() -> Callable[[], AbstractContextManager[psycopg.Connection]]:
    """Factory for short write transactions (load, then save). Tests override it."""
    return _transaction


def _answer_cache() -> AnswerCache | None:
    s = get_settings()
    if not s.answer_cache_enabled:
        return None
    return AnswerCache(ttl=timedelta(hours=s.answer_cache_ttl_hours), max_entries=s.answer_cache_max_entries)


def get_guard(llm: Any = Depends(get_llm_client)) -> ScopeGuard | None:
    """The scope check (a small, fast model). Tests override it with a fake."""
    return ScopeGuard(llm) if get_settings().assistant_guard_enabled else None


@router.post("/assistant/messages")
def ask(
    body: AskBody,
    user: CurrentUser = Depends(require_advisor),
    llm: Any = Depends(get_llm_client),
    guard: ScopeGuard | None = Depends(get_guard),
    agent_conn: psycopg.Connection | None = Depends(get_agent_conn),
    store: Callable = Depends(get_store),
):
    advisor_id = user.viewer.id
    settings = get_settings()

    # Limits first: count and reserve this request before any model call (cost control, misuse).
    with store() as c:
        event_id, hit = usage.reserve(
            c,
            advisor_id,
            body.message,
            per_minute=settings.assistant_per_minute,
            per_day=settings.assistant_per_day,
        )
    if hit is not None:
        raise HTTPException(429, hit.message, headers={"Retry-After": str(hit.retry_after_seconds)})

    history, transcript, updated_at = [], [], None
    if body.conversation_id is not None:
        with store() as c:
            conv = conversations.load(c, body.conversation_id, advisor_id)
        if conv is None:
            with store() as c:
                usage.finish(c, event_id, "error", "conversation not found")
            raise HTTPException(404, "Conversation not found.")
        history, transcript, updated_at = conv["history"], conv["transcript"], conv["updated_at"]

    agent = AdvisorAgent(
        advisor_id,
        llm,
        cache=_answer_cache(),
        conn=agent_conn,
        history=history,
        transcript=transcript,
        guard=guard,
        advisor_name=user.name,
    )
    try:
        result = agent.ask(body.message, focus_client_id=body.client_id)
    except anthropic.RateLimitError as exc:
        with store() as c:
            usage.finish(c, event_id, "error", "upstream rate limit")
        raise HTTPException(429, "The assistant is busy. Try again in a moment.") from exc
    except anthropic.APIError as exc:
        with store() as c:
            usage.finish(c, event_id, "error", f"upstream: {type(exc).__name__}")
        raise HTTPException(502, "The assistant is unavailable right now.") from exc

    with store() as c:
        usage.finish(c, event_id, usage.outcome_for(result.stop_reason), result.guard_reason)
    if result.stop_reason == "not_found":
        raise HTTPException(404, "Client not found.")

    with store() as c:
        if body.conversation_id is None:
            conversation_id = conversations.create(
                c,
                advisor_id=advisor_id,
                focus_client_id=body.client_id,
                history=agent.history,
                transcript=agent.transcript,
            )
        else:
            conversation_id = body.conversation_id
            saved = conversations.update(
                c,
                conversation_id,
                advisor_id=advisor_id,
                expected_updated_at=updated_at,
                focus_client_id=body.client_id,
                history=agent.history,
                transcript=agent.transcript,
            )
            if not saved:
                raise HTTPException(409, "This conversation changed in another window. Reload to continue.")

    return {
        "conversation_id": conversation_id,
        "answer": result.text,
        "stop_reason": result.stop_reason,
        "from_cache": result.from_cache,
        "blocked": result.blocked,
        "tool_calls": [{"name": c.name, "input": c.input, "is_error": c.is_error} for c in result.tool_calls],
    }
