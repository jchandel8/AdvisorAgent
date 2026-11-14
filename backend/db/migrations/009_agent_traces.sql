-- Step 6c: full traces of what the AI agents did, for the admin portal.
--
-- agent_runs: one per assistant question (and, from step 7, per Finalyst brief).
-- agent_steps: every scope check, model call, tool call and note in a run, in order, with the exact request
--   and response (client data included). Payloads over 64 KB are stored truncated (truncated = true).
-- agent_prompts: each system prompt version stored once (runs refer to it by hash).
-- Never stored: internal MCP tokens, API keys, passwords. Runs are deleted after TRACE_RETENTION_DAYS (30).

CREATE TABLE agent_prompts (
    hash        text PRIMARY KEY,                 -- sha256 of the role, text and tool definitions
    role        text NOT NULL,                    -- e.g. 'assistant', 'scope_check'
    text        text NOT NULL,
    tools       jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agent_runs (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feature             text NOT NULL CHECK (feature IN ('assistant', 'finalyst')),
    advisor_id          integer NOT NULL REFERENCES advisors(id) ON DELETE CASCADE,
    focus_client_id     integer REFERENCES clients(id) ON DELETE SET NULL,
    assistant_event_id  bigint REFERENCES assistant_events(id) ON DELETE SET NULL,
    conversation_id     uuid,
    prompt_hash         text REFERENCES agent_prompts(hash),
    question            text NOT NULL,
    answer              text,
    outcome             text NOT NULL,
    model               text,
    started_at          timestamptz NOT NULL,
    finished_at         timestamptz NOT NULL,
    model_calls         integer NOT NULL DEFAULT 0,
    tool_calls          integer NOT NULL DEFAULT 0,
    input_tokens        integer NOT NULL DEFAULT 0,
    output_tokens       integer NOT NULL DEFAULT 0,
    cache_read_tokens   integer NOT NULL DEFAULT 0,
    cache_write_tokens  integer NOT NULL DEFAULT 0,
    cost_usd            numeric(12, 6)            -- NULL when a model's price isn't known (e.g. on Bedrock)
);
CREATE INDEX agent_runs_started_idx ON agent_runs (started_at DESC, id DESC);
CREATE INDEX agent_runs_advisor_idx ON agent_runs (advisor_id, started_at DESC);
CREATE INDEX agent_runs_event_idx ON agent_runs (assistant_event_id) WHERE assistant_event_id IS NOT NULL;

CREATE TABLE agent_steps (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id              bigint NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    seq                 integer NOT NULL,
    kind                text NOT NULL CHECK (kind IN ('scope_check', 'model', 'tool', 'cache', 'note')),
    name                text NOT NULL,          -- model name, tool name, or what the note is about
    started_at          timestamptz NOT NULL,
    duration_ms         integer NOT NULL DEFAULT 0,
    request             jsonb,
    response            jsonb,
    truncated           boolean NOT NULL DEFAULT false,
    is_error            boolean NOT NULL DEFAULT false,
    stop_reason         text,
    input_tokens        integer,
    output_tokens       integer,
    cache_read_tokens   integer,
    cache_write_tokens  integer,
    UNIQUE (run_id, seq)
);

-- Opening a trace shows client data, so it is recorded like a document preview.
ALTER TABLE permission_audit DROP CONSTRAINT permission_audit_action_check;
ALTER TABLE permission_audit ADD CONSTRAINT permission_audit_action_check CHECK (
    action IN ('grant', 'revoke', 'create_user', 'create_account', 'view_document', 'download_document',
               'view_agent_run')
);
ALTER TABLE permission_audit ADD COLUMN agent_run_id bigint REFERENCES agent_runs(id) ON DELETE SET NULL;
