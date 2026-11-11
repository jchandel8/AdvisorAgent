"""Reset the database to the seeded mock data.

Usage: uv run python -m wealth.datagen [--anchor YYYY-MM-DD] [--seed 42]

Applies pending migrations, regenerates all data (dates relative to the anchor date), replaces
everything in the database in one transaction, and rewrites demo_users.csv at the repo root.
"""

from __future__ import annotations

import argparse
import time
from datetime import date
from urllib.parse import urlsplit

import psycopg

from wealth.config import get_settings
from wealth.datagen.generate import SEED, generate
from wealth.datagen.load import DEMO_USERS_CSV, analyze, load, write_demo_users
from wealth.migrate import migrate


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--anchor", type=date.fromisoformat, help="anchor date (default: DATA_ANCHOR_DATE or today)"
    )
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    settings = get_settings()
    anchor = args.anchor or settings.data_anchor_date
    db_name = urlsplit(settings.database_url).path.lstrip("/")

    started = time.monotonic()
    migrate(settings.database_url)
    ds = generate(anchor, seed=args.seed)
    with psycopg.connect(settings.database_url) as conn:
        load(conn, ds)
        analyze(conn)
        n_users = write_demo_users(conn, ds)

    print(
        f"Loaded database {db_name!r} (anchor {anchor}, seed {args.seed}) in {time.monotonic() - started:.1f}s"
    )
    print(
        f"  {len(ds.advisors)} advisors, {len(ds.clients)} clients, {len(ds.accounts)} accounts, "
        f"{len(ds.access)} access rows"
    )
    print(
        f"  {len(ds.holdings)} holdings rows, {len(ds.transactions)} transactions, "
        f"{len(ds.performance)} performance rows, {len(ds.documents)} documents"
    )
    print(f"Wrote {n_users} users to {DEMO_USERS_CSV}")


if __name__ == "__main__":
    main()
