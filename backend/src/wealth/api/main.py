"""FastAPI app: one API for the advisor and client portals and the agent.

Run locally: uv run uvicorn wealth.api.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from wealth.api import routes_advisor, routes_client, routes_common
from wealth.config import get_settings, running_on_aws
from wealth.db import close_pools


def check_startup_config() -> None:
    """Refuse to start in an unsafe configuration."""
    settings = get_settings()
    if settings.demo_auth_enabled and running_on_aws():
        raise RuntimeError(
            "DEMO_AUTH_ENABLED=true is a local-only setting and is not allowed on AWS. Use Cognito login."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_startup_config()
    yield
    close_pools()


def create_app() -> FastAPI:
    app = FastAPI(title="Wealth Advisor API", version="0.2.0", lifespan=lifespan)
    app.include_router(routes_common.router)
    app.include_router(routes_client.router)
    app.include_router(routes_advisor.router)
    return app


app = create_app()
