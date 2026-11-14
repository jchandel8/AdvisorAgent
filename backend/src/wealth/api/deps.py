"""Request dependencies: database connections, the signed-in user, the Claude client.

Identity, by AUTH_MODE:
- cognito: a verified Cognito access token (`Authorization: Bearer ...`), see api/cognito.py. Required on AWS.
- demo: a LOCAL-ONLY stand-in that reads `X-Demo-User: advisor:<id>` or `client:<id>`. The API refuses to
  start (and refuses every request) in demo mode on AWS.
Either way the person must exist in the database, and every query is still limited by account_access.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import psycopg
from fastapi import Depends, Header, HTTPException, status

from wealth.access import Viewer
from wealth.api.cognito import NotSetUp, TokenError, signing_key, verify_access_token
from wealth.config import get_settings, running_on_aws
from wealth.db import connection, read_only
from wealth.llm import make_client

DEMO_HEADER = re.compile(r"^(advisor|client|admin):([1-9][0-9]{0,8})$")


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
def _llm_client() -> Any:
    return make_client(get_settings())


def get_llm_client() -> Any:
    """Anthropic API locally, Amazon Bedrock on AWS (LLM_PROVIDER). Tests override it with a fake."""
    return _llm_client()


TABLE_FOR = {"advisor": "advisors", "client": "clients", "admin": "admins"}


@dataclass(frozen=True)
class CurrentUser:
    kind: str  # advisor | client | admin
    id: int
    name: str

    @property
    def viewer(self) -> Viewer:
        """For data queries. Only advisors and clients see account data (Viewer rejects anything else)."""
        return Viewer(self.kind, self.id)

    @property
    def portal(self) -> str:
        return f"/{self.kind}"


def demo_auth_allowed() -> bool:
    return get_settings().demo_auth_enabled and not running_on_aws()


def get_key_resolver():
    """How token signing keys are found (Cognito JWKS). Tests override this with a local test key."""
    return signing_key


def current_user(
    authorization: str | None = Header(default=None),
    x_demo_user: str | None = Header(default=None),
    conn: psycopg.Connection = Depends(get_conn),
    key_resolver=Depends(get_key_resolver),
) -> CurrentUser:
    settings = get_settings()
    if settings.auth_mode == "cognito":
        return _cognito_user(authorization, conn, key_resolver)
    return _demo_user(x_demo_user, conn)


def _cognito_user(authorization: str | None, conn: psycopg.Connection, key_resolver) -> CurrentUser:
    """Identity comes ONLY from a verified Cognito access token (CLAUDE.md: the one security rule)."""
    s = get_settings()
    if not (s.cognito_issuer and s.cognito_client_id):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in is not configured.")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in first.")
    try:
        ident = verify_access_token(
            token.strip(), issuer=s.cognito_issuer, client_id=s.cognito_client_id, key_resolver=key_resolver
        )
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your sign-in has expired or isn't valid.") from exc
    except NotSetUp as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    table = TABLE_FOR[ident.kind]  # fixed by verify_access_token
    row = conn.execute(
        f"SELECT id, first_name || ' ' || last_name AS name FROM {table} WHERE username = %s",
        (ident.username,),
    ).fetchone()
    if row is None:
        # Signed in fine, but not provisioned: 403 (not 401) and say exactly what is missing.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"The login '{ident.username}' is in the {ident.kind}s group, but there is no {ident.kind} with the "
            f"username '{ident.username}' in AdvisorAgent.",
        )
    return CurrentUser(ident.kind, row["id"], row["name"])


def _demo_user(x_demo_user: str | None, conn: psycopg.Connection) -> CurrentUser:
    """Local-only stand-in: refused when not enabled or when running on AWS."""
    if not demo_auth_allowed():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in is not configured.")
    match = DEMO_HEADER.match(x_demo_user or "")
    if match is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Choose a demo user first.")
    kind, person_id = match.group(1), int(match.group(2))
    table = TABLE_FOR[kind]  # fixed by the regex above
    row = conn.execute(
        f"SELECT first_name || ' ' || last_name AS name FROM {table} WHERE id = %s", (person_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user.")
    return CurrentUser(kind, person_id, row["name"])


def require_advisor(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.kind != "advisor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This portal is for advisors.")
    return user


def require_client(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.kind != "client":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This portal is for clients.")
    return user


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.kind != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This portal is for administrators.")
    return user
