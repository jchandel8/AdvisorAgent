"""search_documents: the access rules, scoping, ranking and text extraction."""

from __future__ import annotations

import io
from datetime import date

import docx
import pytest

from tests.fixtures import A1, A2, A3, C1, C3, C4, D1, D2, MISSING_ID, TODAY, J, K, X, Y, Z
from wealth.mcp.client import LocalToolRunner
from wealth.text_extract import extract_text


def search(conn, advisor, focus=None, **args):
    return LocalToolRunner(conn).call(
        "search_documents", args, advisor_id=advisor, today=TODAY, focus_client_id=focus
    )


def found(conn, advisor, query, **args):
    out = search(conn, advisor, query=query, **args)
    return [r["document_id"] for r in out["results"]] if "results" in out else out


def add_doc(conn, account, title, text=None, *, extracted=None, note=None, deleted=False):
    """A seeded-style document (text) or, when text is None, an uploaded-style one (file fields set)."""
    upload = text is None
    return conn.execute(
        """INSERT INTO documents (account_id, title, doc_type, text, extracted_text, note, size_kb, created_date,
                                  deleted_at, storage_key, content_type, original_filename, size_bytes, sha256)
           VALUES (%(account)s, %(title)s, 'other', %(text)s, %(extracted)s, %(note)s, 1, %(day)s,
                   CASE WHEN %(deleted)s THEN now() END,
                   CASE WHEN %(upload)s THEN gen_random_uuid()::text END,
                   CASE WHEN %(upload)s THEN 'application/pdf' END,
                   CASE WHEN %(upload)s THEN 'file.pdf' END,
                   CASE WHEN %(upload)s THEN 1 END,
                   CASE WHEN %(upload)s THEN repeat('0', 64) END)
           RETURNING id""",
        {
            "account": account,
            "title": title,
            "text": text,
            "extracted": extracted,
            "note": note,
            "day": date(2026, 10, 1),
            "deleted": deleted,
            "upload": upload,
        },
    ).fetchone()["id"]


def test_finds_documents_on_visible_accounts(conn):
    assert found(conn, A1, "college savings") == [D2]  # J: A1 and A2 are both on it
    assert found(conn, A2, "college savings") == [D2]
    assert found(conn, A1, "rebalance") == [D1]
    assert found(conn, A2, "rebalance") == []  # D1 is on X, which A2 can't see


def test_advisor_with_no_access_finds_nothing(conn):
    assert found(conn, A3, "college") == []
    assert found(conn, A3, "rebalance") == []


def test_shared_one_account_advisor_never_finds_the_clients_other_documents(conn):
    y_doc = add_doc(conn, Y, "Trust amendment", "Zebra clause for the family trust.")
    z_doc = add_doc(conn, Z, "Estate memo", "Zebra estate planning memo.")
    assert found(conn, A1, "zebra") == []  # Y is C1's other account, Z is C3's; A1 sees neither
    assert set(found(conn, A2, "zebra")) == {y_doc, z_doc}


def test_deleted_documents_and_closed_accounts_are_never_found(conn):
    add_doc(conn, X, "Old plan", "Quokka strategy.", deleted=True)
    add_doc(conn, K, "Closed account letter", "Quokka closing letter.")
    assert found(conn, A1, "quokka") == []


def test_scope_to_a_client_or_account(conn):
    x_doc = add_doc(conn, X, "Meeting notes", "Discussed the ocelot fund.")
    j_doc = add_doc(conn, J, "Joint notes", "Ocelot fund for the joint account.")
    assert set(found(conn, A1, "ocelot")) == {x_doc, j_doc}
    assert found(conn, A1, "ocelot", client_id=C1) == [x_doc]
    assert found(conn, A1, "ocelot", client_id=C3) == [j_doc]
    assert found(conn, A1, "ocelot", account_id=J) == [j_doc]


def test_forbidden_and_unknown_scopes_look_the_same(conn):
    forbidden_account = search(conn, A1, query="zebra", account_id=Z)
    unknown_account = search(conn, A1, query="zebra", account_id=MISSING_ID)
    no_shared_client = search(conn, A1, query="zebra", client_id=C4)
    assert forbidden_account == unknown_account == no_shared_client == {"error": "not found"}


def test_selected_client_limits_the_search(conn):
    add_doc(conn, X, "C1 notes", "Pangolin review.")
    add_doc(conn, J, "J notes", "Pangolin joint review.")
    assert len(found(conn, A1, "pangolin", focus=C1)) == 1
    assert search(conn, A1, focus=C1, query="pangolin", client_id=C3)["error"] == "outside selected client"


def test_title_matches_rank_above_body_matches(conn):
    body = add_doc(conn, X, "Quarterly letter", "A note about the narwhal allocation.")
    title = add_doc(conn, X, "Narwhal allocation", "Details inside.")
    assert found(conn, A1, "narwhal") == [title, body]


def test_uploaded_file_text_and_note_are_searchable_and_snippets_mark_matches(conn):
    add_doc(conn, X, "Signed proposal.pdf", None, extracted="We propose moving to a capybara income ladder.")
    add_doc(conn, X, "Scan", None, extracted=None, note="Axolotl beneficiary form, please review")
    out = search(conn, A1, query="capybara")
    assert out["result_count"] == 1 and "«capybara»" in out["results"][0]["snippet"].lower()
    assert len(found(conn, A1, "axolotl")) == 1


def test_phrase_and_exclusion_syntax(conn):
    a = add_doc(conn, X, "A", "tax loss harvesting plan")
    b = add_doc(conn, X, "B", "loss of tax documents")
    assert found(conn, A1, '"tax loss"') == [a]
    assert found(conn, A1, "tax -harvesting") == [b]  # tax, but not harvesting


def test_stop_words_only_returns_nothing_not_an_error(conn):
    assert search(conn, A1, query="the and")["results"] == []


@pytest.mark.parametrize(
    "args",
    [
        {"query": "x"},
        {"query": "college", "account_id": X, "client_id": C1},
        {"query": "college", "advisor_id": A2},
        {"query": "college", "limit": 50},
        {"query": "   "},
    ],
)
def test_bad_input_is_rejected(conn, args):
    assert search(conn, A1, **args)["error"] == "invalid input"


# --- text extraction -------------------------------------------------------------------------------------


def pdf_with_text(text: str) -> bytes:
    """A small valid PDF with one page of text (offsets computed so any PDF reader accepts it)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def docx_with_text(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Table cell walrus"
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_extracts_text_from_pdf_docx_and_txt():
    assert "Beneficiary update for the meerkat trust" in extract_text(
        pdf_with_text("Beneficiary update for the meerkat trust"), "application/pdf"
    )
    docx_text = extract_text(
        docx_with_text("Rebalance toward bonds"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert "Rebalance toward bonds" in docx_text and "walrus" in docx_text
    assert extract_text(b"Line one\n\nline\x00two", "text/plain; charset=utf-8") == "Line one line two"


def test_unreadable_files_and_images_give_no_text():
    assert extract_text(b"%PDF-1.7\nnot really a pdf", "application/pdf") is None
    assert extract_text(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "image/png") is None
    assert extract_text(b"   \n ", "text/plain") is None


def test_seeded_documents_need_no_extraction(conn):
    row = conn.execute("SELECT text, extracted_text FROM documents WHERE id = %s", (D1,)).fetchone()
    assert row["text"] and row["extracted_text"] is None and found(conn, A1, "rebalance yearly") == [D1]
