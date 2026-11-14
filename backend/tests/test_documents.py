"""Document sharing between advisors and clients: who sees, uploads, opens and deletes what.

Uses the hand-built fixture (tests/fixtures.py). The rules mirror holdings: a document is visible only through
an open account in the person's account_access rows.
"""

from __future__ import annotations

import io
import zipfile
from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.fixtures import A1, A2, A3, ADMIN, C1, C2, C3, C4, D1, D2, MISSING_ID, J, K, X, Y
from wealth.api import deps
from wealth.api.main import create_app
from wealth.api.routes_documents import clean_filename
from wealth.storage import MemoryStorage, get_storage

PDF = b"%PDF-1.7\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


@pytest.fixture
def store():
    return MemoryStorage()


@pytest.fixture
def api(conn, store):
    @contextmanager
    def tx():
        with conn.transaction():  # a savepoint per request, like the real per-request transaction
            yield conn

    def write_conn():
        with tx() as c:
            yield c

    app = create_app()
    app.dependency_overrides[deps.get_conn] = lambda: conn
    app.dependency_overrides[deps.get_write_conn] = write_conn
    app.dependency_overrides[get_storage] = lambda: store
    with TestClient(app) as client:
        yield client


def H(kind: str, pid: int) -> dict:
    return {"X-Demo-User": f"{kind}:{pid}"}


def listing(api, kind, pid, **params) -> dict:
    r = api.get("/api/documents", headers=H(kind, pid), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def ids(api, kind, pid, **params) -> set[int]:
    return {d["document_id"] for d in listing(api, kind, pid, **params)["documents"]}


def upload(
    api,
    kind,
    pid,
    account_id,
    *,
    name="proposal.pdf",
    data=PDF,
    title="Proposal",
    doc_type="other",
    note=None,
):
    form = {"account_id": str(account_id), "title": title, "doc_type": doc_type}
    if note:
        form["note"] = note
    return api.post(
        "/api/documents", headers=H(kind, pid), data=form, files={"file": (name, data, "x/ignored")}
    )


def events(conn, document_id):
    return [
        (r["action"], r["person_type"], r["advisor_id"] or r["client_id"])
        for r in conn.execute(
            "SELECT action, person_type, advisor_id, client_id FROM document_events WHERE document_id = %s ORDER BY id",
            (document_id,),
        ).fetchall()
    ]


# --- who sees what -----------------------------------------------------------------------------------


def test_admins_use_their_own_documents_screen(api):
    assert api.get("/api/documents", headers=H("admin", ADMIN)).status_code == 403


def test_each_person_sees_documents_of_their_accounts_only(api):
    assert ids(api, "advisor", A1) == {D1, D2}  # X and J
    assert ids(api, "advisor", A2) == {D2}  # J (Y, Z, W have no documents yet)
    assert ids(api, "advisor", A3) == set()
    assert ids(api, "client", C1) == {D1}
    assert ids(api, "client", C2) == {D2}
    assert ids(api, "client", C3) == {D2}  # joint owner of J
    assert ids(api, "client", C4) == set()


def test_advisor_sharing_one_account_never_sees_the_clients_other_documents(api):
    # C1 uploads to Y (C1 + A2). A1 shares only X with C1, so A1 must not see it.
    doc = upload(api, "client", C1, Y).json()["document_id"]
    assert doc in ids(api, "advisor", A2)
    assert doc in ids(api, "client", C1)
    assert doc not in ids(api, "advisor", A1)
    assert api.get(f"/api/documents/{doc}/file", headers=H("advisor", A1)).status_code == 404


def test_account_filter_cannot_widen_access(api):
    assert ids(api, "advisor", A1, account_id=X) == {D1}
    assert ids(api, "advisor", A1, account_id=Y) == set()  # not theirs: empty, not an error


def test_revoking_access_hides_documents_on_the_next_request(api, conn):
    assert D2 in ids(api, "advisor", A1)
    conn.execute("DELETE FROM account_access WHERE account_id = %s AND advisor_id = %s", (J, A1))
    assert D2 not in ids(api, "advisor", A1)
    assert api.get(f"/api/documents/{D2}/file", headers=H("advisor", A1)).status_code == 404


def test_uploadable_accounts_exclude_closed_and_viewer_access(api, conn):
    conn.execute(
        "INSERT INTO account_access (account_id, person_type, advisor_id, role) VALUES (%s, 'advisor', %s, 'viewer')",
        (X, A3),
    )
    a1 = {
        a["account_id"]
        for a in api.get("/api/documents/accounts", headers=H("advisor", A1)).json()["accounts"]
    }
    assert a1 == {X, J}  # K is closed
    a3 = api.get("/api/documents/accounts", headers=H("advisor", A3)).json()["accounts"]
    assert a3 == []  # viewer: may read, not upload
    assert D1 in ids(api, "advisor", A3)
    assert upload(api, "advisor", A3, X).status_code == 404


# --- uploading ---------------------------------------------------------------------------------------


def test_joint_owner_upload_is_new_for_everyone_else_until_opened(api, conn, store):
    r = upload(api, "client", C2, J, title="Signed agreement", doc_type="agreement", note="Please review")
    assert r.status_code == 201, r.text
    doc = r.json()["document_id"]

    row = conn.execute("SELECT * FROM documents WHERE id = %s", (doc,)).fetchone()
    assert row["uploaded_by_client_id"] == C2 and row["content_type"] == "application/pdf"
    assert store.objects[row["storage_key"]][0] == PDF and row["storage_key"].startswith(f"documents/{J}/")
    assert row["size_bytes"] == len(PDF) and len(row["sha256"]) == 64 and row["note"] == "Please review"

    def entry(kind, pid):
        return next(d for d in listing(api, kind, pid)["documents"] if d["document_id"] == doc)

    assert entry("client", C2)["mine"] is True and entry("client", C2)["is_new"] is False
    for kind, pid in [("client", C3), ("advisor", A1), ("advisor", A2)]:
        assert entry(kind, pid)["is_new"] is True, (kind, pid)
        assert (
            entry(kind, pid)["uploaded_by"] == "Cli 202" and entry(kind, pid)["uploaded_by_type"] == "client"
        )
    assert listing(api, "client", C3)["new_count"] == 1
    assert api.get("/api/documents/new-count", headers=H("client", C3)).json() == {"new_count": 1}

    assert (
        api.get(f"/api/documents/{doc}/file?disposition=inline", headers=H("client", C3)).status_code == 200
    )
    assert entry("client", C3)["is_new"] is False
    assert entry("advisor", A1)["is_new"] is True  # still new for the others
    assert entry("client", C2)["opened_by"] == "Cli 203"  # the uploader sees who reviewed it
    assert events(conn, doc) == [("upload", "client", C2), ("view", "client", C3)]


def test_seeded_documents_are_never_marked_new(api):
    assert listing(api, "advisor", A1)["new_count"] == 0


def test_cannot_upload_to_an_account_you_cannot_see(api, conn, store):
    for account in (Y, K, MISSING_ID):  # someone else's, closed, missing: the same answer
        assert upload(api, "advisor", A1, account).status_code == 404
    assert store.objects == {}
    assert (
        conn.execute("SELECT count(*) AS n FROM documents WHERE storage_key IS NOT NULL").fetchone()["n"] == 0
    )


@pytest.mark.parametrize(
    "name,data,status",
    [
        ("notes.txt", "Plain text, café ✓".encode(), 201),
        ("scan.png", PNG, 201),
        ("photo.JPG", b"\xff\xd8\xff\xe0" + b"\x00" * 16, 201),
        ("letter.docx", docx_bytes(), 201),
        ("fake.pdf", b"just text pretending", 422),  # contents don't match the name
        ("fake.docx", b"PK\x03\x04 not really a zip", 422),
        ("binary.txt", b"abc\x00def", 422),
        ("page.html", b"<script>alert(1)</script>", 422),  # type not allowed
        ("noextension", PDF, 422),
        ("empty.pdf", b"", 422),
    ],
)
def test_file_checks(api, name, data, status):
    assert upload(api, "advisor", A1, X, name=name, data=data).status_code == status


def test_files_over_10_mb_are_refused(api):
    big = b"%PDF-" + b"0" * (10 * 1024 * 1024)
    assert upload(api, "advisor", A1, X, data=big).status_code == 413


def test_stored_filename_is_cleaned(api, conn):
    doc = upload(api, "advisor", A1, X, name="../../etc/passwd.pdf").json()["document_id"]
    row = conn.execute("SELECT original_filename FROM documents WHERE id = %s", (doc,)).fetchone()
    assert row["original_filename"] == "passwd.pdf"
    assert clean_filename('C:\\Users\\x\\"bad"\tname.pdf') == "badname.pdf"
    assert clean_filename(None) == "document"


def test_storage_failure_saves_nothing(api, conn, store):
    store.fail = True
    assert upload(api, "advisor", A1, X).status_code == 502
    assert (
        conn.execute("SELECT count(*) AS n FROM documents WHERE storage_key IS NOT NULL").fetchone()["n"] == 0
    )
    assert conn.execute("SELECT count(*) AS n FROM document_events").fetchone()["n"] == 0


def test_uploads_need_storage_configured(api):
    api.app.dependency_overrides[get_storage] = lambda: None
    assert upload(api, "advisor", A1, X).status_code == 503


def test_bad_form_is_422(api):
    assert upload(api, "advisor", A1, X, doc_type="memo").status_code == 422
    assert upload(api, "advisor", A1, X, title="").status_code == 422


# --- opening -----------------------------------------------------------------------------------------


def test_download_returns_the_file_safely_and_is_recorded(api, conn):
    doc = upload(api, "advisor", A1, X, name="Plan v2.pdf").json()["document_id"]
    r = api.get(f"/api/documents/{doc}/file", headers=H("client", C1))
    assert r.status_code == 200 and r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="Plan v2.pdf"'
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox"
    assert events(conn, doc)[-1] == ("download", "client", C1)


def test_seeded_document_opens_as_text(api):
    r = api.get(f"/api/documents/{D1}/file?disposition=inline", headers=H("client", C1))
    assert r.status_code == 200 and r.text == "Target 60/40.\nRebalance yearly."
    assert r.headers["content-disposition"] == f'inline; filename="investment-policy-statement-{D1}.txt"'


def test_admin_sees_opens_from_the_portals(api, conn):
    doc = upload(api, "client", C2, J).json()["document_id"]
    assert (
        api.get(f"/api/documents/{doc}/file?disposition=inline", headers=H("advisor", A1)).status_code == 200
    )
    assert api.get(f"/api/documents/{doc}/file", headers=H("client", C3)).status_code == 200
    assert api.get(f"/api/admin/documents/{doc}/download", headers=H("admin", ADMIN)).status_code == 200

    log = api.get(f"/api/admin/documents/{doc}", headers=H("admin", ADMIN)).json()["access_log"]
    # The upload itself is not an open. (Order isn't checked: one test transaction gives every row the
    # same timestamp.)
    assert {(e["action"], e["person_type"], e["person_id"]) for e in log} == {
        ("download", "admin", ADMIN),
        ("download", "client", C3),
        ("view", "advisor", A1),
    }
    assert all(e["name"] for e in log) and len({e["key"] for e in log}) == 3


# --- deleting ----------------------------------------------------------------------------------------


def test_only_the_uploader_can_delete_and_it_is_hidden_not_erased(api, conn):
    doc = upload(api, "client", C2, J).json()["document_id"]
    assert api.delete(f"/api/documents/{doc}", headers=H("client", C3)).status_code == 403
    assert api.delete(f"/api/documents/{doc}", headers=H("advisor", A1)).status_code == 403
    assert api.delete(f"/api/documents/{D2}", headers=H("client", C2)).status_code == 403  # seeded, not C2's
    assert api.delete(f"/api/documents/{doc}", headers=H("client", C2)).status_code == 200

    for kind, pid in [("client", C2), ("client", C3), ("advisor", A1)]:
        assert doc not in ids(api, kind, pid)
    assert api.get(f"/api/documents/{doc}/file", headers=H("client", C2)).status_code == 404
    assert conn.execute("SELECT deleted_at FROM documents WHERE id = %s", (doc,)).fetchone()["deleted_at"]
    assert events(conn, doc)[-1] == ("delete", "client", C2)
    # Admins still see it, marked deleted.
    admin_rows = api.get("/api/admin/documents", headers=H("admin", ADMIN)).json()["documents"]
    assert next(d for d in admin_rows if d["document_id"] == doc)["deleted_at"]


# --- admin access to uploaded files ------------------------------------------------------------------


def test_admin_downloads_uploaded_files_and_previews_only_text(api, conn):
    pdf = upload(api, "advisor", A1, X, name="plan.pdf").json()["document_id"]
    txt = upload(api, "client", C1, X, name="questions.txt", data=b"Can we lower fees?").json()["document_id"]
    admin = H("admin", ADMIN)

    r = api.get(f"/api/admin/documents/{pdf}/download", headers=admin)
    assert r.content == PDF and r.headers["content-disposition"] == 'attachment; filename="plan.pdf"'
    assert api.get(f"/api/admin/documents/{pdf}/content", headers=admin).status_code == 409
    assert (
        api.get(f"/api/admin/documents/{txt}/content", headers=admin).json()["text"] == "Can we lower fees?"
    )

    listed = {d["document_id"]: d for d in api.get("/api/admin/documents", headers=admin).json()["documents"]}
    assert listed[txt]["uploaded_by"] == "Cli 201" and listed[txt]["uploaded_by_type"] == "client"
    assert listed[pdf]["previewable"] is False and listed[D1]["previewable"] is True
    actions = [
        r["action"] for r in conn.execute("SELECT action FROM permission_audit ORDER BY id").fetchall()
    ]
    assert actions == ["download_document", "view_document"]  # the refused preview recorded nothing


# --- database rules ----------------------------------------------------------------------------------


def test_a_document_has_at_most_one_uploader(conn):
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(
            """INSERT INTO documents (account_id, title, doc_type, text, size_kb, created_date,
                                      uploaded_by_advisor_id, uploaded_by_client_id)
               VALUES (%s, 't', 'other', 'x', 1, '2026-11-01', %s, %s)""",
            (X, A1, C1),
        )


def test_an_uploaded_file_row_needs_its_file_facts(conn):
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute(
            """INSERT INTO documents (account_id, title, doc_type, size_kb, created_date, storage_key)
               VALUES (%s, 't', 'other', 1, '2026-11-01', 'documents/x')""",
            (X,),
        )
