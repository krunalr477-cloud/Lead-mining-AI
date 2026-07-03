#!/usr/bin/env bash
# LeadMine backend container entrypoint.
#
# Runs Alembic migrations exactly once at boot — only in the container that
# sets RUN_MIGRATIONS=1 (the `api` service). The worker and beat services leave
# it unset so they never race the api on `alembic upgrade head`. After
# migrating (or skipping), we exec the passed CMD so signals reach PID 1 for
# clean shutdown.
set -euo pipefail

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[entrypoint] Running database migrations (alembic upgrade head)…"
  alembic upgrade head
  echo "[entrypoint] Migrations complete."
else
  echo "[entrypoint] RUN_MIGRATIONS not set — skipping migrations."
fi

exec "$@"
