#!/bin/sh
# Apply database migrations, then start the app.
#
# Set RUN_MIGRATIONS=false on every replica but one so a single process migrates. Concurrent
# runs are also serialized by a Postgres advisory lock in app/db/migrations/env.py, so a race
# degrades to a wait rather than a corrupted schema.
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
  echo "[entrypoint] migrations applied"
fi

exec "$@"
