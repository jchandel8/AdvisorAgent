-- Step 6b: full-text search over documents (seeded text and text extracted from uploaded files).
--
-- extracted_text: text pulled out of an uploaded PDF, DOCX or TXT when it is uploaded (NULL for images,
-- for files the extractor couldn't read, and for seeded documents, which keep their text in `text`).
-- search_tsv: Postgres full-text index, kept up to date by the database itself (a generated column).
-- Weights: title (A) counts most, then the uploader's note (B), then the body (C).
ALTER TABLE documents ADD COLUMN extracted_text text;

ALTER TABLE documents ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title, '')), 'A')
    || setweight(to_tsvector('english', coalesce(note, '')), 'B')
    || setweight(to_tsvector('english', coalesce(text, extracted_text, '')), 'C')
) STORED;

CREATE INDEX documents_search_idx ON documents USING gin (search_tsv);
