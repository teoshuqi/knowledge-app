#!/usr/bin/env bash
# Applies pending SQL migrations in order — plain numbered SQL, no ORM/Alembic
# (LLD §0). Idempotent because every statement inside each file is a one-time
# CREATE; re-running against an already-migrated database is expected to fail
# loudly rather than silently, since there's nothing here designed to be re-run.
set -euo pipefail
: "${POSTGRES_DSN:?POSTGRES_DSN must be set}"

for file in sql/migrations/*.sql; do
    echo "Applying $file..."
    psql "$POSTGRES_DSN" -f "$file"
done
