# AdvisorAgent

A secure, production-style AI agent for wealth advisors. Advisors ask questions in plain English and the agent
answers by calling tools over mock portfolio data. Every tool runs as the logged-in advisor and returns only the
accounts that advisor can access (per-account ACL).

See [CLAUDE.md](CLAUDE.md) for the design and [docs/PROGRESS.md](docs/PROGRESS.md) for status and decisions.

## Quick start (local)

```bash
cp .env.example .env            # then fill in ANTHROPIC_API_KEY
docker compose up               # Postgres, API (seeds mock data on first run) and the web app
```

Open http://localhost:4200, pick a demo advisor in a normal window and a demo client in a private window,
and compare what each can see. In the advisor portal, open **Assistant** and try:
*"Which of my clients are overweight in tech and have a review due this month?"*

Backend tests: `cd backend && uv run pytest -q`. Frontend tests: `docker compose exec web npx ng test --watch=false`.
