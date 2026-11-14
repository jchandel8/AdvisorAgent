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

## 4. Tracing and evals (step 6c)

- New tables `agent_runs` (one per brief or question: who, client, type, status, total tokens, cost, time) and
  `agent_steps` (each model call or tool call: step name, model, tokens in/out, latency, tool name, error).
- Admin portal: **Agent runs** screen with a run's step-by-step timeline. It shows tool names and timings, but not the
  client data inside them.
- Evals: about 25 questions with expected facts computed from the seeded database, graded by code (are the right
  clients named, do the numbers match), plus a Claude grader for "no instructions to the client, sources cited".
  A no-cost version with a fake model runs in CI; the real-model run is manual, because it costs money.
- Per-run cost is measured here, so the Finalyst limits are set from real numbers, not guesses.

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
| 6c | Tracing tables, admin Agent runs screen, evals | every step recorded; admin sees no client data in traces |
| 7a | Market MCP server with Tavily, egress guard, cache | client and advisor names refused; works without a key (feature off, clear message) |
| 7b | Finalyst workflow, page, saved briefs, limits | fake-model tests of every step, revision path, budgets; Playwright run with a stubbed model |
| 7c | Docs: architecture section + diagram, interview guide, PROGRESS | — |
| AWS | Tavily key in Secrets Manager (persistent stack), task gets the new env vars; deploy **only with your yes** | CI green |

Then resume and LinkedIn entries.

## 7. What I need from you

- A Tavily API key (free account at tavily.com), saved by you in `.env` as `TAVILY_API_KEY=...`. Don't paste it
  into chat. Until it exists, the Market server answers "news search isn't set up" and everything else works.
- Approval of this plan, or changes. I start with 6a.
