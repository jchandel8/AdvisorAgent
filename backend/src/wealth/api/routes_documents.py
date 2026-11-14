"""Documents for advisors and clients: list, upload, open, delete.

Access is the account ACL, exactly like holdings: a person sees a document only if it belongs to an open
account in their `visible` set (access.VISIBLE). An advisor who shares one account with a client sees only
that account's documents. Revoking access hides them on the next request.

- Upload: owners, joint owners and advisors (not viewers) to an account they can access. The file is checked
  (size, allowed type, and that its contents really are that type), stored in S3 (a local S3 server in docker compose) under a
  random key, and the row + "upload" event are written in the same transaction. If storing fails, nothing
  is saved.
- Open: the API checks access, records a "view" or "download" event, then streams the bytes itself, so
  the bucket never needs a public URL. Responses are no-store and sandboxed.
- "New": uploaded by someone else and not yet opened by you.
- Delete: only the uploader; hidden (deleted_at), not erased, and recorded.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import uuid
import zipfile
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from wealth.access import VISIBLE
from wealth.api.deps import CurrentUser, current_user, get_write_conn
from wealth.storage import Storage, get_storage
from wealth.text_extract import extract_text

router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_BYTES = 10 * 1024 * 1024
DOC_TYPES = ("statement", "review_notes", "agreement", "ips", "other")


def require_person(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if user.kind not in ("advisor", "client"):
        raise HTTPException(403, "This page is for advisors and clients.")
    return user


# --- file checks -------------------------------------------------------------------------------------


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "word/document.xml" in z.namelist()
    except zipfile.BadZipFile:
        return False


def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


# extension -> (content type we store and serve, check on the actual bytes)
FILE_TYPES = {
    ".pdf": ("application/pdf", lambda d: d.startswith(b"%PDF-")),
    ".png": ("image/png", lambda d: d.startswith(b"\x89PNG\r\n\x1a\n")),
    ".jpg": ("image/jpeg", lambda d: d.startswith(b"\xff\xd8\xff")),
    ".jpeg": ("image/jpeg", lambda d: d.startswith(b"\xff\xd8\xff")),
    ".txt": ("text/plain; charset=utf-8", _is_text),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _is_docx,
    ),
}
ALLOWED = "PDF, TXT, PNG, JPG or DOCX"


def check_file(filename: str, data: bytes) -> str:
    """The content type to store, or a 422 explaining what's wrong. The browser's own type is ignored."""
    if not data:
        raise HTTPException(422, "That file is empty.")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Files can be at most 10 MB.")
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in FILE_TYPES:
        raise HTTPException(422, f"Upload a {ALLOWED} file.")
    content_type, matches = FILE_TYPES[ext]
    if not matches(data):
        raise HTTPException(422, f"That file isn't a real {ext[1:].upper()} file. Upload a {ALLOWED} file.")
    return content_type


def clean_filename(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[\x00-\x1f\x7f\"]", "", base).strip() or "document"
    return base[-120:]


def file_response(*, data: bytes, content_type: str, filename: str, inline: bool) -> Response:
    disposition = "inline" if inline else "attachment"
    ascii_name = filename.encode("ascii", "ignore").decode() or "document"
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{ascii_name}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",  # opened in a tab, an uploaded file can't run scripts
        },
    )


def seeded_filename(title: str, document_id: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "document"
    return f"{slug}-{document_id}.txt"


def document_bytes(doc: dict, storage: Storage | None) -> tuple[bytes, str, str]:
    """(bytes, content type, filename) for a document row with text, storage_key, content_type, ..."""
    if doc["storage_key"] is None:  # seeded documents keep their text in the database
        return (
            doc["text"].encode("utf-8"),
            "text/plain; charset=utf-8",
            seeded_filename(doc["title"], doc["id"]),
        )
    if storage is None:
        raise HTTPException(503, "Document storage isn't set up on this server.")
    return storage.get(doc["storage_key"]), doc["content_type"], doc["original_filename"]


# --- SQL ---------------------------------------------------------------------------------------------

# coalesce: a NULL uploader column must mean "not me" (false), never unknown (NULL).
UPLOADER_IS_ME = """coalesce(
    (%(viewer_kind)s = 'advisor' AND d.uploaded_by_advisor_id = %(viewer_id)s)
    OR (%(viewer_kind)s = 'client' AND d.uploaded_by_client_id = %(viewer_id)s),
    false
)"""
EVENT_IS_ME = "(e.person_type = %(viewer_kind)s AND coalesce(e.advisor_id, e.client_id) = %(viewer_id)s)"

LIST_SQL = f"""
WITH {VISIBLE}
SELECT d.id AS document_id, d.title, d.doc_type, d.note, d.created_date, d.uploaded_at,
       d.size_kb, d.content_type, d.original_filename,
       a.id AS account_id, a.account_name,
       CASE WHEN d.uploaded_by_client_id IS NOT NULL THEN 'client'
            WHEN d.uploaded_by_advisor_id IS NOT NULL THEN 'advisor' END AS uploaded_by_type,
       coalesce(uc.first_name || ' ' || uc.last_name, ua.first_name || ' ' || ua.last_name) AS uploaded_by,
       {UPLOADER_IS_ME} AS mine,
       (d.uploaded_at IS NOT NULL AND NOT {UPLOADER_IS_ME} AND NOT EXISTS (
            SELECT 1 FROM document_events e
            WHERE e.document_id = d.id AND e.action IN ('view', 'download') AND {EVENT_IS_ME}
       )) AS is_new,
       (SELECT string_agg(DISTINCT coalesce(oc.first_name || ' ' || oc.last_name,
                                            oa.first_name || ' ' || oa.last_name), ', ')
          FROM document_events e
          LEFT JOIN clients oc ON oc.id = e.client_id
          LEFT JOIN advisors oa ON oa.id = e.advisor_id
         WHERE e.document_id = d.id AND e.action IN ('view', 'download') AND NOT {EVENT_IS_ME}) AS opened_by
FROM visible v
JOIN accounts a ON a.id = v.account_id
JOIN documents d ON d.account_id = a.id AND d.deleted_at IS NULL
LEFT JOIN clients uc ON uc.id = d.uploaded_by_client_id
LEFT JOIN advisors ua ON ua.id = d.uploaded_by_advisor_id
WHERE (%(account_id)s::int IS NULL OR a.id = %(account_id)s::int)
  AND (%(like)s = '%%%%' OR lower(d.title || ' ' || a.account_name) LIKE %(like)s)
ORDER BY coalesce(d.uploaded_at, d.created_date::timestamptz) DESC, d.id DESC
LIMIT 500"""

UPLOADABLE_SQL = f"""
WITH {VISIBLE}
SELECT a.id AS account_id, a.account_name, a.account_type, me.role,
       (SELECT string_agg(c.first_name || ' ' || c.last_name, ', ' ORDER BY x.role DESC, c.id)
          FROM account_access x JOIN clients c ON c.id = x.client_id WHERE x.account_id = a.id) AS clients
FROM visible v
JOIN accounts a ON a.id = v.account_id
JOIN account_access me ON me.account_id = a.id
 AND ((%(viewer_kind)s = 'advisor' AND me.advisor_id = %(viewer_id)s)
      OR (%(viewer_kind)s = 'client' AND me.client_id = %(viewer_id)s))
WHERE me.role <> 'viewer'
ORDER BY clients, a.account_name, a.id"""

ONE_SQL = f"""
WITH {VISIBLE}
SELECT d.*, {UPLOADER_IS_ME} AS mine
FROM visible v JOIN documents d ON d.account_id = v.account_id
WHERE d.id = %(document_id)s AND d.deleted_at IS NULL"""


def _event(conn, user: CurrentUser, document_id: int, action: str) -> None:
    conn.execute(
        """INSERT INTO document_events (document_id, person_type, advisor_id, client_id, action)
           VALUES (%s, %s, %s, %s, %s)""",
        (
            document_id,
            user.kind,
            user.id if user.kind == "advisor" else None,
            user.id if user.kind == "client" else None,
            action,
        ),
    )


def _visible_document(conn, user: CurrentUser, document_id: int) -> dict:
    row = conn.execute(ONE_SQL, {**user.viewer.params(), "document_id": document_id}).fetchone()
    if row is None:  # not there, deleted, or not yours: the same answer
        raise HTTPException(404, "Document not found.")
    return row


# --- endpoints ---------------------------------------------------------------------------------------


@router.get("")
def list_documents(
    account_id: int | None = Query(default=None, gt=0),
    q: str = Query(default="", max_length=100),
    user: CurrentUser = Depends(require_person),
    conn=Depends(get_write_conn),
):
    rows = conn.execute(
        LIST_SQL,
        {**user.viewer.params(), "account_id": account_id, "like": f"%{q.strip().lower()}%"},
    ).fetchall()
    return {"new_count": sum(1 for r in rows if r["is_new"]), "documents": rows}


@router.get("/new-count")
def new_count(user: CurrentUser = Depends(require_person), conn=Depends(get_write_conn)):
    """How many documents wait for you to open them (the number on the Documents menu item)."""
    row = conn.execute(
        f"SELECT count(*) FILTER (WHERE is_new) AS n FROM ({LIST_SQL}) docs",
        {**user.viewer.params(), "account_id": None, "like": "%%"},
    ).fetchone()
    return {"new_count": row["n"]}


@router.get("/accounts")
def uploadable_accounts(user: CurrentUser = Depends(require_person), conn=Depends(get_write_conn)):
    """Accounts this person may upload to (open, with access, not as a viewer)."""
    return {"accounts": conn.execute(UPLOADABLE_SQL, user.viewer.params()).fetchall()}


@router.post("", status_code=201)
async def upload_document(
    account_id: int = Form(gt=0),
    title: str = Form(min_length=1, max_length=120),
    doc_type: Literal["statement", "review_notes", "agreement", "ips", "other"] = Form(),
    note: str | None = Form(default=None, max_length=500),
    file: UploadFile = File(),
    user: CurrentUser = Depends(require_person),
    conn=Depends(get_write_conn),
    storage: Storage | None = Depends(get_storage),
):
    allowed = conn.execute(
        f"SELECT 1 FROM ({UPLOADABLE_SQL}) u WHERE u.account_id = %(account_id)s",
        {**user.viewer.params(), "account_id": account_id},
    ).fetchone()
    if allowed is None:
        raise HTTPException(404, "You can't upload to that account.")
    if storage is None:
        raise HTTPException(503, "Document uploads aren't set up on this server.")

    data = await file.read(MAX_BYTES + 1)
    filename = clean_filename(file.filename)
    content_type = check_file(filename, data)
    extracted = extract_text(data, content_type)  # for document search; None if the file has no readable text
    key = f"documents/{account_id}/{uuid.uuid4()}"
    row = conn.execute(
        """INSERT INTO documents (account_id, title, doc_type, size_kb, created_date, uploaded_by_advisor_id,
                                  uploaded_by_client_id, storage_key, content_type, original_filename,
                                  size_bytes, sha256, note, uploaded_at, extracted_text)
           VALUES (%(account_id)s, %(title)s, %(doc_type)s, %(size_kb)s, %(today)s, %(advisor)s, %(client)s,
                   %(key)s, %(content_type)s, %(filename)s, %(size)s, %(sha)s, %(note)s, now(), %(extracted)s)
           RETURNING id""",
        {
            "account_id": account_id,
            "title": title.strip(),
            "doc_type": doc_type,
            "size_kb": max(1, math.ceil(len(data) / 1024)),
            "today": date.today(),
            "advisor": user.id if user.kind == "advisor" else None,
            "client": user.id if user.kind == "client" else None,
            "key": key,
            "content_type": content_type,
            "filename": filename,
            "size": len(data),
            "sha": hashlib.sha256(data).hexdigest(),
            "note": (note or "").strip() or None,
            "extracted": extracted,
        },
    ).fetchone()
    _event(conn, user, row["id"], "upload")
    try:
        storage.put(key, data, content_type)
    except Exception as exc:  # the request transaction rolls back the row and the event
        raise HTTPException(502, "The file couldn't be stored, so nothing was saved. Try again.") from exc
    return {"document_id": row["id"], "title": title.strip(), "account_id": account_id}


@router.get("/{document_id}/file")
def open_document(
    document_id: int,
    disposition: Literal["inline", "attachment"] = "attachment",
    user: CurrentUser = Depends(require_person),
    conn=Depends(get_write_conn),
    storage: Storage | None = Depends(get_storage),
):
    doc = _visible_document(conn, user, document_id)
    data, content_type, filename = document_bytes(doc, storage)
    _event(conn, user, document_id, "view" if disposition == "inline" else "download")
    return file_response(
        data=data, content_type=content_type, filename=filename, inline=disposition == "inline"
    )


@router.delete("/{document_id}")
def delete_document(
    document_id: int, user: CurrentUser = Depends(require_person), conn=Depends(get_write_conn)
):
    doc = _visible_document(conn, user, document_id)
    if not doc["mine"]:
        raise HTTPException(403, "Only the person who uploaded a document can delete it.")
    conn.execute("UPDATE documents SET deleted_at = now() WHERE id = %s", (document_id,))
    _event(conn, user, document_id, "delete")
    return {"deleted": document_id}
