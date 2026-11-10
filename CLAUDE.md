# Wealth-Advisor Agent (Project 1)

## Goal
A portfolio project showing a secure, production-style AI agent. Financial advisors ask questions in plain English
("which of my clients are overweight in tech and have a review due this month?") and an agent answers by calling
tools over mock portfolio, CRM and document data.

## The one security rule
The advisor's identity comes ONLY from the verified login token (Cognito JWT), never from the prompt or the model.
Every tool receives `advisor_id` from the backend and filters every query by it. The model never queries the
database directly and never chooses whose data it sees.

## Stack
- Python 3.12, FastAPI backend
- Claude via tool use (Anthropic API locally; Amazon Bedrock later)
- Postgres: Docker locally (docker-compose.yml), RDS on AWS
- AWS Cognito for login (week 2), ECS Express Mode + RDS + Secrets Manager (week 3)
- Terraform or CDK for infrastructure, GitHub Actions for CI
- Tools exposed through an MCP server (week 3)

## Data model (mock data, generated with Faker)
- advisors: id, name, email
- clients: id, advisor_id, name, risk_profile, target_allocation, next_review_date
- holdings: id, client_id, symbol, sector, quantity, market_value
- documents: id, client_id, title, type, text

## Tools (week 1)
- get_my_clients(advisor_id)
- get_holdings(advisor_id, client_id)
- find_reviews_due(advisor_id, within_days)
Tools return only the fields the answer needs, and do math (percentages, totals) in SQL.

## How to work in this repo
- Build one step at a time. Current step is listed below; don't start later steps unprompted.
- Propose a plan before writing code for anything bigger than one file.
- Write tests for every tool, including a test that one advisor cannot see another advisor's clients.
- Keep secrets in `.env` (never committed). Config comes from environment variables.
- Explain unfamiliar concepts briefly when introducing them; the owner must be able to explain every piece in an interview.

## Current step
Week 1: data generator (into local Postgres in Docker), 3 tools, and an agent loop tested from the terminal. No web app or login yet.
Local DB connection comes from DATABASE_URL in .env.
