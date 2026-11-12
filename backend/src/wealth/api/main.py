"""FastAPI app: one API for the advisor and client portals and the agent.

Run locally: uv run uvicorn wealth.api.main:app --reload
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from wealth.api import routes_admin, routes_advisor, routes_client, routes_common
from wealth.config import get_settings, running_on_aws
from wealth.db import close_pools


def check_startup_config() -> None:
    """Refuse to start in an unsafe configuration."""
    settings = get_settings()
    if settings.demo_auth_enabled and running_on_aws():
        raise RuntimeError(
            "AUTH_MODE=demo is a local-only setting and is not allowed on AWS. Use Cognito login."
        )
    if settings.auth_mode == "cognito" and not (settings.cognito_issuer and settings.cognito_client_id):
        raise RuntimeError(
            "AUTH_MODE=cognito needs COGNITO_REGION, COGNITO_USER_POOL_ID and COGNITO_CLIENT_ID."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_startup_config()
    yield
    close_pools()


def create_app() -> FastAPI:
    app = FastAPI(title="Wealth Advisor API", version="0.3.0", lifespan=lifespan)
    app.include_router(routes_common.router)
    app.include_router(routes_client.router)
    app.include_router(routes_advisor.router)
    app.include_router(routes_admin.router)
    static_dir = os.environ.get("STATIC_DIR", "").strip()
    if static_dir and Path(static_dir).is_dir():
        _serve_frontend(app, Path(static_dir))
    return app


def _serve_frontend(app: FastAPI, root: Path) -> None:
    """On AWS one container serves the API and the built Angular app (same address, no CORS).
    Files are served as-is; any other non-API path returns index.html so Angular's router handles it."""
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "Not found.")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root.resolve()):
            # Hashed bundles never change, so they can be cached for a year; index.html never is.
            return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable"})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
