-- 003: demo user list (for the Demo page) and stored agent conversations.

-- Suggested demo users, written by the data loader. Same two-FK pattern as account_access.
CREATE TABLE demo_users (
    id           integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    person_type  text NOT NULL CHECK (person_type IN ('advisor', 'client')),
    advisor_id   integer REFERENCES advisors(id) ON DELETE CASCADE,
    client_id    integer REFERENCES clients(id) ON DELETE CASCADE,
    note         text NOT NULL,
    sort_order   integer NOT NULL,
    CONSTRAINT demo_person_matches_type CHECK (
        (person_type = 'advisor' AND advisor_id IS NOT NULL AND client_id IS NULL)
        OR (person_type = 'client' AND client_id IS NOT NULL AND advisor_id IS NULL)
    )
);

-- One row per assistant conversation. history = the exact messages sent to the model (append-only);
-- transcript = questions and final answers only (used for the answer-cache key and the chat UI).
CREATE TABLE agent_conversations (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    advisor_id       integer NOT NULL REFERENCES advisors(id) ON DELETE CASCADE,
    focus_client_id  integer REFERENCES clients(id) ON DELETE SET NULL,
    history          jsonb NOT NULL DEFAULT '[]',
    transcript       jsonb NOT NULL DEFAULT '[]',
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agent_conversations_advisor_idx ON agent_conversations (advisor_id, updated_at DESC);
