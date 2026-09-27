#!/usr/bin/env bash
# Applies seed data in order — idempotent (uses ON CONFLICT DO NOTHING)
set -euo pipefail
: "${POSTGRES_DSN:?POSTGRES_DSN must be set}"

for file in sql/seeds/*.sql; do
    echo "Seeding with $file..."
    psql "$POSTGRES_DSN" -f "$file"
done

echo "All seeds applied."
