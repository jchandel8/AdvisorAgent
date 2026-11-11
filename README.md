# AdvisorAgent

A secure, production-style AI agent for wealth advisors. Advisors ask questions in plain English and the agent
answers by calling tools over mock portfolio data. Every tool runs as the logged-in advisor and returns only the
accounts that advisor can access (per-account ACL).

See [CLAUDE.md](CLAUDE.md) for the design and [docs/PROGRESS.md](docs/PROGRESS.md) for status and decisions.

## Quick start (local)

```bash
cp .env.example .env            # then fill in DATABASE_URL and ANTHROPIC_API_KEY
docker compose up -d db
cd backend
uv sync
uv run python -m wealth.datagen # create schema, load seeded mock data, write ../demo_users.csv
uv run pytest -q
uv run wealth-agent --advisor-id 1
```

Try: *"Which of my clients are overweight in tech and have a review due this month?"*
