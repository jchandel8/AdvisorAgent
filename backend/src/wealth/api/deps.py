"""Request dependencies: database connections, the signed-in user, the Claude client.

Identity: until Cognito arrives (build step 3), a LOCAL-ONLY stand-in reads the demo user from the
`X-Demo-User: advisor:<id>` or `client:<id>` header. It works only when DEMO_AUTH_ENABLED=true, and the
API refuses to start (and refuses every request) with it enabled on AWS. Whatever the header says, the
person must exist in the database, and every query is still limited by account_access.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import anthropic
import psycopg
from fastapi import Depends, Header, HTTPException, status

from wealth.access import Viewer
from wealth.config import get_settings, running_on_aws
from wealth.db import connection, read_only

DEMO_HEADER = re.compile(r"^(advisor|client):([1-9][0-9]{0,8})$")


def get_conn() -> Iterator[psycopg.Connection]:
    """Read-only connection for portal queries."""
    with read_only() as conn:
        yield conn


def get_write_conn() -> Iterator[psycopg.Connection]:
    """Read-write connection (conversation storage). Committed when the request succeeds."""
    with connection() as conn, conn.transaction():
        yield conn


def get_agent_conn() -> psycopg.Connection | None:
    """None in production: the agent opens its own read-only connections per tool call. Tests override."""
    return None


@lru_cache(maxsize=1)
def _anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def get_llm_client() -> Any:
    return _anthropic_client()


@dataclass(frozen=True)
class CurrentUser:
    viewer: Viewer
    name: str

    @property
    def portal(self) -> str:
        return f"/{self.viewer.kind}"


def demo_auth_allowed() -> bool:
    return get_settings().demo_auth_enabled and not running_on_aws()


def current_user(
    x_demo_user: str | None = Header(default=None),
    conn: psycopg.Connection = Depends(get_conn),
) -> CurrentUser:
    if not demo_auth_allowed():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in is not configured.")
    match = DEMO_HEADER.match(x_demo_user or "")
    if match is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Choose a demo user first.")
    kind, person_id = match.group(1), int(match.group(2))
    table = "advisors" if kind == "advisor" else "clients"  # fixed by the regex above
    row = conn.execute(
        f"SELECT first_name || ' ' || last_name AS name FROM {table} WHERE id = %s", (person_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user.")
    return CurrentUser(Viewer(kind, person_id), row["name"])


def require_advisor(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.viewer.kind != "advisor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This portal is for advisors.")
    return user


def require_client(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.viewer.kind != "client":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This portal is for clients.")
    return user
