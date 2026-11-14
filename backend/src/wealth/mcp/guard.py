"""The checks in front of every MCP server. Only calls made from inside this process get through.

Three independent checks, any one of which stops outside traffic:
1. No forwarding headers. Requests that came through a proxy (the AWS load balancer always adds
   X-Forwarded-For) are refused. This also matters because uvicorn runs with --proxy-headers on AWS, which
   lets X-Forwarded-For rewrite the client address, so the address check alone could be fooled.
2. A loopback client address and, through the MCP SDK's DNS-rebinding protection, a loopback Host header.
3. A valid internal token for this server (internal_token.py). This is the real control: its key never
   leaves the process.

The verified identity is put in the request scope (scope["state"]["mcp_identity"]) for the server's
handlers. Nothing in the tool arguments can change it.
"""

from __future__ import annotations

import json
import logging

from wealth.mcp.internal_token import InternalTokenError, verify

log = logging.getLogger(__name__)

LOOPBACK = {"127.0.0.1", "::1"}
PROXY_HEADERS = {b"x-forwarded-for", b"x-forwarded-host", b"x-forwarded-proto", b"forwarded", b"x-real-ip"}


class InternalOnly:
    """ASGI middleware: wraps one MCP server's app; `server` is the token audience it accepts."""

    def __init__(self, app, server: str):
        self.app = app
        self.server = server

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":  # lifespan events pass through
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        client = (scope.get("client") or ("", 0))[0]
        if PROXY_HEADERS & headers.keys() or client not in LOOPBACK:
            log.warning("MCP %s: refused a request from outside the process (client %s)", self.server, client)
            await _reply(send, 403, "MCP servers only accept calls from inside the app.")
            return
        auth = headers.get(b"authorization", b"").decode("latin-1")
        if not auth.startswith("Bearer "):
            await _reply(send, 401, "Missing internal token.")
            return
        try:
            identity = verify(auth.removeprefix("Bearer ").strip(), self.server)
        except InternalTokenError as exc:
            log.warning("MCP %s: bad internal token: %s", self.server, exc)
            await _reply(send, 401, "Invalid internal token.")
            return
        scope.setdefault("state", {})["mcp_identity"] = identity
        await self.app(scope, receive, send)


async def _reply(send, status: int, message: str) -> None:
    body = json.dumps({"error": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
