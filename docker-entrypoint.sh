#!/usr/bin/env sh
# Apply DB migrations (idempotent) then start the server.
# Set RUN_MIGRATIONS=false to skip migrations on boot (e.g. if you run them
# as a separate one-off Cloud Run Job).
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[entrypoint] Running database migrations…"
  alembic upgrade head
fi

echo "[entrypoint] Starting server on port ${PORT:-8080}…"
exec python main.py
