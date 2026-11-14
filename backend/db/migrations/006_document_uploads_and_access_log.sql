-- 006: who uploaded each document, and an audit trail for admins opening documents (admin Documents screen).

-- The person who uploaded the document. Seeded documents are attributed to the account's first advisor
-- (lowest advisor ID with access), the same rule the data loader applies after a reset.
ALTER TABLE documents
    ADD COLUMN uploaded_by_advisor_id integer REFERENCES advisors(id) ON DELETE SET NULL;

UPDATE documents d
SET uploaded_by_advisor_id = (
    SELECT min(x.advisor_id) FROM account_access x WHERE x.account_id = d.account_id
);

CREATE INDEX documents_created_idx ON documents (created_date DESC, id DESC);

-- Admins may read documents, but every preview and download is recorded, like a permission change.
ALTER TABLE permission_audit DROP CONSTRAINT permission_audit_action_check;
ALTER TABLE permission_audit ADD CONSTRAINT permission_audit_action_check CHECK (
    action IN ('grant', 'revoke', 'create_user', 'create_account', 'view_document', 'download_document')
);
ALTER TABLE permission_audit
    ADD COLUMN document_id integer REFERENCES documents(id) ON DELETE SET NULL;

CREATE INDEX permission_audit_admin_idx ON permission_audit (admin_id, created_at DESC);
CREATE INDEX permission_audit_document_idx ON permission_audit (document_id, created_at DESC)
    WHERE document_id IS NOT NULL;
