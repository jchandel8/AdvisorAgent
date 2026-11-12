"""Create or update Cognito logins for the demo users (the `demo_users` table).

Usage (run by the owner, after `infra/tf.sh persistent apply`):
    uv run python -m wealth.ops.demo_logins            # dry run: shows what it would do
    uv run python -m wealth.ops.demo_logins --apply    # creates/updates the logins

Needs COGNITO_REGION, COGNITO_USER_POOL_ID and DEMO_PASSWORD (the shared demo password, kept in .env
locally and in Secrets Manager on AWS; never committed, never printed). Safe to re-run: existing logins
get the current password and the right group.

Each login's username is the person's database username, and the group (advisors / clients) tells the
API which table to look in. That pairing is the whole identity mapping.
"""

from __future__ import annotations

import argparse
import os
import sys

import boto3
import psycopg

from wealth.config import get_settings

GROUP_FOR = {"advisor": "advisors", "client": "clients"}


def demo_people(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """SELECT d.person_type AS kind,
                  coalesce(a.username, c.username) AS username,
                  coalesce(a.email, c.email) AS email,
                  coalesce(a.first_name || ' ' || a.last_name, c.first_name || ' ' || c.last_name) AS name
           FROM demo_users d
           LEFT JOIN advisors a ON a.id = d.advisor_id
           LEFT JOIN clients c ON c.id = d.client_id
           ORDER BY d.sort_order""",
    ).fetchall()


def upsert_login(cognito, pool_id: str, person: dict, password: str) -> str:
    username, group = person["username"], GROUP_FOR[person["kind"]]
    try:
        cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=username,
            UserAttributes=[
                {"Name": "email", "Value": person["email"]},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name", "Value": person["name"]},
            ],
            MessageAction="SUPPRESS",  # no invitation emails for demo users
        )
        action = "created"
    except cognito.exceptions.UsernameExistsException:
        action = "updated"
    cognito.admin_set_user_password(UserPoolId=pool_id, Username=username, Password=password, Permanent=True)
    for other in set(GROUP_FOR.values()) - {group}:  # exactly one group, or the API rejects the token
        try:
            cognito.admin_remove_user_from_group(UserPoolId=pool_id, Username=username, GroupName=other)
        except cognito.exceptions.ResourceNotFoundException:
            pass
    cognito.admin_add_user_to_group(UserPoolId=pool_id, Username=username, GroupName=group)
    return action


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    args = parser.parse_args()

    s = get_settings()
    password = os.environ.get("DEMO_PASSWORD", "")
    if not (s.cognito_region and s.cognito_user_pool_id):
        sys.exit("Set COGNITO_REGION and COGNITO_USER_POOL_ID (from `infra/tf.sh persistent output`).")
    if len(password) < 12:
        sys.exit("Set DEMO_PASSWORD (12+ characters, upper and lower case and a number) in .env.")

    with psycopg.connect(s.database_url, row_factory=psycopg.rows.dict_row) as conn:
        people = demo_people(conn)
    if not people:
        sys.exit("No demo users in the database. Run `python -m wealth.datagen` first.")

    cognito = boto3.client("cognito-idp", region_name=s.cognito_region)
    for p in people:
        line = f"{p['kind']:8} {p['username']:28} -> group {GROUP_FOR[p['kind']]}"
        if args.apply:
            print(f"{upsert_login(cognito, s.cognito_user_pool_id, p, password):8} {line}")
        else:
            print(f"would set {line}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to create or update these logins.")


if __name__ == "__main__":
    main()
