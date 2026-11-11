"""Apply SQL migrations in backend/db/migrations in filename order, once each.

Usage: uv run python -m wealth.migrate [--test]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import psycopg

from wealth.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def migrate(url: str) -> list[str]:
    """Apply pending migrations; return the versions applied. Each file runs in its own transaction."""
    applied_now: list[str] = []
    with psycopg.connect(url) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        conn.commit()
        done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            applied_now.append(path.name)
    return applied_now


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="migrate the test database instead")
    args = parser.parse_args()
    settings = get_settings()
    url = settings.test_database_url if args.test else settings.database_url
    applied = migrate(url)
    print(f"Applied: {', '.join(applied)}" if applied else "Database is up to date.")


if __name__ == "__main__":
    main()
