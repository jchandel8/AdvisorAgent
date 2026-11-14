"""Pull searchable text out of an uploaded file (PDF, DOCX, TXT) at upload time.

Best effort: a file we can't read still uploads; it just isn't searchable by its contents (its title and
note still are). Images have no text (no OCR). Output is capped and stripped of NUL characters, which
Postgres text can't store.
"""

from __future__ import annotations

import io
import logging

log = logging.getLogger(__name__)

MAX_CHARS = 200_000  # plenty for search; keeps the full-text index small
MAX_PDF_PAGES = 300


def extract_text(data: bytes, content_type: str) -> str | None:
    try:
        if content_type.startswith("application/pdf"):
            text = _pdf(data)
        elif content_type.startswith("application/vnd.openxmlformats-officedocument.wordprocessingml"):
            text = _docx(data)
        elif content_type.startswith("text/plain"):
            text = data.decode("utf-8", errors="replace")
        else:
            return None
    except Exception:  # a malformed file must never fail the upload
        log.warning("could not extract text from a %s upload", content_type, exc_info=True)
        return None
    text = " ".join(text.replace("\x00", " ").split())  # one line of words; search ignores layout
    return text[:MAX_CHARS] or None


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages[:MAX_PDF_PAGES]:
        parts.append(page.extract_text() or "")
        if sum(map(len, parts)) > MAX_CHARS:
            break
    return "\n".join(parts)


def _docx(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)
