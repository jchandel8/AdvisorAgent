# AI Finalyst: plan (for approval)

The AI Finalyst is a second AI feature in the advisor portal. The advisor picks one client and a brief type, and a
team of agents prepares a **brief for the advisor**: the facts, what is happening in the market around the client's
holdings, and suggestions with evidence. The advisor reviews it; nothing goes to the client. It is built on the
step 6 foundation from CLAUDE.md: MCP servers, document search, tracing and evals.

Decisions already made by the owner:
- web news comes from a search API (Tavily: free tier, built for agents) behind our own Market MCP server;
- prices come from the seeded database, so the brief's numbers match the portals.

## 1. The workflow: orchestrated in code, not a free-roaming agent

```
advisor picks client + brief type
        │
  [1] Router (Haiku) ── scope check, brief type, tickers/sectors to watch ── off-topic → fixed reply
        │
        ├──────────────── run in parallel ────────────────┐
  [2a] Facts agent (Sonnet)                       [2b] Research agent (Sonnet)
       Portfolio MCP + document search                 Market MCP (news search, sector moves)
       → facts JSON (holdings, drift, gains,           → news items, each with URL, date, source
         reviews, notes from documents)                  (only tickers/sectors, never client data)
        └──────────────────────┬──────────────────────────┘
  [3] Analytics (Analytics MCP, plain code): drift vs target, concentration, gains, what-if rebalance
        │
  [4] Finalyst (Opus): writes the brief: summary, 3–5 suggestions, each with reasons, evidence, risks, confidence
        │
  [5] Reviewer (Sonnet): every number must appear in facts or analytics; every market claim needs a source;
      fits the client's risk profile; written for the advisor, not as an instruction to the client
        │  fails → one revision by the Finalyst, then return with the reviewer's flags shown
        ▼
  brief saved + shown, with every step traced
```

Why code orchestration: each step has a fixed job, input and output schema, so it is testable, cheap, and easy to
explain. The model decides *what to look up* inside a step; the code decides *the order of the steps*.

## 2. MCP servers (new package `backend/src/wealth/mcp/`)

MCP (Model Context Protocol) is a standard way to expose tools to AI models. Our agents act as MCP clients; the
servers own the tools. Built with the official Python `mcp` SDK.

| Server | Tools | Data |
|---|---|---|
| Portfolio | the six existing tools + `search_documents` | Postgres, always through the access layer |
| Analytics | `allocation_drift`, `concentration`, `rebalance_preview`, `gain_summary` | pure functions on numbers passed in; no database |
| Market | `search_news(query, days)`, `sector_moves(sector, period)`, `security_profile(symbol)` | Tavily for news; seeded prices for moves |

Security, same rule as today: identity never comes from the model.
- The agent gets a **short-lived signed internal token** (HMAC, 2 minutes, carrying advisor ID and selected client)
  from the backend. The Portfolio server verifies it and takes the advisor only from it. Tool arguments have no
  `advisor_id`.
- The servers are mounted in the same FastAPI app under `/mcp/*`, but accept **loopback requests only**. Traffic
  through the AWS load balancer is refused even with a valid token.
- **Data egress guard** on the Market server: a query may contain only tickers, sector names and generic market
  words. Anything matching a client or advisor name, an account number, or an email is refused before the search API
  is called, and the refusal is logged.
- News results are cached for 6 hours (fewer API calls; repeatable demos).
- The existing assistant moves to the Portfolio MCP server too, so one tool implementation serves both features.

## 3. Document search (step 6b)

- Postgres full-text search (`tsvector`, GIN index) over seeded document text and text extracted from uploaded PDF,
  DOCX and TXT files (`pypdf`, `python-docx`), extracted at upload time.
- `search_documents(query, client_id?)` returns short snippets with document ID and title, only on visible accounts.
- No vector database for now: full-text search needs no extra infrastructure and is easy to explain. Embeddings can
  come later.

## 4. Tracing, full agent logs and evals (step 6c)

The owner wants to see exactly what the agents did, with real values, for both the assistant and the Finalyst.

- New tables `agent_runs` (one per question or brief: who, client, type, status, tokens, cache hit rate, cost, time)
  and `agent_steps` (one per model call or tool call, in order).
- Each step stores its **full detail**:
  - for a tool call: the tool name, the exact arguments the model sent (after validation), and the full result
    returned to the model, client data included;
  - for a model call: the model, the text it wrote, the tool calls it asked for, the stop reason, tokens in and out,
    cache read and write tokens, and latency;
  - router classification, reviewer verdicts and revision notes;
  - Market searches: the query, whether the egress guard allowed it, and the URLs returned;
  - errors, refusals and limit hits.
- What is never stored: the internal MCP token, API keys and passwords. The system prompts are stored once per
  version (by hash), not in every run.
- **Admin portal → Agent runs:** a list of runs (filter by advisor, client, feature, outcome) and a run's timeline.
  Each step expands to show its request and response as readable JSON. The Assistant log links to each run's trace.
- Safeguards, because this lets admins read client portfolio data, which they couldn't before:
  - admins only;
  - **opening a trace is itself audited** (`view_agent_run` in the audit log, like document previews);
  - traces are deleted automatically after 30 days (a setting);
  - each stored payload is capped at 64 KB, with a visible "truncated" marker.
- Evals: about 25 questions with expected facts computed from the seeded database, graded by code (are the right
  clients named, do the numbers match), plus a Claude grader for "no instructions to the client, sources cited".
  A no-cost version with a fake model runs in CI; the real-model run is manual, because it costs money.
- Per-run cost and cache hit rate are measured from these traces, so the Finalyst limits are set from real numbers.

## 4b. Caching, used deliberately at every layer

Every cache key that can hold client data includes the advisor ID and a fingerprint of the accounts they can see
right now. Nothing is shared between advisors, and revoking access makes old entries unusable at once.

| Layer | What is cached | Rule |
|---|---|---|
| Claude prompt caching | Each agent role's fixed prefix (tool definitions and system prompt) | One explicit cache breakpoint at the end of the fixed prefix, plus automatic caching for the growing tool loop. Prefixes are kept byte-for-byte stable: tools sorted by name, no dates or names in system prompts (today's date moves into the user message; the current assistant puts it in the system prompt, which resets the cache daily), and one fixed model, effort and thinking setting per role. |
| Shared facts block | The Facts and Analytics output | Placed first in the Finalyst's and Reviewer's messages with a breakpoint, so the draft, the review and the revision all read it from the cache instead of paying for it three times. |
| Answer cache (exists) | Assistant answers, until 24 hours or midnight | Key gains the account fingerprint. |
| Brief reuse | A saved brief for the same advisor, client and type on the same day, with the same account fingerprint | Shown with "Run again" in place of a new paid run. |
| Tool results within a run | Identical Portfolio or Analytics calls in one run | Memoized for that run only, never across runs or people. |
| Market news | Search results per normalized query | 6 hours in Postgres; also saves free-tier quota. |
| Sector moves | Computed from seeded prices | Cached per sector, period and price date (the data changes only when re-seeded). |

Check that it works, now and later:
- the cache read and write tokens of every model call are stored in `agent_steps`, and the admin trace shows the hit
  rate;
- a CI test renders each role's prompt twice and asserts the bytes before the breakpoint are identical;
- a manual real-model check asserts the second identical request reads from the cache.

Model minimums matter: prompts shorter than the model's minimum silently don't cache (Haiku 4.5 on AWS needs 4,096
tokens, Sonnet 4.6 needs 1,024, and the 5.5 models need 512). The small router prompt won't cache on AWS. That is
expected; it's cheap. The large prefixes, tools and the facts block, are the ones that matter.

## 5. Finalyst feature (step 7)

- **Advisor portal → AI Finalyst page:** pick a client (required; access checked), pick a brief type (portfolio
  review, market impact, rebalancing ideas, meeting prep), then Run.
  - Live progress while it works (Routing → Facts → Research → Analytics → Drafting → Review), streamed from the
    server.
  - The brief has a summary, suggestion cards (reasons, evidence chips linking to facts or sources, risks,
    confidence), a sources list with links, and the reviewer's notes.
  - Every brief carries a footer: "Prepared for the advisor's review. Not advice to the client."
- **Saved briefs:** table `finalyst_briefs`; the advisor sees their history per client. Revoking access hides them.
- **Limits:** 5 briefs an hour and 20 a day per advisor; at most 20 tool calls and a token budget per run; timeouts
  per step.
- **Models:** Router Haiku; Facts, Research and Reviewer Sonnet; Finalyst Opus 5.5 locally. On Bedrock, the newest
  Opus the AWS account can use (checked before deploying; Sonnet 4.6 if none). Each model is set separately in config.

## 6. Build order (each part: its own branch, tests, merged on your OK)

| Part | What | Key tests |
|---|---|---|
| 6a | Portfolio + Analytics MCP servers; the assistant switched to MCP | ACL through MCP; bad, expired or missing internal token; non-loopback refused; model-supplied advisor ID rejected |
| 6b | Document search + text extraction | shared-one-account advisor can't find the client's other documents; deleted documents not found |
| 6c | Full agent traces, admin Agent runs screen, caching checks, evals | every step recorded with arguments and results; opening a trace is audited; secrets never stored; traces expire; cached prefixes stay byte-stable |
| 7a | Market MCP server with Tavily, egress guard, cache | client and advisor names refused; works without a key (feature off, clear message) |
| 7b | Finalyst workflow, page, saved briefs, limits | fake-model tests of every step, revision path, budgets; Playwright run with a stubbed model |
| 7c | Docs: architecture section + diagram, interview guide, PROGRESS | — |
| AWS | Tavily key in Secrets Manager (persistent stack), task gets the new env vars; deploy **only with your yes** | CI green |

Then resume and LinkedIn entries.

## 7. What I need from you

- A Tavily API key (free account at tavily.com), saved by you in `.env` as `TAVILY_API_KEY=...`. Don't paste it
  into chat. Until it exists, the Market server answers "news search isn't set up" and everything else works.
- Approved on 2026-11-13, with two additions: deliberate caching (4b) and full agent logs for admins (4).
