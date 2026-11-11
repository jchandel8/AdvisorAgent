# Progress log

Handoff notes so work can resume in any session. Update at the end of every step.

## Status

| Step | State |
|---|---|
| 1. Schema, data generator, tools, terminal agent, access tests | **Done** (2026-11-11), 102 tests passing |
| 2. FastAPI endpoints + Angular portals (advisor, client) | Not started — wait for owner's go |
| 3. Cognito login, Playwright E2E | Not started |
| 4. Admin portal, audit log, demo page, reset script | Not started |
| 5. AWS deploy (ECS Express, RDS, Secrets Manager), IaC, CI | Not started |
| 6. MCP server, document search, guardrails, evals, tracing, rate limits | Not started |

## How to run (local)

```bash
docker compose up -d db                     # Postgres 17, database "wealth"
cd backend
uv sync                                     # Python 3.12 venv + deps (uv installs 3.12 if needed)
uv run python -m wealth.datagen             # migrate + regenerate + reload all data + write ../demo_users.csv
uv run pytest -q                            # all tests (creates/drops a separate wealth_test database)
uv run wealth-agent --advisor-id 1          # terminal agent; advisor 1 and 2 are the demo advisors
```

Env (`.env` at repo root, see `.env.example`): `DATABASE_URL`, `ANTHROPIC_API_KEY`, optional `ANTHROPIC_MODEL`
(default `claude-sonnet-5-5`), `TEST_DATABASE_URL` (default: same server, db `wealth_test`), `DATA_ANCHOR_DATE`,
`ANSWER_CACHE_ENABLED` / `ANSWER_CACHE_TTL_HOURS` (24) / `ANSWER_CACHE_MAX_ENTRIES` (1000).
CLI flags: `--model`, `--no-cache`, `--today`.

## Layout

```
backend/
  db/migrations/001_schema.sql   core schema (plain SQL, applied in filename order by wealth.migrate)
  db/migrations/002_reference_data_and_cache.sql   sectors/asset_classes/currencies lookups, answer_cache
  src/wealth/
    config.py      env settings (only place that reads os.environ)
    db.py          psycopg pool; read_only() = READ ONLY transaction
    migrate.py     migration runner (schema_migrations table)
    access.py      VISIBLE / SCOPED / snapshot_sql() fragments, ToolContext, scoped_account_ids  <- ACL core
    tools/         schemas.py (pydantic inputs), one module per tool, registry.py (execute_tool)
    agent/         prompts.py, loop.py (AdvisorAgent manual tool loop), answer_cache.py, cli.py (wealth-agent)
    datagen/       securities.py, prices.py, generate.py (pure), load.py (COPY + CSV), __main__.py
  tests/           fixtures.py (hand-built ACL scenario), test_schema, test_access_rules,
                   test_agent_loop (fake model), test_answer_cache, test_generator (pure),
                   test_seeded_db (dev DB)
demo_users.csv     generated; demo users first (DEMO notes); no passwords
```

## Key decisions (and why)

- **account_access has two FK columns** (`advisor_id`, `client_id`) plus `person_type`, with CHECKs that exactly
  one is set and the role fits the type. Real foreign keys instead of a polymorphic `person_id`. The view
  `v_account_access` shows the CLAUDE.md `(person_type, person_id)` shape. Owner chose this.
- **One ACL definition**: `access.VISIBLE` CTE (advisor's ACL rows on open accounts). Every tool query joins it.
  Client scope = visible accounts that client has an ACL row on, so advisors see only shared accounts.
- **Forbidden == missing**: tools return `{"error": "not found"}` for both, so IDs can't be probed.
- **advisor_id never reaches the model**: tool JSON schemas omit it; pydantic `extra="forbid"` rejects it if the
  model sends it; `execute_tool(..., advisor_id=session)` injects it. Tools run in READ ONLY transactions.
- **Plain SQL + psycopg 3, no ORM**, so the ACL join is visible. Math (market value, weights, gains, weighted
  returns, totals) is in SQL; Python only shapes the JSON.
- **Mock data is simulated, not random rows**: seeded price path (84 months, grid = anchor minus whole months),
  per-account transaction replay → holdings snapshots (24 dates: anchor and 23 prior months) are exactly the
  replayed transactions; cost basis = average cost; sells store `realized_gain` (added column, like a broker
  confirm; needed for the step 2 realized gain/loss chart). Performance = time-weighted buy-and-hold per period,
  chained; pre-history back-cast from the opening portfolio; NULL before open_date.
- **CASH** is a security (price 1) holding the uninvested balance. Transactions `amount` is always positive.
- **Dates relative to anchor** (`DATA_ANCHOR_DATE`, default today) so "reviews due this month" always has answers.
  Same seed + anchor ⇒ identical data (tested by hash). Re-run datagen to refresh dates (it is the reset script).
- **Joint accounts count fully** in each joint owner's totals (`get_my_clients`). For an advisor book total,
  sum DISTINCT accounts (step 2 dashboard must do this, or totals double-count joint accounts).
- **Agent**: manual tool-use loop (not the beta tool runner) so the security boundary is explicit.
  Default model `claude-sonnet-5-5` (owner's choice). On the 4 demo questions Haiku 5.5 and Sonnet 5.5 both
  matched ground truth; total ~$0.005 on Haiku vs ~$0.09 on Sonnet, so Haiku is the fallback if cost matters. Effort `medium`, max 10 tool rounds,
  append-only history. `fallbacks="default"` (beta `server-side-fallback-2026-07-01`) is sent only for models
  that support it (Opus/Sonnet 5.5 etc., not Haiku; Claude API only, not Bedrock).
- **Lookup tables** `sectors`, `asset_classes`, `currencies` with FKs from `securities`; `securities.currency`
  added. **USD only** (owner's decision); other currencies would need an FX table for totals. The pydantic
  Literals in tools/schemas.py must match the lookup tables (tested).
- **Filters**: `get_holdings` and `get_transactions` take `sectors`, `asset_classes`, `currencies`;
  `get_transactions` also `types`. Applied in SQL; filters can never widen access (tested). Holdings return
  `portfolio_market_value`, `selection` totals, and every row as `pct_of_selection` and `pct_of_portfolio`.
  `detail`: `totals` (no positions) / `summary` (top 10, default) / `full`.
- **Query performance**: snapshot CTE uses LATERAL lookups through the (account_id, as_of_date, symbol) index
  (it was seq-scanning all 170k holdings rows: 246 ms -> 5 ms). Scoped tools build the snapshot only for
  accounts in scope. Datagen runs ANALYZE after loading. All tools now 10-21 ms.
- **Caching** (cost is model tokens, not DB time):
  1. Anthropic prompt caching: system+tools block and top-level `cache_control` (whole conversation), 5-min TTL.
  2. Answer cache (`answer_cache` table): key = SHA-256 of advisor, fingerprint of advisor's visible accounts,
     prompt+tools fingerprint, model, date, normalized conversation. Exact repeats only (no "similar question"
     matching). TTL 24h or next local midnight; LRU eviction above max entries; datagen truncates it.
     Access grants/revokes change the key automatically, so stale-permission answers can't be served.
  3. No tool-result cache on purpose: DB is 10-21 ms and caching it risks serving data after access is revoked.
- `get_performance` returns `partial_periods` when some accounts lack a figure (too new), because the
  combined number then covers only the others.
- No closed accounts in generated data (closed-account hiding is covered by the test fixture).

## Data facts (seed 42, anchor 2026-11-11)

10 advisors, 200 clients (52 couples + 96 singles), 348 accounts (52 joint = 15%, 33 with two advisors),
781 ACL rows, ~170k holdings rows, ~61k transactions (mostly dividends), 7,745 performance rows, 683 documents.
Demo advisors 1 and 2 (most clients); 9 tech-overweight clients (55-70% tech) with reviews this month;
demo split client 10 (advisor 2 sees only some accounts); joint demo client 63. See demo_users.csv.

## Known follow-ups

- The example question still makes ~16 tool calls (one per client due). About $0.06 on Sonnet, $0.003 on Haiku; the answer cache makes repeats free. Optional
  step 6 idea: a single "sector exposure across my clients" tool (adds a tool beyond the CLAUDE.md list).
- On AWS (step 5) with several API containers, the answer cache already works (shared Postgres table).
- Step 2: DB-backed endpoints must reuse `access.VISIBLE` (advisor) and add a client-side equivalent
  (`account_access.client_id`). Add a local-only "pick demo user" setting that cannot be enabled on AWS.
- **UI (step 2+)**: owner wants a modern, elegant UI built with the `ui-ux-pro-max-skill`
  (https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), possibly combined with other design skills.
  Review that third-party repo before installing it.
- Step 5: Bedrock client + model ID `anthropic.claude-opus-5-5`; server-side `fallbacks` is not available there.
