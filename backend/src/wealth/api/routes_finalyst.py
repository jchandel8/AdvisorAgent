"""AI Finalyst endpoints (advisor portal).

POST /api/advisor/finalyst/briefs        start a brief (or reuse today's identical one); returns at once
GET  /api/advisor/finalyst/briefs        your briefs, newest first (optionally for one client)
GET  /api/advisor/finalyst/briefs/{id}   one brief; poll it while status is "running" to see the stage

A run takes about a minute, so it happens in a background thread and the page polls. Every rule of the
assistant applies: the advisor comes from the verified login, the client must share an account with them
(checked here and again by every tool), limits per advisor, full trace for admins. Briefs of clients the
advisor no longer shares an account with are hidden.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from wealth.access import VISIBLE, Viewer, accessible_client_name
from wealth.agent.guard import ScopeGuard
from wealth.agent.trace import Tracer
from wealth.api.deps import CurrentUser, get_llm_client, require_advisor
from wealth.api.routes_advisor import get_store
from wealth.config import get_settings
from wealth.finalyst.workflow import BRIEF_TYPES, Finalyst, FinalystError
from wealth.mcp.client import McpToolRunner

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/advisor/finalyst", tags=["finalyst"])

BriefType = Literal["portfolio_review", "market_impact", "rebalancing", "meeting_prep"]
STALE_MINUTES = 10  # a run still "running" after this was lost (e.g. the container restarted)


class BriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: int = Field(gt=0)
    brief_type: BriefType
    note: str | None = Field(default=None, max_length=500)
    refresh: bool = False  # true: run again even if today's identical brief exists


def get_finalyst_factory(llm: Any = Depends(get_llm_client)) -> Callable[..., Finalyst]:
    """Builds the workflow with the real MCP servers. Tests override it."""
    settings = get_settings()

    def make(advisor_id: int, trace: Tracer, on_stage: Callable[[str], None]) -> Finalyst:
        return Finalyst(
            llm,
            advisor_id,
            portfolio=McpToolRunner("portfolio"),
            analytics=McpToolRunner("analytics"),
            market=McpToolRunner("market"),
            trace=trace,
            finalyst_model=settings.finalyst_model,
            research_model=settings.research_model,
            guard=ScopeGuard(llm) if settings.assistant_guard_enabled else None,
            on_stage=on_stage,
        )

    return make


def get_launcher() -> Callable[[Callable[[], None]], None]:
    """How a run is started: a background thread. Tests run it inline."""

    def launch(job: Callable[[], None]) -> None:
        threading.Thread(target=job, name="finalyst-run", daemon=True).start()

    return launch


def _fingerprint(conn, advisor_id: int, body: BriefRequest) -> str:
    row = conn.execute(
        f"WITH {VISIBLE} SELECT coalesce(string_agg(account_id::text, ',' ORDER BY account_id), '') AS ids FROM visible",
        Viewer("advisor", advisor_id).params(),
    ).fetchone()
    payload = [
        body.client_id,
        body.brief_type,
        " ".join((body.note or "").lower().split()),
        date.today().isoformat(),
        row["ids"],
    ]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


BRIEF_COLUMNS = """b.id, b.client_id, c.first_name || ' ' || c.last_name AS client_name, b.brief_type, b.note,
       b.status, b.stage, b.created_at, b.finished_at, b.error, b.brief, b.review"""

VISIBLE_CLIENT = f"""EXISTS (
    WITH {VISIBLE}
    SELECT 1 FROM visible v JOIN account_access ca ON ca.account_id = v.account_id AND ca.client_id = b.client_id
)"""


def _expire_stale(conn, advisor_id: int) -> None:
    conn.execute(
        """UPDATE finalyst_briefs SET status = 'failed', error = 'The run was interrupted. Run it again.',
                  finished_at = now()
           WHERE advisor_id = %s AND status = 'running' AND created_at < now() - make_interval(mins => %s)""",
        (advisor_id, STALE_MINUTES),
    )


@router.post("/briefs", status_code=202)
def start_brief(
    body: BriefRequest,
    user: CurrentUser = Depends(require_advisor),
    store: Callable = Depends(get_store),
    make_finalyst: Callable = Depends(get_finalyst_factory),
    launch: Callable = Depends(get_launcher),
):
    advisor_id = user.viewer.id
    settings = get_settings()
    with store() as c:
        if accessible_client_name(c, user.viewer, body.client_id) is None:
            raise HTTPException(404, "Client not found.")
        _expire_stale(c, advisor_id)
        fingerprint = _fingerprint(c, advisor_id, body)
        if not body.refresh:
            existing = c.execute(
                """SELECT id FROM finalyst_briefs WHERE advisor_id = %s AND fingerprint = %s AND status = 'done'
                   ORDER BY id DESC LIMIT 1""",
                (advisor_id, fingerprint),
            ).fetchone()
            if existing:
                return {"id": existing["id"], "status": "done", "reused": True}
        counts = c.execute(
            """SELECT count(*) FILTER (WHERE created_at > now() - interval '1 hour') AS hour,
                      count(*) FILTER (WHERE created_at > date_trunc('day', now())) AS day
               FROM finalyst_briefs WHERE advisor_id = %s""",
            (advisor_id,),
        ).fetchone()
        if counts["day"] >= settings.finalyst_per_day:
            raise HTTPException(429, f"You've reached today's limit of {settings.finalyst_per_day} briefs.")
        if counts["hour"] >= settings.finalyst_per_hour:
            raise HTTPException(
                429, f"You can run up to {settings.finalyst_per_hour} briefs an hour. Try again later."
            )
        brief_id = c.execute(
            """INSERT INTO finalyst_briefs (advisor_id, client_id, brief_type, note, stage, fingerprint)
               VALUES (%s, %s, %s, %s, 'checking', %s) RETURNING id""",
            (advisor_id, body.client_id, body.brief_type, (body.note or "").strip() or None, fingerprint),
        ).fetchone()["id"]

    def job() -> None:
        _run(brief_id, advisor_id, body, store, make_finalyst)

    launch(job)
    return {"id": brief_id, "status": "running", "reused": False}


def _run(
    brief_id: int, advisor_id: int, body: BriefRequest, store: Callable, make_finalyst: Callable
) -> None:
    question = f"{body.brief_type.replace('_', ' ')} brief" + (f": {body.note}" if body.note else "")
    trace = Tracer("finalyst", advisor_id, question, focus_client_id=body.client_id)

    def stage(name: str) -> None:
        with store() as c:
            c.execute("UPDATE finalyst_briefs SET stage = %s WHERE id = %s", (name, brief_id))

    outcome, brief, review, error = "error", None, None, None
    finalyst = make_finalyst(advisor_id, trace, stage)
    try:
        result = finalyst.run(body.client_id, body.brief_type, body.note)
        outcome, brief, review, error = result.outcome, result.brief, result.review, result.message
        if outcome == "done":
            outcome = "answered"
    except FinalystError as exc:
        error = f"The brief couldn't be prepared: {exc}."
    except Exception:
        log.exception("finalyst run %s failed", brief_id)
        error = "The brief couldn't be prepared because of an error. Try again."

    run_id = None
    try:
        with store() as c:
            run_id = trace.save(
                c,
                outcome=outcome,
                answer=(brief or {}).get("summary") or error,
                model=finalyst.finalyst_model,
            )
    except Exception:
        log.exception("could not save the Finalyst trace")
    with store() as c:
        c.execute(
            """UPDATE finalyst_briefs SET status = %s, stage = %s, brief = %s, review = %s, error = %s, run_id = %s,
                      finished_at = now() WHERE id = %s""",
            (
                "done" if brief else "failed",
                "done" if brief else None,
                json.dumps(brief) if brief else None,
                json.dumps(review) if review else None,
                error,
                run_id,
                brief_id,
            ),
        )


@router.get("/briefs")
def list_briefs(
    client_id: int | None = Query(default=None, gt=0),
    user: CurrentUser = Depends(require_advisor),
    store: Callable = Depends(get_store),
):
    with store() as c:
        _expire_stale(c, user.viewer.id)
        rows = c.execute(
            f"""SELECT {BRIEF_COLUMNS} FROM finalyst_briefs b JOIN clients c ON c.id = b.client_id
                WHERE b.advisor_id = %(viewer_id)s AND (%(client)s::int IS NULL OR b.client_id = %(client)s::int)
                  AND {VISIBLE_CLIENT}
                ORDER BY b.created_at DESC, b.id DESC LIMIT 50""",
            {**user.viewer.params(), "client": client_id},
        ).fetchall()
    for r in rows:  # the list shows the summary only
        r["summary"] = (r.pop("brief") or {}).get("summary")
        r.pop("review", None)
    return {"briefs": rows, "brief_types": BRIEF_TYPES}


@router.get("/briefs/{brief_id}")
def get_brief(
    brief_id: int, user: CurrentUser = Depends(require_advisor), store: Callable = Depends(get_store)
):
    with store() as c:
        _expire_stale(c, user.viewer.id)
        row = c.execute(
            f"""SELECT {BRIEF_COLUMNS} FROM finalyst_briefs b JOIN clients c ON c.id = b.client_id
                WHERE b.id = %(id)s AND b.advisor_id = %(viewer_id)s AND {VISIBLE_CLIENT}""",
            {**user.viewer.params(), "id": brief_id},
        ).fetchone()
    if row is None:  # not yours, or you no longer share an account with the client: the same answer
        raise HTTPException(404, "Brief not found.")
    return row
