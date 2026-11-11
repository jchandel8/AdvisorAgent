"""Database access: one connection pool per URL, and a read-only transaction helper.

Tools only ever read, so they run inside `read_only()`. Even if a query were wrong, Postgres
would refuse any write in that transaction.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from wealth.config import get_settings

_pools: dict[str, ConnectionPool] = {}


def get_pool(url: str | None = None) -> ConnectionPool:
    url = url or get_settings().database_url
    pool = _pools.get(url)
    if pool is None:
        pool = ConnectionPool(url, min_size=1, max_size=5, kwargs={"row_factory": dict_row}, open=True)
        _pools[url] = pool
    return pool


def close_pools() -> None:
    for pool in _pools.values():
        pool.close()
    _pools.clear()


@contextmanager
def connection(url: str | None = None) -> Iterator[psycopg.Connection]:
    with get_pool(url).connection() as conn:
        yield conn


@contextmanager
def read_only(url: str | None = None) -> Iterator[psycopg.Connection]:
    """Yield a connection inside a READ ONLY transaction (committed/rolled back on exit)."""
    with connection(url) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            yield conn
