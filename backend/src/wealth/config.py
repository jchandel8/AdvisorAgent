"""Settings read from environment variables (and the repo-root .env file locally).

Everything configurable lives here so no other module reads os.environ directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from dotenv import find_dotenv, load_dotenv

DEFAULT_MODEL = "claude-sonnet-5-5"


def _with_db_name(url: str, db_name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{db_name}"))


@dataclass(frozen=True)
class Settings:
    database_url: str
    test_database_url: str
    anthropic_api_key: str | None
    anthropic_model: str
    data_anchor_date: date
    answer_cache_enabled: bool
    answer_cache_ttl_hours: float
    answer_cache_max_entries: int
    demo_auth_enabled: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # usecwd=True searches upward from the working directory, so running from backend/ finds ../.env.
    load_dotenv(find_dotenv(usecwd=True), override=False)

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")

    test_url = os.environ.get("TEST_DATABASE_URL", "").strip() or _with_db_name(database_url, "wealth_test")
    if test_url == database_url:
        raise RuntimeError("TEST_DATABASE_URL must point at a different database than DATABASE_URL.")

    anchor_raw = os.environ.get("DATA_ANCHOR_DATE", "").strip()
    anchor = date.fromisoformat(anchor_raw) if anchor_raw else date.today()

    return Settings(
        database_url=database_url,
        test_database_url=test_url,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL,
        data_anchor_date=anchor,
        answer_cache_enabled=os.environ.get("ANSWER_CACHE_ENABLED", "true").strip().lower() != "false",
        answer_cache_ttl_hours=float(os.environ.get("ANSWER_CACHE_TTL_HOURS", "").strip() or 24),
        answer_cache_max_entries=int(os.environ.get("ANSWER_CACHE_MAX_ENTRIES", "").strip() or 1000),
        # Local-only stand-in for login (pick a demo user). Off unless explicitly enabled; refused on AWS.
        demo_auth_enabled=os.environ.get("DEMO_AUTH_ENABLED", "false").strip().lower() == "true",
    )


# Environment variables that AWS sets inside ECS tasks, Lambda and other managed runtimes.
AWS_RUNTIME_MARKERS = (
    "ECS_CONTAINER_METADATA_URI_V4",
    "ECS_CONTAINER_METADATA_URI",
    "AWS_EXECUTION_ENV",
    "AWS_LAMBDA_FUNCTION_NAME",
)


def running_on_aws() -> bool:
    return any(os.environ.get(name) for name in AWS_RUNTIME_MARKERS)
