#!/usr/bin/env sh
set -eu

echo "[entrypoint] Starting backend container..."

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[entrypoint] Running Alembic migrations..."

  retry_count=0
  max_retries="${MIGRATION_MAX_RETRIES:-10}"
  retry_seconds="${MIGRATION_RETRY_SECONDS:-3}"

  until alembic upgrade head; do
    retry_count=$((retry_count + 1))

    if [ "$retry_count" -ge "$max_retries" ]; then
      echo "[entrypoint] Alembic migration failed after ${max_retries} retries."
      exit 1
    fi

    echo "[entrypoint] Migration failed. Retrying in ${retry_seconds}s... (${retry_count}/${max_retries})"
    sleep "$retry_seconds"
  done

  echo "[entrypoint] Alembic migrations completed."
else
  echo "[entrypoint] RUN_MIGRATIONS=false. Skipping Alembic migrations."
fi

echo "[entrypoint] Executing: $*"
exec "$@"