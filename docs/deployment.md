# Deployment & Verification

How to stand up the Phase 1 stack and confirm ingestion actually works — locally or on a server. One script does both jobs; there's no separate "test" vs "deploy" path.

## Scripts

| File | Role |
|---|---|
| `docker-compose.yml` | Defines the stack (`postgres`, `prefect-server`, `prefect-worker`) and bootstraps the database on first boot. |
| `scripts/e2e_test.sh` | Orchestrator. Starts the stack, waits for it to be healthy, triggers verification. Safe to run repeatedly; never tears the stack down. |
| `scripts/verify_pipeline.py` | Does the actual checking. Runs *inside* the `prefect-worker` container and exercises the real ingestion code. |

## What happens, step by step

### 1. Database bootstrap (automatic, first boot only)

`docker-compose.yml` mounts two files into postgres's `/docker-entrypoint-initdb.d/`:

- `sql/migrations/001_initial_schema.sql` → creates `bronze`, `silver`, `gold` schemas and all tables
- `sql/seeds/002_source_registry_phase1.sql` → seeds the 11 Phase 1 sources into `gold.source_registry`

Postgres runs every `*.sql` file in that directory, in filename order, **once** — only when its data directory (the `pgdata` volume) is empty. On a fresh volume this is how the schema and seed data get applied; there's no separate migration step to run by hand. On a volume that already has data, these files are silently skipped (matches normal Postgres behavior — this isn't a migration runner).

If you need to re-apply from scratch: `docker compose down -v` wipes the volume, so the next `up` re-bootstraps.

### 2. `scripts/e2e_test.sh` — start + wait + verify

```bash
./scripts/e2e_test.sh
```

1. `docker compose up -d --build` — starts all three services (rebuilding the worker image if `Dockerfile`/`pyproject.toml` changed).
2. Waits for `postgres` to report ready — polls `pg_isready` inside the postgres container (the same command `docker-compose.yml`'s own healthcheck uses).
3. Waits for `prefect-server` to report healthy — polls its `/api/health` endpoint (again, the same check already defined in `docker-compose.yml`).
4. Runs `docker compose exec -T prefect-worker python scripts/verify_pipeline.py` — hands off to the verification script, **inside** the worker container, so it's exercising the exact image that runs ingestion in production.

The script does not stop or remove containers afterward. On a laptop that just means `docker compose down` is on you when you're done; on a server it means the verified stack is what's left running — that's the point.

### 3. `scripts/verify_pipeline.py` — what gets checked

Runs inside `prefect-worker`, so it has the app's code and its network path to `postgres` for free. Five checks, in order, each printed with ✓/✗:

1. **Schema** — `bronze.raw_items`, `silver.items`, `gold.source_registry`, `gold.pipeline_watermarks` exist in `information_schema.tables`.
2. **Source registry** — row count in `gold.source_registry` is at least the 11 expected Phase 1 sources.
3. **Ingestion** — for each of the 11 sources, calls `fetch_source(db, source_id)` — the actual Prefect task, run through Prefect's task engine exactly as it would be in production. This is the real connector `.fetch()` call followed by the real upsert into `bronze.raw_items`, watermark included.
4. **Bronze data** — queries `bronze.raw_items` grouped by `source_id` and prints row counts; fails if the table is empty after step 3.
5. **Watermarks** — queries `gold.pipeline_watermarks`; fails if empty (each successful `fetch_source` call in step 3 should have written one row per source).

Exit code is `0` only if every check passed; any single ✗ makes it `1`. `e2e_test.sh` propagates that exit code, so CI (or you) can gate on it.

The `DB` class in this script is a small shim (`fetch_one`/`fetch_all`/`execute` over a psycopg connection) — it exists only because `fetch_source` expects an object of that shape and Phase 1 hasn't built the real Postgres repository yet (that's ticket S-01, Phase 5). It's deliberately minimal and marked as such in the file — don't extend it; build S-01 instead if more callers need a real db object.

## Running it

```bash
# Full run: start stack, wait, verify
./scripts/e2e_test.sh

# Inspect after a run
docker compose logs -f prefect-worker
docker compose exec postgres psql -U knowledge -c "select source_id, count(*) from bronze.raw_items group by 1;"

# Re-run verification only, without restarting anything
docker compose exec -T prefect-worker python -m scripts.verify_pipeline

# Full reset (wipes the database volume, next `up` re-bootstraps schema+seed)
docker compose down -v
```

## Known gaps (by design, not oversight)

- No idempotent re-migration path — schema changes on an existing volume need `down -v`, not a rerun of the SQL.
- No teardown flag on `e2e_test.sh` — add `docker compose down` yourself if you want a throwaway run.
- Not wired into CI yet — `e2e_test.sh`'s exit code is CI-ready; add a workflow step calling it when that's needed.
