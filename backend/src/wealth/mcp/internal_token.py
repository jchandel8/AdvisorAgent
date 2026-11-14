"""Short-lived signed tokens that carry the advisor's identity from the backend to an MCP server.

The model never sees these tokens and never supplies the advisor. The backend (which got the advisor from
the verified Cognito token) signs one per agent request; the MCP server verifies it and takes the advisor,
the selected client and "today" only from it.

Format: a standard JWT signed with HMAC-SHA256 (HS256). The audience names one server ("mcp:portfolio"),
so a token for one server is refused by another. Tokens live for 2 minutes.

Key: MCP_SIGNING_KEY if set; otherwise a random key made when the process starts. The servers run in the
same process as the agent (one uvicorn worker per container), so a per-process key works and there is no
secret to manage. Set MCP_SIGNING_KEY if the app ever runs several workers per container.
"""

from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import jwt

ISSUER = "advisoragent-backend"
LIFETIME_SECONDS = 120
SERVERS = ("portfolio", "analytics", "market")


class InternalTokenError(Exception):
    """Missing, malformed, expired, wrong-audience or badly signed token."""


@dataclass(frozen=True)
class McpIdentity:
    advisor_id: int | None  # None for servers that need no identity (analytics)
    focus_client_id: int | None
    today: date


@lru_cache(maxsize=1)
def _key() -> bytes:
    configured = os.environ.get("MCP_SIGNING_KEY", "").strip()
    if configured:
        if len(configured) < 32:
            raise RuntimeError("MCP_SIGNING_KEY must be at least 32 characters.")
        return configured.encode()
    return secrets.token_bytes(32)


def sign(server: str, *, advisor_id: int | None, today: date, focus_client_id: int | None = None) -> str:
    if server not in SERVERS:
        raise ValueError(f"unknown MCP server {server!r}")
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": f"mcp:{server}",
        "iat": now,
        "exp": now + LIFETIME_SECONDS,
        "today": today.isoformat(),
    }
    if advisor_id is not None:
        claims["sub"] = str(advisor_id)
    if focus_client_id is not None:
        claims["focus_client_id"] = focus_client_id
    return jwt.encode(claims, _key(), algorithm="HS256")


def verify(token: str, server: str) -> McpIdentity:
    try:
        claims = jwt.decode(
            token,
            _key(),
            algorithms=["HS256"],  # never "none", never an algorithm chosen by the token
            audience=f"mcp:{server}",
            issuer=ISSUER,
            options={"require": ["iss", "aud", "iat", "exp", "today"]},
        )
        advisor = claims.get("sub")
        focus = claims.get("focus_client_id")
        return McpIdentity(
            advisor_id=int(advisor) if advisor is not None else None,
            focus_client_id=int(focus) if focus is not None else None,
            today=date.fromisoformat(claims["today"]),
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise InternalTokenError(str(exc)) from exc
