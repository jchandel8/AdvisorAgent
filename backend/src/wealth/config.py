"""Settings read from environment variables (and the repo-root .env file locally).

Everything configurable lives here so no other module reads os.environ directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from urllib.parse import quote, urlsplit, urlunsplit

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
    auth_mode: str  # "demo" (local picker) or "cognito" (verified JWT)
    cognito_region: str | None
    cognito_user_pool_id: str | None
    cognito_client_id: str | None
    cognito_domain: str | None  # managed login domain, e.g. advisoragent-123.auth.us-west-1.amazoncognito.com
    assistant_per_minute: int
    assistant_per_day: int
    assistant_guard_enabled: bool

    @property
    def demo_auth_enabled(self) -> bool:
        return self.auth_mode == "demo"

    @property
    def cognito_issuer(self) -> str | None:
        if self.cognito_region and self.cognito_user_pool_id:
            return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # usecwd=True searches upward from the working directory, so running from backend/ finds ../.env.
    load_dotenv(find_dotenv(usecwd=True), override=False)

    database_url = os.environ.get("DATABASE_URL", "").strip() or _database_url_from_parts()
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
        # demo = local-only user picker (refused on AWS); cognito = Cognito access tokens only.
        auth_mode=_auth_mode(),
        cognito_region=os.environ.get("COGNITO_REGION", "").strip() or None,
        cognito_user_pool_id=os.environ.get("COGNITO_USER_POOL_ID", "").strip() or None,
        cognito_client_id=os.environ.get("COGNITO_CLIENT_ID", "").strip() or None,
        cognito_domain=os.environ.get("COGNITO_DOMAIN", "").strip() or None,
        # Assistant guardrails: per-advisor limits and the scope check (keep the check on outside tests).
        assistant_per_minute=int(os.environ.get("ASSISTANT_PER_MINUTE", "").strip() or 10),
        assistant_per_day=int(os.environ.get("ASSISTANT_PER_DAY", "").strip() or 100),
        assistant_guard_enabled=os.environ.get("ASSISTANT_GUARD_ENABLED", "true").strip().lower() != "false",
    )


def _database_url_from_parts() -> str:
    """On AWS the password comes from the RDS-managed secret (injected as DB_PASSWORD), so the URL is
    assembled here instead of being stored anywhere. sslmode=require: RDS traffic is encrypted."""
    host = os.environ.get("DB_HOST", "").strip()
    if not host:
        return ""
    user = quote(os.environ.get("DB_USER", "").strip(), safe="")
    password = quote(os.environ.get("DB_PASSWORD", ""), safe="")
    port = os.environ.get("DB_PORT", "5432").strip()
    name = os.environ.get("DB_NAME", "wealth").strip()
    return f"postgresql://{user}:{password}@{host}:{port}/{name}?sslmode=require"


def _auth_mode() -> str:
    mode = os.environ.get("AUTH_MODE", "").strip().lower()
    if not mode:  # backward compatible with the step 2 setting
        mode = "demo" if os.environ.get("DEMO_AUTH_ENABLED", "").strip().lower() == "true" else "cognito"
    if mode not in ("demo", "cognito"):
        raise RuntimeError(f"AUTH_MODE must be 'demo' or 'cognito', not {mode!r}")
    return mode


# Environment variables that AWS sets inside ECS tasks, Lambda and other managed runtimes.
AWS_RUNTIME_MARKERS = (
    "ECS_CONTAINER_METADATA_URI_V4",
    "ECS_CONTAINER_METADATA_URI",
    "AWS_EXECUTION_ENV",
    "AWS_LAMBDA_FUNCTION_NAME",
)


def running_on_aws() -> bool:
    return any(os.environ.get(name) for name in AWS_RUNTIME_MARKERS)
