-- Step 7b: AI Finalyst briefs. A brief is prepared for the advisor about one client; nothing goes to the client.
--
-- status: running -> done | failed. stage: the step in progress, shown live in the advisor portal.
-- fingerprint: client, brief type, note, day and the advisor's visible accounts. A finished brief with the same
--   fingerprint is reused instead of paying for a new run (revoking access changes the fingerprint).
-- brief: the Finalyst's structured output; review: the reviewer's verdict and the number check.
CREATE TABLE finalyst_briefs (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    advisor_id    integer NOT NULL REFERENCES advisors(id) ON DELETE CASCADE,
    client_id     integer NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    brief_type    text NOT NULL CHECK (brief_type IN ('portfolio_review', 'market_impact', 'rebalancing', 'meeting_prep')),
    note          text,
    status        text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'failed')),
    stage         text,
    fingerprint   text NOT NULL,
    brief         jsonb,
    review        jsonb,
    error         text,
    run_id        bigint REFERENCES agent_runs(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);
CREATE INDEX finalyst_briefs_advisor_idx ON finalyst_briefs (advisor_id, created_at DESC);
CREATE INDEX finalyst_briefs_reuse_idx ON finalyst_briefs (advisor_id, fingerprint) WHERE status = 'done';
