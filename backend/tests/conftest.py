"""Test database setup.

Once per test session: drop and recreate the separate `wealth_test` database, apply migrations,
and load the hand-built fixture. Each test then gets a connection inside a transaction that is
rolled back afterwards, so tests cannot affect each other.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from tests.fixtures import load_fixture
from wealth import storage
from wealth.config import get_settings
from wealth.migrate import migrate


def _admin_url(url: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path="/postgres"))


@pytest.fixture(scope="session")
def test_db_url() -> str:
    settings = get_settings()
    url = settings.test_database_url
    db_name = urlsplit(url).path.lstrip("/")
    # Safety: never drop the dev database.
    assert url != settings.database_url and "test" in db_name, f"refusing to reset {db_name!r}"

    with psycopg.connect(_admin_url(url), autocommit=True) as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db_name)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))

    migrate(url)
    with psycopg.connect(url) as conn:
        load_fixture(conn)
        conn.commit()
    return url


@pytest.fixture
def conn(test_db_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(test_db_url, row_factory=dict_row) as c:
        try:
            yield c
        finally:
            c.rollback()


@pytest.fixture(autouse=True)
def isolated_auth_settings(monkeypatch):
    """Tests never depend on the developer's .env sign-in or model settings: demo mode, no Cognito, the
    Anthropic provider with default models, unless a test
    sets its own. Values are set to empty (not removed) so .env can't refill them."""
    monkeypatch.setenv("AUTH_MODE", "demo")
    for name in (
        "COGNITO_REGION",
        "COGNITO_USER_POOL_ID",
        "COGNITO_CLIENT_ID",
        "COGNITO_DOMAIN",
        "LLM_PROVIDER",
        "ANTHROPIC_MODEL",
        "GUARD_MODEL",
        "BEDROCK_REGION",
        "DOCUMENTS_BUCKET",
        "S3_ENDPOINT_URL",
    ):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    storage._s3.cache_clear()
    yield
    get_settings.cache_clear()
