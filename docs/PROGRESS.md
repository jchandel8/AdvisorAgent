# Progress log

Handoff notes so work can resume in any session. Update at the end of every step.

## Status

| Step | State |
|---|---|
| 1. Schema, data generator, tools, terminal agent, access tests | **Done** (2026-11-11), 102 tests passing |
| 2. FastAPI endpoints + Angular portals (advisor, client) | **Done** (2026-11-12): 144 backend + 7 frontend tests |
| 3. Cognito login, Playwright E2E | **Done** (2026-11-12). Cognito pool `us-west-1_yZ66inLgw` created with the owner's permission. Owner still to run `wealth.ops.demo_logins --apply` |
| 4. Admin portal, audit log, demo page, reset script | **Done** (2026-11-12): 227 backend, 9 frontend, 6 browser tests |
| 5. AWS deploy (ECS Express, RDS, Secrets Manager), IaC, CI | **Deployed** (2026-11-13): https://ad-4e693211c8514b9389b0a39a34b07394.ecs.us-west-1.on.aws (Cognito callbacks added). Fixes found on the way: OIDC subject now has owner/repo IDs; Express needs `log_stream_prefix`; set `auto_scaling_metric`/`target_value` (provider 6.73 bug) and untainted the service. Default VPC egress works (no NAT). Next: owner tests phase 9 |
| Extras after 5 | Bedrock on AWS (Sonnet 4.6 / Haiku 4.5); admin drilldowns + Documents; document sharing (S3). Merged to main 2026-11-13; AWS torn down, next deploy needs the owner's yes |
| 6a. MCP servers (Portfolio, Analytics); assistant uses MCP | **Done on branch `feature/mcp-servers`** (2026-11-13): 341 backend tests. Not merged yet |
| 6b, 6c, 7 (AI Finalyst) | Planned in `docs/finalyst-plan.md` (approved 2026-11-13 with full admin traces + caching added) |

## How to run (local)

Whole stack (what the demo uses):

```bash
docker compose up        # db + api (migrates, seeds if empty, live reload) + web (ng serve with /api proxy)
# http://localhost:4200  -> Demo page: pick an advisor in a normal window, a client in a private window
```

Node runs only inside the `web` container (host Node is v12, too old for Angular 22). Run frontend commands
with `docker compose exec web npx ng build|test`. Backend tools on the host:

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
  src/wealth/api/   FastAPI: main.py (startup guard), deps.py (demo login, connections), routes_client.py,
                    routes_advisor.py (assistant endpoint), routes_common.py, queries.py, conversations.py
  Dockerfile        API image (same image locally and on AWS)
frontend/           Angular 22 app (zoneless, standalone, signals, strict templates), Tailwind v4, ECharts
  src/app/core/     api.ts, models.ts, session.ts (demo user + interceptor + guards), theme.ts, format.ts
  src/app/shared/   ui.ts (icons, swatch, signed values, states), chart.ts (ECharts + table view), filters.ts
  src/app/layout/   shell.ts (portal rail / bottom tabs)
  src/app/pages/    demo, client/{dashboard,holdings,transactions,performance}, advisor/{dashboard,accounts,
                    assistant}, profile
design-system/advisoragent/MASTER.md   design source of truth (tokens, type, charts, rules)
.claude/skills/     ui-ux-pro-max (reviewed, MIT) + Anthropic frontend-design, used for all UI work
demo_users.csv     generated; demo users first (DEMO notes); no passwords
```

## Step 3: sign-in (Cognito)
- `AUTH_MODE=demo|cognito` (config.py). Demo = local picker, refused on AWS. Cognito = `api/cognito.py` verifies
  the ACCESS token: RS256 via the pool's JWKS (cached), issuer, exp (30 s leeway), `token_use=access`,
  `client_id`, exactly one group of advisors/clients/admins. Identity: Cognito username == DB username, group ==
  table. Admin tokens get 403 until step 4.
- Frontend: `core/auth.ts` reads `/api/auth/config`, then oidc-client-ts authorization code + PKCE through the
  hosted sign-in page; Bearer token on /api calls; sign-out hits Cognito `/logout`. Pages: /login,
  /auth/callback. The demo picker exists only in demo mode.
- Terraform (`infra/persistent`, run with `infra/tf.sh`, Terraform 1.17.2 in Docker, local state for now):
  Lite user pool, admin-only sign-up, groups, public PKCE app client, hosted domain
  `advisoragent-<account-id>`. `plan` = 6 to add. NOT applied (owner's rule: ask before any AWS change).
- `python -m wealth.ops.demo_logins [--apply]`: creates/updates Cognito logins for `demo_users`, password from
  `DEMO_PASSWORD`. The owner runs it (Claude doesn't create accounts or handle passwords).
- Playwright (`e2e/`, image v1.64.1, `docker compose --profile e2e run --rm e2e`): demo-mode suite passes;
  cognito suite (`E2E_AUTH=cognito`) is for the owner after the logins exist.
- cryptography is pinned <49: newer releases have no Intel-macOS wheels.

## Step 4: admin portal
- Migration 005: `admins`, `demo_users.admin_id`, `permission_audit` (append-only; written in the SAME
  transaction as each change). Demo admin: `morgan.lee` (fixed, not Faker, so other data is unchanged).
- Sign-in: `admin:<id>` demo header / Cognito `admins` group -> `admins` table. `CurrentUser(kind, id, name)`;
  `.viewer` only for advisors/clients; `require_admin`.
- API `/api/admin/*` (routes_admin.py): users (list, create = DB row + Cognito login in the right group with
  DEMO_PASSWORD; login failure rolls back the insert), accounts (list, create with owners + advisors),
  access (list, grant, revoke; an account keeps >= 1 client owner and >= 1 advisor), people search, audit log,
  assistant log. Admins manage access; they don't read portfolios.
- UI `/admin` (slate band): Users, Accounts, Permissions (two-step revoke), Audit log, Assistant log.
- Demo page works in both modes: picker in demo mode; usernames + "Sign in" in cognito mode.
  `/api/demo/users` is public (usernames, never passwords).
- Reset: `python -m wealth.ops.reset --yes` = reload all data (clears conversations, cache, logs) + demo
  logins when AUTH_MODE=cognito. Admin-created Cognito logins are left in the pool.
- E2E covers the CLAUDE.md demo script: admin grants Anthony account 19, he sees 3 of Kevin's accounts,
  admin revokes, back to 2, both in the audit log.
- **Drilldowns + Documents (2026-11-13, branch feature/admin-drilldowns):** migration 006 adds
  `documents.uploaded_by_advisor_id` (seeded docs: the account's lowest-ID advisor, same rule in migration and
  loader) and `permission_audit.document_id` + actions `view_document` / `download_document`.
  API: `GET /users/{kind}/{id}` (profile + all accounts with role, clients, advisors; admins: profile only),
  `GET /accounts/{id}` (facts, access, document titles; no values), `GET /documents` (search title/account/ID,
  type filter, 50/page), `GET /documents/{id}` (facts + last 20 opens; not audited, no text),
  `/documents/{id}/content` (preview) and `/download` (.txt attachment, no-store) are each audited in the same
  transaction. `GET /audit?admin_id=` for an admin's own activity. Owner decisions taken as recommended:
  admins may read documents with every open audited; download as .txt; uploader recorded, S3 uploads later.
  UI: names in Users and Accounts link to `/admin/users/:kind/:id` and `/admin/accounts/:id`; new
  Documents nav item, `/admin/documents` and `/admin/documents/:id` (Preview, Download .txt via HttpClient blob
  so the token is sent). E2E: admin clicks client -> account -> document -> download.
- **Document sharing (2026-11-13, branch feature/document-sharing, built on feature/admin-drilldowns):**
  advisors and clients upload to an account they can access (not as a viewer; open accounts only), and
  everyone with access sees it. `routes_documents.py`: `GET /api/documents` (via access.VISIBLE, with
  `is_new`, `mine`, `opened_by`), `/new-count`, `/accounts` (uploadable), `POST` (multipart; 10 MB; PDF, TXT,
  PNG, JPG, DOCX; contents checked against the type; filename cleaned; row + event + S3 put in one
  transaction), `/{id}/file?disposition=inline|attachment` (streamed by the API: no-store, nosniff,
  CSP sandbox; records view/download), `DELETE` (uploader only; soft delete). Migration 007: upload columns on
  `documents` (one uploader, file facts required), type `other`, `document_events`. Storage `wealth/storage.py`:
  S3 on AWS (task role, bucket `advisoragent-documents-<account>`, private, AES256, TLS-only, force_destroy,
  policy `document-files` = Put/Get on documents/*), locally `adobe/s3mock` in compose (MinIO images are no
  longer published). The API streams files instead of presigned URLs: one code path, no public bucket URL.
  New-count badge on the Documents menu (refreshed on navigation). Admin screens show uploads (client or
  advisor uploader, deleted marker); admin preview only for text. Tests: 30 in test_documents.py; E2E advisor
  uploads, client (private window) sees New + menu count, downloads, advisor sees "opened by", deletes.

## Step 5: AWS deploy (code written, NOT applied)

Nothing below exists on AWS yet except the Cognito pool. Every `apply` needs the owner's explicit yes.

- `Dockerfile` (repo root): multi-stage; builds Angular, serves it from FastAPI (`STATIC_DIR`), runs
  `backend/scripts/start.sh` (migrate -> `datagen --if-empty` -> `demo_logins --apply` when cognito and
  `DEMO_PASSWORD` set -> uvicorn `--proxy-headers`). Image `advisoragent:local` smoke-tested locally.
- `config.py`: if `DATABASE_URL` is empty, builds it from `DB_HOST/DB_USER/DB_PASSWORD/DB_NAME/DB_PORT`
  with `sslmode=require` (RDS-managed secret injects the password). Tested in `test_deploy_config.py`.
- Terraform (run with `infra/tf.sh`, Terraform 1.17.2 in Docker, AWS provider 6.73), three stacks:
  1. `infra/bootstrap` (local state): tfstate S3 bucket, GitHub OIDC provider, deploy role
     `advisoragent-github-deploy` (main branch only; AdministratorAccess for now; tighten later). Plan: 7 to add.
  2. `infra/persistent` (local state): Cognito (applied) + NEW ECR repo `advisoragent` and secrets
     `advisoragent/demo-password` (value put by the owner, not in TF). The Anthropic key secret was removed
     2026-11-13 (AWS uses Bedrock; there is no Claude API key on AWS).
  3. `infra/app` (S3 backend): default VPC (no NAT), RDS Postgres 17 db.t4g.micro private,
     ECS Express Mode service (port 8000, health `/api/health`, 0.5 vCPU / 1 GB, 1 task), IAM roles, logs.
     Output `APP_URL`. Destroyed by Teardown; persistent stack kept.
- Workflows: `ci.yml` (ruff, pytest with Postgres service, frontend test+build), `deploy.yml` (manual;
  OIDC -> ECR push -> terraform apply -> prints APP_URL), `teardown.yml` (manual; type DESTROY).
  Need repo variables `AWS_DEPLOY_ROLE_ARN`, `TFSTATE_BUCKET` and a GitHub environment `demo`.
- After the first deploy: add `APP_URL` to `app_urls` in `infra/persistent` and re-apply so Cognito
  accepts callbacks from the AWS URL.
- Unverified risk: Express Mode tasks in the default VPC need a public IP for internet access (Anthropic
  API, Secrets Manager, ECR) since there is no NAT. Check on first deploy.
- **Bedrock (2026-11-13, branch feature/bedrock):** `LLM_PROVIDER` picks the client (`wealth/llm.py`): `anthropic`
  locally (API key), `bedrock` on AWS (`AnthropicBedrock`, ECS task role, no key). Task role policy `invoke-claude`
  allows InvokeModel only on the configured US inference profiles, plus their foundation models only via those
  profiles (`bedrock:InferenceProfileArn` condition; checked with simulate-custom-policy). The API key secret is no
  longer injected on AWS. The 5.5 models are listed but return 403 "not available for this account", so AWS uses
  `us.anthropic.claude-sonnet-4-6` + `us.anthropic.claude-haiku-4-5-20251001-v1:0` (verified live from the laptop:
  agent answered with tools; guard classified in-scope/out-of-scope/manipulation). Haiku 4.5 rejects `effort`, so
  the guard omits it for that model. Server-side `fallbacks` is Claude-API-only and turned off on Bedrock.
- ALB security group (created by ECS Express, `AmazonECSManaged`): 80 and 443 open to 0.0.0.0/0 and ::/0. Only an
  HTTPS:443 listener exists, so port 80 gets no answer; the LB is IPv4-only, so the ::/0 rules match nothing.
  Outbound only to the task SG on 8000; task SG allows 8000 only from the ALB SG. Left as AWS manages it.

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

### Step 2 decisions
- **Viewer** (`access.Viewer(kind, id)`): VISIBLE works for advisors and clients; tools and portal API share
  the same queries. Client endpoints never take a client_id: scope is the signed-in client (+ optional
  account_id, 404 if not theirs).
- **Local demo login**: header `X-Demo-User: advisor:<id>|client:<id>`, only when `DEMO_AUTH_ENABLED=true`;
  the API refuses to start (and 401s every request) if an AWS runtime marker env var is present
  (`config.running_on_aws`). Cognito replaces this in step 3 (`deps.current_user` is the one place to change).
- **Assistant endpoint** `POST /api/advisor/assistant/messages`: conversations stored in `agent_conversations`
  (history = exact model messages as JSON, transcript = Q/A). No DB connection held during the model call;
  save uses optimistic locking on `updated_at` (409 on conflict). The selected client is re-checked before
  every tool round (`access_revoked` stop). Answer cache + prompt caching from step 1 apply.
- **UI stack** (owner's choices): Tailwind v4 + Angular CDK, Apache ECharts (lazy-loaded, SVG renderer, aria),
  light default + dark toggle. Every chart has a text summary and "Show as table".
- **Design** (MASTER.md): account swatches (slot = account_id % 8) are the identity across portals; portal
  bands (advisor evergreen, client ink blue); statement sentences instead of hero numbers; Instrument Sans
  with verified tabular figures. Palettes validated with the dataviz validator (green/red failed CVD, so
  charts use blue/red; green/red only on text with ▲▼ and +/−).
- Filters and selections live in the URL (`?account=`, `?client=`, `?page=`) for deep links and back button.
- Generator numbers duplicate account names per owner ("Individual 2").

### Assistant guardrails (added 2026-11-12, after the owner found it answering "diameter of the moon")
Layers, in order (code: `agent/guard.py`, `agent/loop.py`, `api/usage.py`, migration 004):
1. **Limits**: 10 questions/minute and 100/day per advisor (`ASSISTANT_PER_MINUTE`, `ASSISTANT_PER_DAY`).
   Each request reserves its `assistant_events` row under a per-advisor advisory lock, so concurrent requests
   can't slip past. 429 with `Retry-After`. `rate_limited` rows don't count toward the limits.
2. **Scope check**: `claude-haiku-5-5` with structured output classifies in_scope / out_of_scope /
   manipulation, given the last 2 Q/A, the selected client and the advisor's name. Fails closed (error,
   refusal, bad JSON -> blocked). Blocked questions get fixed backend text and never reach the main model.
   Cached answers skip it (they passed it when first asked).
3. **Main prompt**: strict scope; facts and analysis only, no buy/sell/rebalance recommendations (owner's
   decision); no message can change who it acts for.
4. **Answer check**: money/percent figures with no tool call anywhere in the conversation -> fixed reply,
   and the turn is removed from the history.
5. **Audit**: every request in `assistant_events` (outcome + short reason); admin portal (step 4) can show it.
6. **Selected client = hard scope** (owner's decision, after a "Moon" question with Renee Wilson selected
   listed Moody/Moore clients): `focus_client_id` narrows the VISIBLE CTE to that client's accounts, client
   lists return only that client (not joint co-owners), and a tool call naming another client_id returns
   "outside selected client". Enforced in the tool layer, not the prompt.
Eval: `uv run python evals/run_scope_guard.py` (42 labelled cases, ~$0.01). Latest: 20/20 in-scope allowed,
21/22 blocked + 1 blocked by fail-closed. Known miss: "Danielle Johnson's clients" (another advisor's name)
is classed in-scope, but no data can leak: the tools only return the signed-in advisor's accounts. The ACL,
not the guard, is the access control; the guard is a cost and misuse filter.
- No closed accounts in generated data (closed-account hiding is covered by the test fixture).

## Data facts (seed 42, anchor 2026-11-11)

10 advisors, 200 clients (52 couples + 96 singles), 348 accounts (52 joint = 15%, 33 with two advisors),
781 ACL rows, ~170k holdings rows, ~61k transactions (mostly dividends), 7,745 performance rows, 683 documents.
Demo advisors 1 and 2 (most clients); 9 tech-overweight clients (55-70% tech) with reviews this month;
demo split client 10 (advisor 2 sees only some accounts); joint demo client 63. See demo_users.csv.

## Plan for 2026-11-14 (agreed 2026-11-13)

AWS changes (deploy, teardown, IAM, Bedrock access) still need the owner's explicit yes each time.

1. Verify the redeploy after the teardown test: startup logs, sign-in on the new URL, and that
   `cognito_allow_url.py` added the new URL and removed the old `.on.aws` one (its first real run).
2. Bedrock (own branch, before the admin drilldowns): confirm the region/inference profile and model ID for
   Sonnet 5.5 and Haiku 5.5; `LLM_PROVIDER` setting (anthropic locally, bedrock on AWS) with tests for both
   clients; task role gets `bedrock:InvokeModel` on Claude models only; drop the API key secret from the task;
   owner enables model access in the Bedrock console (add to DEPLOY.md); redeploy and ask a live question;
   update the diagrams and interview guide. Trade-off: no server-side `fallbacks` on Bedrock.
3. Admin drilldowns + Documents screen (branch). Owner to confirm 3 decisions first (recommended: admins may
   view/download documents with each view/download audited; download as .txt; record uploader only, S3
   uploads later). Client/advisor -> profile + accounts; account -> details + users; admin -> profile + own
   audit log; Documents list -> details (uploader, dates, download). Works locally and on AWS.
4. Hardening (small): narrow the deploy role from AdministratorAccess; branch protection on main; Playwright
   e2e in CI; README with screenshots; short demo video.
5. Later: step 6 (MCP server, document search, guardrails, evals, tracing), then the suggestions
   multi-agent system (router, facts agent, suggestions agent on Opus, reviewer, advisor-responsibility footnote).

## Step 6a: MCP servers (2026-11-13, branch feature/mcp-servers)

- SDK: `mcp==2.3.0`. In 2.x FastMCP is renamed `MCPServer` (`mcp.server.mcpserver`); HTTP client is
  `httpx2`; `Client(streamable_http_client(url, http_client=...))` takes the transport, not opened streams.
- `wealth/mcp/portfolio.py`: low-level `Server` serving the existing registry (one security boundary,
  `execute_tool`; schemas byte-identical). `wealth/mcp/analytics.py`: `MCPServer` decorators, pure functions
  (allocation_drift, concentration, rebalance_preview). Both mounted in the FastAPI app at `/mcp/portfolio/`
  and `/mcp/analytics/` (stateless, JSON responses); their session managers run in the app lifespan.
- Identity: `wealth/mcp/internal_token.py`, HS256 JWT, audience per server, 2 minutes, key random per process
  (or `MCP_SIGNING_KEY`). Only works with one uvicorn worker per container (true locally and on AWS).
- Guard (`wealth/mcp/guard.py`): refuse proxy headers (X-Forwarded-For etc., because start.sh trusts proxy
  headers from anyone), non-loopback client, missing/invalid token; SDK refuses non-loopback Host (421).
  Verified live: outside call 403; another process in the same container 401 (signature).
- Agent: `AdvisorAgent(tools=...)`; default MCP in the app, `LocalToolRunner` when a test connection is given
  and in the CLI. Tool schemas are canonical (keys sorted), because the SDK reorders keys (prompt cache).
- Each MCP tool call is about 3 loopback POSTs (protocol probe, initialize, call). Fine for now; revisit with a
  per-turn session if latency matters. Tool list is fetched once per process.
- Live check: assistant as Anthony answered "38 clients" with get_my_clients over MCP.

## Known follow-ups

- The example question still makes ~16 tool calls (one per client due). About $0.06 on Sonnet, $0.003 on Haiku; the answer cache makes repeats free. Optional
  step 6 idea: a single "sector exposure across my clients" tool (adds a tool beyond the CLAUDE.md list).
- On AWS (step 5) with several API containers, the answer cache already works (shared Postgres table).
- Dev ergonomics: on macOS the web container rebuilds in ~5–15 s; the first use of a new npm dependency
  triggers a one-time Vite pre-bundle and page reload (a page can look blank until it finishes).
- Swatches inside assistant answers (MASTER.md idea) are not implemented; answers name accounts in text.
- Step 3: Playwright E2E for both portals; replace demo header with Cognito JWT verification.
- Step 2: DB-backed endpoints must reuse `access.VISIBLE` (advisor) and add a client-side equivalent
  (`account_access.client_id`). Add a local-only "pick demo user" setting that cannot be enabled on AWS.
- **UI (step 2+)**: owner wants a modern, elegant UI built with the `ui-ux-pro-max-skill`
  (https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), possibly combined with other design skills.
  Review that third-party repo before installing it.
- Step 5: Bedrock client + model ID `anthropic.claude-opus-5-5`; server-side `fallbacks` is not available there.
- Step 5 cost plan (discussed 2026-11-12, estimates to confirm in the AWS Pricing Calculator): always-on
  ~$60-90/month + Claude usage (ALB ~$20, Fargate API ~$18, RDS t4g.micro ~$15, public IPv4 ~$7-11, rest small).
  Owner wants to turn the demo on and off: plan a disposable stack (IaC destroy/deploy, ~$1-3/month while off,
  ~15 min to bring up) with GitHub Actions "Deploy demo" / "Tear down" buttons and an optional auto-teardown.
  Keep secrets, ECR images and the Cognito pool; data is re-seeded on each deploy (migrate -> datagen
  --if-empty -> create Cognito demo users). Avoid a NAT Gateway; serve the Angular build from S3 + CloudFront.
  RDS auto-restarts after 7 days stopped, so prefer teardown over pause. Serverless (Lambda + Aurora
  Serverless v2) is the fallback if idle cost matters more than the ECS/RDS portfolio story.
