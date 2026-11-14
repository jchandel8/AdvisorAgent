"""Admin portal API: users, accounts, permissions, documents, audit log, assistant log.

Admins manage access; they don't read portfolios (no holdings, transactions or values here). They may read
documents, but every preview and download is recorded in permission_audit like a change. Every change is
written to permission_audit in the SAME transaction as the change, so the log can't miss one.
Advisors and clients see a grant or revoke on their next request: every query reads account_access live.
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any, Literal

import boto3
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wealth.api.deps import CurrentUser, get_write_conn, require_admin
from wealth.api.routes_documents import document_bytes, file_response
from wealth.config import get_settings
from wealth.datagen.generate import ALLOCATIONS
from wealth.storage import Storage, get_storage

router = APIRouter(prefix="/api/admin", tags=["admin"])

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLES = {"advisor": {"advisor", "viewer"}, "client": {"owner", "joint_owner", "viewer"}}
TABLE = {"advisor": "advisors", "client": "clients", "admin": "admins"}


# --- identity provider (Cognito) ---------------------------------------------------------------------


class Logins:
    """Creates sign-in logins. In demo mode there is no identity provider, so this does nothing."""

    def create(self, *, username: str, email: str, name: str, group: str) -> None:
        return None


class CognitoLogins(Logins):
    """Creates the Cognito login in the right group. The new user signs in with the shared demo password
    (DEMO_PASSWORD), which suits this demo app; a production app would send an invitation instead."""

    def __init__(self, region: str, pool_id: str, password: str):
        self.client = boto3.client("cognito-idp", region_name=region)
        self.pool_id = pool_id
        self.password = password

    def create(self, *, username: str, email: str, name: str, group: str) -> None:
        self.client.admin_create_user(
            UserPoolId=self.pool_id,
            Username=username,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name", "Value": name},
            ],
            MessageAction="SUPPRESS",
        )
        self.client.admin_set_user_password(
            UserPoolId=self.pool_id, Username=username, Password=self.password, Permanent=True
        )
        self.client.admin_add_user_to_group(UserPoolId=self.pool_id, Username=username, GroupName=group)


def get_logins() -> Logins:
    s = get_settings()
    if s.auth_mode != "cognito":
        return Logins()

    password = os.environ.get("DEMO_PASSWORD", "")  # Secrets Manager -> env on AWS
    if not (s.cognito_region and s.cognito_user_pool_id and password):
        raise HTTPException(503, "Creating users needs COGNITO_* settings and DEMO_PASSWORD on the server.")
    return CognitoLogins(s.cognito_region, s.cognito_user_pool_id, password)


def _audit(conn, admin: CurrentUser, action: str, summary: str, **fields: Any) -> None:
    conn.execute(
        """INSERT INTO permission_audit (admin_id, admin_name, action, account_id, person_type, person_id, role,
                                         document_id, summary)
           VALUES (%(admin_id)s, %(admin_name)s, %(action)s, %(account_id)s, %(person_type)s, %(person_id)s,
                   %(role)s, %(document_id)s, %(summary)s)""",
        {
            "admin_id": admin.id,
            "admin_name": admin.name,
            "action": action,
            "account_id": fields.get("account_id"),
            "person_type": fields.get("person_type"),
            "person_id": fields.get("person_id"),
            "role": fields.get("role"),
            "document_id": fields.get("document_id"),
            "summary": summary,
        },
    )


def _person_name(conn, person_type: str, person_id: int) -> str | None:
    row = conn.execute(
        f"SELECT first_name || ' ' || last_name AS name FROM {TABLE[person_type]} WHERE id = %s", (person_id,)
    ).fetchone()
    return row["name"] if row else None


# --- users ------------------------------------------------------------------------------------------


@router.get("/users")
def list_users(
    kind: Literal["advisor", "client", "admin"] = "advisor",
    q: str = Query(default="", max_length=100),
    admin: CurrentUser = Depends(require_admin),
    conn=Depends(get_write_conn),
):
    like = f"%{q.strip().lower()}%"
    if kind == "advisor":
        sql = """SELECT p.id, p.username, p.first_name, p.last_name, p.email,
                        (SELECT count(*) FROM account_access x WHERE x.advisor_id = p.id) AS account_count,
                        (SELECT count(DISTINCT ca.client_id) FROM account_access x
                           JOIN account_access ca ON ca.account_id = x.account_id AND ca.client_id IS NOT NULL
                          WHERE x.advisor_id = p.id) AS client_count
                 FROM advisors p"""
    elif kind == "client":
        sql = """SELECT p.id, p.username, p.first_name, p.last_name, p.email, p.risk_profile,
                        (SELECT count(*) FROM account_access x WHERE x.client_id = p.id) AS account_count
                 FROM clients p"""
    else:
        sql = "SELECT p.id, p.username, p.first_name, p.last_name, p.email FROM admins p"
    rows = conn.execute(
        sql
        + """ WHERE %(like)s = '%%%%' OR lower(p.first_name || ' ' || p.last_name || ' ' || p.username) LIKE %(like)s
              ORDER BY p.last_name, p.first_name, p.id LIMIT 300""",
        {"like": like},
    ).fetchall()
    return {"kind": kind, "count": len(rows), "users": rows}


class NewUser(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["advisor", "client"]
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    email: str = Field(max_length=254)
    username: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=30)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=2)
    risk_profile: Literal["conservative", "moderate", "growth", "aggressive"] = "moderate"

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if not EMAIL.match(v):
            raise ValueError("enter a valid email address")
        return v.lower()

    @field_validator("username")
    @classmethod
    def _username(cls, v: str | None) -> str | None:
        if v is not None and not USERNAME.match(v.lower()):
            raise ValueError("3-64 characters: lowercase letters, numbers, dots, dashes or underscores")
        return v.lower() if v else v


def _default_username(first: str, last: str) -> str:
    base = re.sub(r"[^a-z0-9]", "", first.lower()) + "." + re.sub(r"[^a-z0-9]", "", last.lower())
    return base if USERNAME.match(base) else f"user.{base}"[:64]


@router.post("/users", status_code=201)
def create_user(
    body: NewUser,
    admin: CurrentUser = Depends(require_admin),
    conn=Depends(get_write_conn),
    logins: Logins = Depends(get_logins),
):
    """Creates the database person and the sign-in login together. If the login fails, the database
    insert is rolled back (the request's transaction), so there are never half-created users."""
    username = body.username or _default_username(body.first_name, body.last_name)
    taken = conn.execute(
        "SELECT 1 FROM advisors WHERE username = %(u)s OR email = %(e)s"
        " UNION ALL SELECT 1 FROM clients WHERE username = %(u)s OR email = %(e)s"
        " UNION ALL SELECT 1 FROM admins WHERE username = %(u)s OR email = %(e)s",
        {"u": username, "e": body.email},
    ).fetchone()
    if taken:
        raise HTTPException(409, f"The username '{username}' or that email is already in use.")

    common = {
        "username": username,
        "first": body.first_name,
        "last": body.last_name,
        "email": body.email,
        "phone": body.phone,
        "city": body.city,
        "state": (body.state or "").upper() or None,
    }
    if body.kind == "advisor":
        row = conn.execute(
            """INSERT INTO advisors (username, first_name, last_name, email, phone, city, state)
               VALUES (%(username)s, %(first)s, %(last)s, %(email)s, %(phone)s, %(city)s, %(state)s) RETURNING id""",
            common,
        ).fetchone()
    else:
        row = conn.execute(
            """INSERT INTO clients (username, first_name, last_name, email, phone, city, state, risk_profile,
                                    target_allocation)
               VALUES (%(username)s, %(first)s, %(last)s, %(email)s, %(phone)s, %(city)s, %(state)s, %(risk)s,
                       %(alloc)s) RETURNING id""",
            {
                **common,
                "risk": body.risk_profile,
                "alloc": psycopg.types.json.Jsonb(ALLOCATIONS[body.risk_profile]),
            },
        ).fetchone()
    name = f"{body.first_name} {body.last_name}"
    _audit(
        conn,
        admin,
        "create_user",
        f"Created {body.kind} {name} ({username})",
        person_type=body.kind,
        person_id=row["id"],
    )
    try:
        logins.create(username=username, email=body.email, name=name, group=f"{body.kind}s")
    except Exception as exc:  # the request transaction rolls back the insert and the audit row
        raise HTTPException(
            502, f"The sign-in login couldn't be created, so nothing was saved: {exc}"
        ) from exc
    return {"kind": body.kind, "id": row["id"], "username": username, "name": name}


# --- accounts ----------------------------------------------------------------------------------------


@router.get("/accounts")
def list_accounts(
    q: str = Query(default="", max_length=100),
    admin: CurrentUser = Depends(require_admin),
    conn=Depends(get_write_conn),
):
    like = f"%{q.strip().lower()}%"
    rows = conn.execute(
        """SELECT a.id AS account_id, a.account_name, a.account_type, a.open_date, a.close_date,
                  (SELECT string_agg(c.first_name || ' ' || c.last_name, ', ' ORDER BY x.role DESC, c.id)
                     FROM account_access x JOIN clients c ON c.id = x.client_id WHERE x.account_id = a.id) AS clients,
                  (SELECT string_agg(v.first_name || ' ' || v.last_name, ', ' ORDER BY v.id)
                     FROM account_access x JOIN advisors v ON v.id = x.advisor_id WHERE x.account_id = a.id) AS advisors
           FROM accounts a
           WHERE %(like)s = '%%%%'
              OR lower(a.account_name) LIKE %(like)s
              OR a.id::text = %(raw)s
           ORDER BY a.id DESC
           LIMIT 300""",
        {"like": like, "raw": q.strip()},
    ).fetchall()
    return {"count": len(rows), "accounts": rows}


class NewAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    account_name: str = Field(min_length=3, max_length=120)
    account_type: Literal["individual", "joint", "ira", "trust"]
    description: str | None = Field(default=None, max_length=300)
    owner_client_ids: list[int] = Field(min_length=1, max_length=2)
    advisor_ids: list[int] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _owners(self):
        if len(set(self.owner_client_ids)) != len(self.owner_client_ids) or len(set(self.advisor_ids)) != len(
            self.advisor_ids
        ):
            raise ValueError("list each person once")
        if self.account_type == "joint" and len(self.owner_client_ids) != 2:
            raise ValueError("a joint account has exactly two owners")
        if self.account_type != "joint" and len(self.owner_client_ids) != 1:
            raise ValueError("only a joint account has two owners")
        return self


@router.post("/accounts", status_code=201)
def create_account(
    body: NewAccount, admin: CurrentUser = Depends(require_admin), conn=Depends(get_write_conn)
):
    for cid in body.owner_client_ids:
        if _person_name(conn, "client", cid) is None:
            raise HTTPException(404, f"There is no client with ID {cid}.")
    for aid in body.advisor_ids:
        if _person_name(conn, "advisor", aid) is None:
            raise HTTPException(404, f"There is no advisor with ID {aid}.")
    acct = conn.execute(
        "INSERT INTO accounts (account_name, account_type, description, open_date) VALUES (%s, %s, %s, %s) RETURNING id",
        (body.account_name, body.account_type, body.description, date.today()),
    ).fetchone()
    account_id = acct["id"]
    _audit(
        conn,
        admin,
        "create_account",
        f"Created account {body.account_name} (#{account_id})",
        account_id=account_id,
    )
    for i, cid in enumerate(body.owner_client_ids):
        _grant(conn, admin, account_id, "client", cid, "owner" if i == 0 else "joint_owner")
    for aid in body.advisor_ids:
        _grant(conn, admin, account_id, "advisor", aid, "advisor")
    return {"account_id": account_id, "account_name": body.account_name}


# --- permissions -------------------------------------------------------------------------------------


@router.get("/accounts/{account_id}/access")
def account_access(
    account_id: int, admin: CurrentUser = Depends(require_admin), conn=Depends(get_write_conn)
):
    acct = conn.execute(
        "SELECT id AS account_id, account_name, account_type, open_date, close_date FROM accounts WHERE id = %s",
        (account_id,),
    ).fetchone()
    if acct is None:
        raise HTTPException(404, "Account not found.")
    rows = conn.execute(
        """SELECT x.id AS access_id, x.person_type, coalesce(x.advisor_id, x.client_id) AS person_id,
                  coalesce(v.first_name || ' ' || v.last_name, c.first_name || ' ' || c.last_name) AS name,
                  coalesce(v.username, c.username) AS username,
                  x.role, x.granted_at, x.granted_by
           FROM account_access x
           LEFT JOIN advisors v ON v.id = x.advisor_id
           LEFT JOIN clients c ON c.id = x.client_id
           WHERE x.account_id = %s
           ORDER BY x.person_type DESC, x.role, name""",
        (account_id,),
    ).fetchall()
    return {**acct, "access": rows}


@router.get("/people")
def find_people(
    q: str = Query(min_length=1, max_length=100),
    kind: Literal["advisor", "client"] | None = None,
    admin: CurrentUser = Depends(require_admin),
    conn=Depends(get_write_conn),
):
    """Search advisors and clients by name, username or ID, for the grant form."""
    like = f"%{q.strip().lower()}%"
    rows = conn.execute(
        """SELECT * FROM (
             SELECT 'advisor' AS person_type, id AS person_id, first_name || ' ' || last_name AS name, username
             FROM advisors
             UNION ALL
             SELECT 'client', id, first_name || ' ' || last_name, username FROM clients
           ) p
           WHERE (%(kind)s::text IS NULL OR p.person_type = %(kind)s)
             AND (lower(p.name || ' ' || p.username) LIKE %(like)s OR p.person_id::text = %(raw)s)
           ORDER BY p.name LIMIT 20""",
        {"kind": kind, "like": like, "raw": q.strip()},
    ).fetchall()
    return {"people": rows}


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int = Field(gt=0)
    person_type: Literal["advisor", "client"]
    person_id: int = Field(gt=0)
    role: Literal["owner", "joint_owner", "advisor", "viewer"]

    @model_validator(mode="after")
    def _role_fits(self):
        if self.role not in ROLES[self.person_type]:
            raise ValueError(f"a {self.person_type} can't have the role {self.role}")
        return self


def _grant(conn, admin: CurrentUser, account_id: int, person_type: str, person_id: int, role: str) -> int:
    id_col = "advisor_id" if person_type == "advisor" else "client_id"
    try:
        with conn.transaction():  # savepoint: a duplicate becomes a clean 409
            row = conn.execute(
                f"""INSERT INTO account_access (account_id, person_type, {id_col}, role, granted_by)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (account_id, person_type, person_id, role, admin.name),
            ).fetchone()
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, "That person already has access to this account.") from exc
    name = _person_name(conn, person_type, person_id)
    acct = conn.execute("SELECT account_name FROM accounts WHERE id = %s", (account_id,)).fetchone()
    _audit(
        conn,
        admin,
        "grant",
        f"Granted {name} ({person_type}) {role.replace('_', ' ')} access to {acct['account_name']} (#{account_id})",
        account_id=account_id,
        person_type=person_type,
        person_id=person_id,
        role=role,
    )
    return row["id"]


@router.post("/access", status_code=201)
def grant_access(body: Grant, admin: CurrentUser = Depends(require_admin), conn=Depends(get_write_conn)):
    acct = conn.execute("SELECT close_date FROM accounts WHERE id = %s", (body.account_id,)).fetchone()
    if acct is None:
        raise HTTPException(404, "Account not found.")
    if acct["close_date"] is not None:
        raise HTTPException(409, "That account is closed.")
    if _person_name(conn, body.person_type, body.person_id) is None:
        raise HTTPException(404, f"There is no {body.person_type} with ID {body.person_id}.")
    access_id = _grant(conn, admin, body.account_id, body.person_type, body.person_id, body.role)
    return {"access_id": access_id}


@router.delete("/access/{access_id}")
def revoke_access(access_id: int, admin: CurrentUser = Depends(require_admin), conn=Depends(get_write_conn)):
    row = conn.execute(
        """SELECT x.*, a.account_name FROM account_access x JOIN accounts a ON a.id = x.account_id
           WHERE x.id = %s FOR UPDATE""",
        (access_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "That access no longer exists.")
    # An account always keeps at least one client owner and at least one advisor.
    remaining = conn.execute(
        """SELECT count(*) FILTER (WHERE person_type = 'client' AND role = 'owner') AS owners,
                  count(*) FILTER (WHERE person_type = 'advisor') AS advisors
           FROM account_access WHERE account_id = %s AND id <> %s""",
        (row["account_id"], access_id),
    ).fetchone()
    if row["person_type"] == "client" and row["role"] == "owner" and remaining["owners"] == 0:
        raise HTTPException(409, "This is the account's only owner. Grant another owner first.")
    if row["person_type"] == "advisor" and remaining["advisors"] == 0:
        raise HTTPException(409, "This is the account's only advisor. Grant another advisor first.")
    conn.execute("DELETE FROM account_access WHERE id = %s", (access_id,))
    person_id = row["advisor_id"] or row["client_id"]
    name = _person_name(conn, row["person_type"], person_id)
    _audit(
        conn,
        admin,
        "revoke",
        f"Revoked {name}'s ({row['person_type']}) {row['role'].replace('_', ' ')} access to "
        f"{row['account_name']} (#{row['account_id']})",
        account_id=row["account_id"],
        person_type=row["person_type"],
        person_id=person_id,
        role=row["role"],
    )
    return {"revoked": access_id}


# --- drilldowns: one user, one account ---------------------------------------------------------------

PROFILE_SQL = {
    "advisor": """SELECT id, username, first_name, last_name, email, phone, certifications, city, state, created_at
                  FROM advisors WHERE id = %s""",
    "client": """SELECT id, username, first_name, last_name, email, phone, address, city, state, risk_profile,
                        target_allocation, next_review_date, created_at
                 FROM clients WHERE id = %s""",
    "admin": "SELECT id, username, first_name, last_name, email, created_at FROM admins WHERE id = %s",
}


@router.get("/users/{kind}/{person_id}")
def user_detail(
    kind: Literal["advisor", "client", "admin"],
    person_id: int,
    admin: CurrentUser = Depends(require_admin),
    conn=Depends(get_write_conn),
):
    """Profile plus, for advisors and clients, every account they have access to and who else is on it.
    (Admin activity is paged separately: GET /audit?admin_id=...)"""
    profile = conn.execute(PROFILE_SQL[kind], (person_id,)).fetchone()
    if profile is None:
        raise HTTPException(404, f"There is no {kind} with ID {person_id}.")
    if kind == "admin":
        return {"kind": kind, "profile": profile, "accounts": []}
    id_col = "advisor_id" if kind == "advisor" else "client_id"
    accounts = conn.execute(
        f"""SELECT a.id AS account_id, a.account_name, a.account_type, a.open_date, a.close_date,
                   me.role, me.granted_at,
                   (SELECT string_agg(c.first_name || ' ' || c.last_name, ', ' ORDER BY x.role DESC, c.id)
                      FROM account_access x JOIN clients c ON c.id = x.client_id WHERE x.account_id = a.id) AS clients,
                   (SELECT string_agg(v.first_name || ' ' || v.last_name, ', ' ORDER BY v.id)
                      FROM account_access x JOIN advisors v ON v.id = x.advisor_id WHERE x.account_id = a.id) AS advisors
            FROM account_access me JOIN accounts a ON a.id = me.account_id
            WHERE me.{id_col} = %s
            ORDER BY a.close_date IS NOT NULL, a.account_name, a.id""",
        (person_id,),
    ).fetchall()
    return {"kind": kind, "profile": profile, "accounts": accounts}


@router.get("/accounts/{account_id}")
def account_detail(
    account_id: int, admin: CurrentUser = Depends(require_admin), conn=Depends(get_write_conn)
):
    """Account facts, everyone with access, and its documents (titles only; no portfolio values)."""
    acct = conn.execute(
        """SELECT id AS account_id, account_name, account_type, description, open_date, close_date
           FROM accounts WHERE id = %s""",
        (account_id,),
    ).fetchone()
    if acct is None:
        raise HTTPException(404, "Account not found.")
    access = account_access(account_id, admin, conn)["access"]
    documents = conn.execute(
        DOCUMENT_LIST_SQL + " WHERE d.account_id = %(account_id)s ORDER BY d.created_date DESC, d.id DESC",
        {"account_id": account_id},
    ).fetchall()
    return {**acct, "access": access, "documents": documents}


# --- documents ---------------------------------------------------------------------------------------

DOC_TYPES = ("ips", "review_notes", "statement", "agreement", "other")

DOCUMENT_LIST_SQL = """
    SELECT d.id AS document_id, d.title, d.doc_type, d.size_kb, d.created_date, d.uploaded_at, d.deleted_at,
           d.note, d.content_type, d.original_filename,
           a.id AS account_id, a.account_name,
           CASE WHEN d.uploaded_by_client_id IS NOT NULL THEN 'client'
                WHEN d.uploaded_by_advisor_id IS NOT NULL THEN 'advisor' END AS uploaded_by_type,
           coalesce(d.uploaded_by_client_id, d.uploaded_by_advisor_id) AS uploaded_by_id,
           coalesce(uc.first_name || ' ' || uc.last_name, u.first_name || ' ' || u.last_name) AS uploaded_by,
           (d.storage_key IS NULL OR d.content_type LIKE 'text/plain%%') AS previewable
    FROM documents d
    JOIN accounts a ON a.id = d.account_id
    LEFT JOIN advisors u ON u.id = d.uploaded_by_advisor_id
    LEFT JOIN clients uc ON uc.id = d.uploaded_by_client_id"""


@router.get("/documents")
def list_documents(
    q: str = Query(default="", max_length=100),
    doc_type: Literal["ips", "review_notes", "statement", "agreement", "other"] | None = None,
    page: int = Query(default=1, ge=1, le=10_000),
    admin: CurrentUser = Depends(require_admin),
    conn=Depends(get_write_conn),
):
    """Newest first, 50 a page. Search matches the title, the account name or an account/document ID."""
    size = 50
    rows = conn.execute(
        f"""SELECT docs.*, count(*) OVER () AS total_rows
            FROM ({DOCUMENT_LIST_SQL}
                  WHERE (%(type)s::text IS NULL OR d.doc_type = %(type)s)
                    AND (%(like)s = '%%%%' OR lower(d.title || ' ' || a.account_name) LIKE %(like)s
                         OR d.id::text = %(raw)s OR a.id::text = %(raw)s)) docs
            ORDER BY docs.created_date DESC, docs.document_id DESC LIMIT %(size)s OFFSET %(offset)s""",
        {
            "type": doc_type,
            "like": f"%{q.strip().lower()}%",
            "raw": q.strip(),
            "size": size,
            "offset": (page - 1) * size,
        },
    ).fetchall()
    total = rows[0]["total_rows"] if rows else 0
    for r in rows:
        del r["total_rows"]
    return {"page": page, "page_size": size, "total_rows": total, "documents": rows}


def _document(conn, document_id: int) -> dict:
    row = conn.execute(DOCUMENT_LIST_SQL + " WHERE d.id = %s", (document_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Document not found.")
    return row


@router.get("/documents/{document_id}")
def document_detail(
    document_id: int, admin: CurrentUser = Depends(require_admin), conn=Depends(get_write_conn)
):
    """Facts about the document and who has opened it. Not the text itself (see /content)."""
    doc = _document(conn, document_id)
    opened = conn.execute(
        """SELECT id, created_at, admin_id, admin_name, action FROM permission_audit
           WHERE document_id = %s ORDER BY created_at DESC, id DESC LIMIT 20""",
        (document_id,),
    ).fetchall()
    return {**doc, "access_log": opened}


def _record_open(conn, admin: CurrentUser, doc: dict, action: str) -> None:
    verb = "Viewed" if action == "view_document" else "Downloaded"
    _audit(
        conn,
        admin,
        action,
        f"{verb} document {doc['title']} (#{doc['document_id']}) of {doc['account_name']} (#{doc['account_id']})",
        account_id=doc["account_id"],
        document_id=doc["document_id"],
    )


@router.get("/documents/{document_id}/content")
def document_content(
    document_id: int,
    admin: CurrentUser = Depends(require_admin),
    conn=Depends(get_write_conn),
    storage: Storage | None = Depends(get_storage),
):
    """The document's text, for the preview (text documents only). Recorded in the audit log."""
    doc = _document(conn, document_id)
    if not doc["previewable"]:
        raise HTTPException(409, "Only text documents can be previewed here. Download this one instead.")
    data, _, _ = document_bytes(_stored(conn, document_id), storage)
    _record_open(conn, admin, doc, "view_document")
    return {"document_id": document_id, "text": data.decode("utf-8", errors="replace")}


def _stored(conn, document_id: int) -> dict:
    return conn.execute(
        "SELECT id, title, text, storage_key, content_type, original_filename FROM documents WHERE id = %s",
        (document_id,),
    ).fetchone()


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: int,
    admin: CurrentUser = Depends(require_admin),
    conn=Depends(get_write_conn),
    storage: Storage | None = Depends(get_storage),
):
    """The document's file (seeded documents as .txt). Recorded in the audit log in the same transaction."""
    doc = _document(conn, document_id)
    data, content_type, filename = document_bytes(_stored(conn, document_id), storage)
    _record_open(conn, admin, doc, "download_document")
    return file_response(data=data, content_type=content_type, filename=filename, inline=False)


# --- logs --------------------------------------------------------------------------------------------


@router.get("/audit")
def audit_log(
    page: int = Query(default=1, ge=1, le=10_000),
    admin_id: int | None = Query(default=None, gt=0),  # one admin's activity (admin drilldown)
    admin: CurrentUser = Depends(require_admin),
    conn=Depends(get_write_conn),
):
    size = 50
    rows = conn.execute(
        """SELECT id, created_at, admin_id, admin_name, action, account_id, person_type, person_id, role,
                  document_id, summary, count(*) OVER () AS total_rows
           FROM permission_audit
           WHERE %(admin_id)s::int IS NULL OR admin_id = %(admin_id)s
           ORDER BY created_at DESC, id DESC LIMIT %(size)s OFFSET %(offset)s""",
        {"admin_id": admin_id, "size": size, "offset": (page - 1) * size},
    ).fetchall()
    total = rows[0]["total_rows"] if rows else 0
    for r in rows:
        del r["total_rows"]
    return {"page": page, "page_size": size, "total_rows": total, "events": rows}


@router.get("/assistant-events")
def assistant_events(
    blocked_only: bool = True,
    page: int = Query(default=1, ge=1, le=10_000),
    admin: CurrentUser = Depends(require_admin),
    conn=Depends(get_write_conn),
):
    size = 50
    rows = conn.execute(
        """SELECT e.id, e.created_at, e.advisor_id, v.first_name || ' ' || v.last_name AS advisor_name,
                  e.outcome, e.question, e.reason, count(*) OVER () AS total_rows
           FROM assistant_events e JOIN advisors v ON v.id = e.advisor_id
           WHERE NOT %(blocked)s OR e.outcome LIKE 'blocked%%' OR e.outcome IN ('guard_error', 'rate_limited')
           ORDER BY e.created_at DESC, e.id DESC LIMIT %(size)s OFFSET %(offset)s""",
        {"blocked": blocked_only, "size": size, "offset": (page - 1) * size},
    ).fetchall()
    total = rows[0]["total_rows"] if rows else 0
    for r in rows:
        del r["total_rows"]
    return {"page": page, "page_size": size, "total_rows": total, "events": rows}
