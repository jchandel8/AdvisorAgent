#!/usr/bin/env python3
"""Point Cognito sign-in at the current AWS app URL (run by the Deploy workflow after each deploy).

ECS Express gives the service a new random URL whenever it is re-created (after a teardown), and Cognito only
returns users to URLs on its allow-list. This script:
  - keeps every non-AWS entry (http://localhost:4200 for local development),
  - drops old ECS Express URLs (*.on.aws), so stale addresses don't pile up,
  - adds <app_url>/auth/callback and <app_url>/login.

UpdateUserPoolClient resets any setting that is not sent, so the script reads the full current client and sends
all of it back with only the two URL lists changed. If AWS returns a field the update call doesn't accept, the
AWS CLI rejects the request instead of silently dropping a setting.

Uses only the AWS CLI and the Python standard library (both preinstalled on GitHub runners).
  python3 infra/scripts/cognito_allow_url.py --pool <pool id> --client <client id> --url https://... [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile

# Returned by DescribeUserPoolClient but not accepted by UpdateUserPoolClient.
READ_ONLY = {"CreationDate", "LastModifiedDate", "ClientSecret"}
AWS_APP_SUFFIX = ".on.aws"


def aws(*args: str) -> dict:
    out = subprocess.run(["aws", *args, "--output", "json"], check=True, capture_output=True, text=True)
    return json.loads(out.stdout) if out.stdout.strip() else {}


def merged(urls: list[str], new: str) -> list[str]:
    """Keep non-AWS entries in their order, drop old AWS app entries, add the new one."""
    kept = [u for u in urls if AWS_APP_SUFFIX not in u.split("/")[2]]
    return [*kept, new] if new not in kept else kept


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pool", required=True)
    p.add_argument("--client", required=True)
    p.add_argument("--url", required=True, help="app origin, e.g. https://ad-xxxx.ecs.us-west-1.on.aws")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    url = a.url.rstrip("/")
    if not url.startswith("https://"):
        sys.exit(f"--url must start with https:// (got {url!r})")

    client = aws("cognito-idp", "describe-user-pool-client", "--user-pool-id", a.pool, "--client-id", a.client)[
        "UserPoolClient"
    ]
    before = (client.get("CallbackURLs", []), client.get("LogoutURLs", []))
    client["CallbackURLs"] = merged(before[0], f"{url}/auth/callback")
    client["LogoutURLs"] = merged(before[1], f"{url}/login")
    after = (client["CallbackURLs"], client["LogoutURLs"])

    print("callback URLs:", before[0], "->", after[0])
    print("logout URLs:  ", before[1], "->", after[1])
    if after == before:
        print("Already up to date.")
        return
    if a.dry_run:
        print("Dry run: nothing changed.")
        return

    body = {k: v for k, v in client.items() if k not in READ_ONLY}
    with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
        json.dump(body, f)
        f.flush()
        aws("cognito-idp", "update-user-pool-client", "--cli-input-json", f"file://{f.name}")
    print("Updated Cognito allow-list.")


if __name__ == "__main__":
    main()
