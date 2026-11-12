#!/bin/sh
# Container start (AWS and the production image): prepare the database, then serve.
#   1. apply migrations
#   2. load the seed data if the database is empty (first deploy, or after a reset)
#   3. with Cognito sign-in, make sure the demo logins exist (idempotent)
#   4. serve the API and the built frontend
set -e
python -m wealth.migrate
python -m wealth.datagen --if-empty
if [ "${AUTH_MODE:-cognito}" = "cognito" ] && [ -n "${DEMO_PASSWORD:-}" ]; then
  python -m wealth.ops.demo_logins --apply || echo "warning: demo logins not updated (see above); continuing"
fi
exec uvicorn wealth.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'
