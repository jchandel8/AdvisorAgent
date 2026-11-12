"""Reset the demo to its starting state.

Usage:
    uv run python -m wealth.ops.reset --yes

1. Regenerates and reloads all data (same seed; dates relative to today), which also clears assistant
   conversations, the answer cache, the assistant log and the permission audit log.
2. When AUTH_MODE=cognito: makes sure the demo logins exist with the current demo password and groups.

Logins created later from the admin portal are left in Cognito (their database rows are gone after a reset,
so they can't open anything). Delete them in the Cognito console if you want a clean pool.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from wealth.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--yes", action="store_true", help="confirm: this replaces all data in the database")
    args = parser.parse_args()
    if not args.yes:
        sys.exit("This replaces ALL data in the database. Re-run with --yes to confirm.")

    subprocess.run([sys.executable, "-m", "wealth.datagen"], check=True)
    if get_settings().auth_mode == "cognito":
        subprocess.run([sys.executable, "-m", "wealth.ops.demo_logins", "--apply"], check=True)
    print("Demo reset complete.")


if __name__ == "__main__":
    main()
