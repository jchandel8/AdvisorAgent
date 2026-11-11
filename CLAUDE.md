# Wealth-Advisor Agent (Project 1)

## Goal
A portfolio project showing a secure, production-style AI agent. Financial advisors ask questions in plain English
("which of my clients are overweight in tech and have a review due this month?") and an agent answers by calling
tools over mock portfolio, CRM and document data. Two web portals (advisor and client) show the same data from
each side, so the permission model can be checked side by side.

## Permission model (accounts are the center)
- Accounts are the central entity. Holdings, transactions, performance and documents belong to an account.
- Access is granted per account through the `account_access` table (an ACL). A row links one account to one
  person (advisor or client) with a role.
- A client sees only the accounts they have an ACL row for.
- An advisor sees ONLY the accounts they have an ACL row for. An advisor can see a client if they share at least
  one account, but sees only the shared accounts, not the client's other accounts.
- An account can have more than one client (joint accounts) and more than one advisor.

## The one security rule
The user's identity comes ONLY from the verified login token (Cognito JWT, from week 2), never from the prompt or
the model. In week 1 the terminal app takes the advisor ID as a startup setting to stand in for the token.
Every tool receives `advisor_id` from the backend, never from the model, and every query joins through
`account_access` to return only accounts that advisor can access. The model never queries the database directly.

## Stack
- Python 3.12, FastAPI backend: one REST API serving both portals, plus the agent endpoint
- Angular frontend with two portals (advisor and client) in one app, charts with a standard chart library
- Claude via tool use (Anthropic API locally; Amazon Bedrock later)
- Postgres: Docker locally (docker-compose.yml), RDS on AWS
- AWS Cognito for login (week 2), ECS Express Mode + RDS + Secrets Manager (week 3)
- Terraform or CDK for infrastructure, GitHub Actions for CI
- Tools exposed through an MCP server (week 3)

## Data model (mock data, generated with Faker)
Conventions: snake_case names, integer or UUID primary keys, and every link is a foreign key by ID (never by name).
Derived values (client counts, market value, gains) are computed in SQL, not stored.

- advisors: id, username, first_name, last_name, email, phone, certifications, city, state
- clients: id, username, first_name, last_name, email, phone, address, city, state, risk_profile,
  target_allocation (JSON by asset class), next_review_date
- accounts: id, account_name, account_type (individual, joint, IRA, trust), description, open_date, close_date
- account_access: account_id, person_type (advisor or client), person_id, role (owner, joint_owner, advisor, viewer)
- securities: symbol, description, sector, asset_class
- holdings: id, account_id, symbol, quantity, cost_basis, price, as_of_date
- transactions: id, account_id, trade_date, type (buy, sell, dividend, deposit, withdrawal), symbol, quantity,
  price, amount
- performance: id, account_id, as_of_date, return_1d, return_1m, return_3m, return_6m, return_ytd, return_1y,
  return_2y, return_3y, return_5y
- documents: id, account_id, title, doc_type, text, size_kb, created_date

## Data volume
Use a fixed random seed so the data is the same every run.
- 10 advisors, 200 clients
- About 350 accounts: most individual, about 15% joint (2 clients), about 10% shared by 2 advisors
- About 60 real securities across sectors; 10 to 30 holdings per account
- About 2 years of transactions per account
- Monthly performance rows for the last 24 months per account
- 1 to 3 documents per account
- Spread next_review_date over the next 90 days, with some overdue
- Make a few clients clearly overweight in tech, so the example question has a real answer

## Web portals
One frontend app with three portals, one backend API, one Cognito user pool with three groups (`advisors`, `clients`,
`admins`).
- Advisor portal at `/advisor`, client portal at `/client`, admin portal at `/admin`. A user can only open the
  portal for their group.
- The backend checks the role and the account ACL on every API call. The frontend hiding a screen is not security.
- Both portals run locally (`docker compose up` starts Postgres, API and frontend) and on AWS, with the same code.
- To compare side by side, open the advisor portal in a normal window and the client portal in a private window.

### Client portal
- Dashboard: list of the client's accounts (account name, market value), total portfolio value, and a chart of
  the top 10 holdings across all their accounts.
- Holdings: table of all holdings with an account filter (all accounts or one), and a top 10 holdings chart that
  follows the filter.
- Transactions: table of transactions with an account filter, and a chart of realized gain/loss (from sells,
  average cost method) and unrealized gain/loss (current holdings vs cost basis).
- Performance: portfolio performance across all accounts (market-value weighted) with an account filter; a growth
  chart over time plus the return periods (1D through 5Y).
- Profile: username, first name, last name, email, phone, address. Read-only.

### Advisor portal
- Dashboard: list of the advisor's clients with each client's portfolio value (only accounts the advisor can
  access), and a total.
- Accounts: pick a client, see that client's accounts the advisor can access, with market values.
- Advanced Assistant: chat page for the AI agent. Ask about all clients, or pick one client from a dropdown to
  focus the questions. The selected client is sent as context, and the backend verifies the advisor can access that
  client before every tool call. It never trusts the dropdown alone.
- Profile: username, name, email, phone, certifications, city, state. Read-only.

### Admin portal (kept small)
- Users: list advisors and clients; create a user (creates the Cognito user and the database row together).
- Accounts: list accounts; create an account.
- Permissions: grant or revoke a person's access to an account. Changes show up in the advisor and client portals
  on the next page load.
- Audit log: every permission change records who, what, and when.

## Demo
- A "Demo" page lists ready-made demo users (2 advisors, 3 clients, 1 admin) with what each one can see.
- Demo users share one demo password, stored in Secrets Manager on AWS and in `.env` locally. The owner shares it
  directly with viewers; it is never committed.
- A reset script restores the seeded data, so a demo always starts from the same state.
- The agent endpoint has a per-user rate limit and a daily request cap, to control AI cost on the public demo.
- Demo script (about 3 minutes): advisor asks the agent a question; admin grants the advisor a new account; the
  advisor sees it and the agent can answer about it; the client portal shows the same account from the client side.

## Tools (agent, week 1)
Every tool's first argument is advisor_id, filled in by the backend. The model only supplies the other arguments.
- get_my_clients(advisor_id)
- get_accounts(advisor_id, client_id)
- get_holdings(advisor_id, account_id or client_id, as_of_date)
- get_transactions(advisor_id, account_id or client_id, start_date, end_date)
- get_performance(advisor_id, account_id or client_id, as_of_date)
- find_reviews_due(advisor_id, within_days)
Tools return only the fields the answer needs, and do math (percentages, totals, gains) in SQL.

## How to work in this repo
- Build one step at a time. Current step is listed below; don't start later steps unprompted.
- Propose a plan before writing code for anything bigger than one file.
- Write tests for every tool, including:
  - an advisor cannot see accounts or clients they have no ACL row for
  - an advisor who shares one account with a client cannot see that client's other accounts
- Keep secrets in `.env` (never committed). Config comes from environment variables.
- Never store passwords in the database or in files. Login is handled by Cognito (build order step 3).
- Explain unfamiliar concepts briefly when introducing them; the owner must be able to explain every piece in an interview.

## Build order
Each step ends working, tested, committed and pushed. Do not start the next step until the owner says so.
1. Database schema, data generator, agent tools and terminal agent loop, with tests for the access rules.
2. FastAPI endpoints for the client and advisor screens, with tests. Then the Angular app with both portals, run
   with `docker compose up`. Until login exists, a local-only setting picks the demo user; it must be impossible
   to enable on AWS.
3. Cognito login with the three groups; the backend reads user ID and role from the verified token only.
   End-to-end browser tests (Playwright) log in as an advisor and a client and check what each can see.
4. Admin portal, audit log, demo page and reset script.
5. Deploy to AWS (ECR, ECS Express Mode, RDS, Secrets Manager) with infrastructure as code and GitHub Actions CI
   running the tests on every push.
6. MCP server for the tools, document search, guardrails, evals, tracing, rate limits, optional SAML federation.


## Current step
Think about the best approach to start this development. take step by step approach with minimum room for errors or bugs. Keep in mind that I should be able to see these two portals side by side in browser locally while development is happening and when I deploy these to AWS I should be able to see two portal, working backend services, AI agents should be working and i should have an easy enough way to demo it to anyone. If you think I need an admin UI to manage accounts, client users, advisor users, permissioning then bake that in to your planning. Maintain a detailed memory file for yourself so in case you need to pick up development in different sessions you should be able to do that. 
Build Local DB connection comes from DATABASE_URL in .env.
Also write `demo_users.csv` (name, email, role, person ID, and for advisors their client count) so the owner can pick
test users later. No passwords in it.
