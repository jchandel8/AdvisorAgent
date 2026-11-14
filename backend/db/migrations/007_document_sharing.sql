-- 007: advisors and clients upload documents to an account they can access, and see who opened them.

-- Uploads store the file in S3 (MinIO locally); seeded documents keep their text in the database.
ALTER TABLE documents ALTER COLUMN text DROP NOT NULL;
ALTER TABLE documents
    ADD COLUMN uploaded_by_client_id integer REFERENCES clients(id) ON DELETE SET NULL,
    ADD COLUMN storage_key text UNIQUE,
    ADD COLUMN content_type text,
    ADD COLUMN original_filename text,
    ADD COLUMN size_bytes bigint CHECK (size_bytes > 0),
    ADD COLUMN sha256 text,
    ADD COLUMN note text,
    ADD COLUMN uploaded_at timestamptz,
    ADD COLUMN deleted_at timestamptz,
    ADD CONSTRAINT documents_one_uploader CHECK (uploaded_by_advisor_id IS NULL OR uploaded_by_client_id IS NULL),
    ADD CONSTRAINT documents_has_content CHECK (text IS NOT NULL OR storage_key IS NOT NULL),
    ADD CONSTRAINT documents_file_fields CHECK (
        storage_key IS NULL
        OR (content_type IS NOT NULL AND original_filename IS NOT NULL AND size_bytes IS NOT NULL AND sha256 IS NOT NULL)
    );

ALTER TABLE documents DROP CONSTRAINT documents_doc_type_check;
ALTER TABLE documents ADD CONSTRAINT documents_doc_type_check
    CHECK (doc_type IN ('ips', 'review_notes', 'statement', 'agreement', 'other'));

-- Who uploaded, viewed, downloaded or deleted a document (advisors and clients). Drives "New" and
-- "Opened by". Admin opens stay in permission_audit.
CREATE TABLE document_events (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id  integer NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    person_type  text NOT NULL CHECK (person_type IN ('advisor', 'client')),
    advisor_id   integer REFERENCES advisors(id) ON DELETE CASCADE,
    client_id    integer REFERENCES clients(id) ON DELETE CASCADE,
    action       text NOT NULL CHECK (action IN ('upload', 'view', 'download', 'delete')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT document_events_person CHECK (
        (person_type = 'advisor' AND advisor_id IS NOT NULL AND client_id IS NULL)
        OR (person_type = 'client' AND client_id IS NOT NULL AND advisor_id IS NULL)
    )
);
CREATE INDEX document_events_doc_idx ON document_events (document_id, created_at DESC);
CREATE INDEX document_events_advisor_idx ON document_events (advisor_id, document_id) WHERE advisor_id IS NOT NULL;
CREATE INDEX document_events_client_idx ON document_events (client_id, document_id) WHERE client_id IS NOT NULL;
