#!/bin/bash
# Starts the stack and smoke-tests ingestion. Same script for local test runs
# and deploy verification — it doesn't tear anything down, so on a server
# this just leaves the verified stack running.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose up -d --build

echo "waiting for postgres..."
until docker compose exec -T postgres pg_isready -U knowledge >/dev/null 2>&1; do sleep 2; done

echo "waiting for prefect-server..."
until docker compose exec -T prefect-server python -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:4200/api/health')" \
  >/dev/null 2>&1; do sleep 2; done

echo "running pipeline verification..."
docker compose exec -T prefect-worker python -m scripts.verify_pipeline
