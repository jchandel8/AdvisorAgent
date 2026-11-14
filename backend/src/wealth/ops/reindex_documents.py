"""Fill in searchable text for uploaded files that don't have it yet (uploaded before step 6b).

Usage:
    uv run python -m wealth.ops.reindex_documents          # report what would change
    uv run python -m wealth.ops.reindex_documents --apply  # read each file from storage and save its text

New uploads get their text when they are uploaded, so this is a one-off for older files. Deleted
documents are skipped; files the extractor can't read keep extracted_text NULL.
"""

from __future__ import annotations

import argparse

from wealth.db import connection
from wealth.storage import get_storage
from wealth.text_extract import extract_text


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="save the extracted text")
    args = parser.parse_args()

    storage = get_storage()
    if storage is None:
        raise SystemExit("DOCUMENTS_BUCKET is not set, so there are no uploaded files to read.")
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, storage_key, content_type FROM documents
               WHERE storage_key IS NOT NULL AND extracted_text IS NULL AND deleted_at IS NULL
               ORDER BY id"""
        ).fetchall()
        print(f"{len(rows)} uploaded document(s) without searchable text.")
        done = 0
        for row in rows:
            text = extract_text(storage.get(row["storage_key"]), row["content_type"])
            if text is None:
                print(f"  #{row['id']}: no readable text")
                continue
            print(f"  #{row['id']}: {len(text)} characters")
            if args.apply:
                conn.execute("UPDATE documents SET extracted_text = %s WHERE id = %s", (text, row["id"]))
                done += 1
        if args.apply:
            conn.commit()
            print(f"Saved text for {done} document(s).")
        else:
            print("Nothing saved. Re-run with --apply to save.")


if __name__ == "__main__":
    main()
