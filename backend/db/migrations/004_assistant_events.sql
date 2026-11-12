-- 004: one row per assistant request, for rate limiting, the daily cap and misuse review.
-- outcome: answered | cached | blocked_scope | blocked_manipulation | blocked_unverified | guard_error
--          | rate_limited | error
CREATE TABLE assistant_events (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    advisor_id  integer NOT NULL REFERENCES advisors(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    outcome     text NOT NULL CHECK (outcome IN (
                    'answered', 'cached', 'blocked_scope', 'blocked_manipulation', 'blocked_unverified',
                    'guard_error', 'rate_limited', 'error')),
    question    text NOT NULL,             -- truncated to 500 characters
    reason      text                       -- the guard's short reason, when blocked
);
CREATE INDEX assistant_events_advisor_time_idx ON assistant_events (advisor_id, created_at DESC);
CREATE INDEX assistant_events_blocked_idx ON assistant_events (created_at DESC)
    WHERE outcome LIKE 'blocked%';
