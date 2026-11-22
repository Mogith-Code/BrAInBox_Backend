#!/bin/sh
# Start command of the API image (api/Dockerfile):
#   1. apply database migrations (alembic upgrade head), unless RUN_MIGRATIONS=false
#   2. start the API on $PORT (Cloud Run sets it; 8000 elsewhere)
# Two containers starting together is safe: migrations/env.py holds a PostgreSQL lock, so the
# second one waits and then finds nothing to do. If migrating fails the container stops and
# the old revision keeps serving.
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo '{"severity":"INFO","message":"Running alembic upgrade head"}'
  alembic upgrade head
fi

# --proxy-headers: trust X-Forwarded-* from the front proxy (https URLs, client IP).
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*' --no-server-header
