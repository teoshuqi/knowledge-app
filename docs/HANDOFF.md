# Phase 1 Handoff Document

**Project:** Knowledge App — AI Engineering Daily Digest  
**Phase:** Phase 1 (Foundation + Ingestion)  
**Completed:** 2026-09-27  
**Status:** ✅ E2E tested and verified

---

## What Was Built

Phase 1 establishes the **ingestion pipeline**: fetching content from 11 sources, inserting raw items into the bronze layer, and preparing the schema + config for Phase 2 processing.

### Phase 0 Foundation (F-01 through F-06)
- ✅ **F-01** — Repo scaffold (directory tree, `pyproject.toml`, `.env.example`)
- ✅ **F-02** — Schema migration (`sql/migrations/001_initial_schema.sql`): `bronze`, `silver`, `gold` schemas + all tables
- ✅ **F-03** — Docker Compose skeleton: postgres, prefect-server, prefect-worker
- ✅ **F-04** — Config/secrets loader (`src/config.py`): DSN, LLM key, embedding model
- ✅ **F-05** — Embedding model validation gate (default: `sentence-transformers/all-MiniLM-L6-v2`)
- ✅ **F-06** — CPU llama-server throughput benchmark (decided: local llama-server for hourly fast path)

### Phase 1 Ingestion (I-01 through I-06)
- ✅ **I-01** — `Connector` ABC (`src/connectors/base.py`): `fetch()` + `to_canonical_draft()` interface
- ✅ **I-02** — RSS pool connector: Netflix, Jay Alammar, Spotify, SeattleDataGuy, arXiv×3
- ✅ **I-03** — Reddit connector: r/MachineLearning, r/LocalLLaMA, r/mlops (RSS feeds, no PRAW)
- ✅ **I-04** — GitHub Trending connector (repo-shaped drafts, not article path)
- ✅ **I-05** — `fetch_source` Prefect task: watermark idempotency, bronze upsert
- ✅ **I-06** — Seed `gold.source_registry` with Phase 1 sources, `category='AI Engineering'`

**E2E Test Results** (2026-09-27 08:13):
```
Schema:           ✓ 4/4 tables verified
Source Registry:  ✓ 11/11 sources seeded
Ingestion:        ✓ 11/11 fetch_source tasks completed
Bronze Data:      ✓ 71 rows inserted across 6 live sources
Watermarks:       ✓ 11/11 watermark rows recorded
```

---

## Code Style & Conventions

### Philosophy: "Ponytail" (Lazy, Efficient)

**Core principle:** The shortest path to done is the right path. No speculation, no premature abstractions.

#### Rules enforced in this codebase:

1. **No over-documentation**
   - Only comment WHERE (why is non-obvious), never WHAT (names should say that)
   - No multi-line docstrings; one short line max
   - Example: ✅ Good:
     ```python
     def _to_canonical_draft(raw):
         # Reconstruct a RawItem from the DB row, then delegate to the
         # connector's extraction method (per-source via registry).
     ```
   - Example: ❌ Bad:
     ```python
     def _to_canonical_draft(raw):
         """This function takes a raw item from the database and converts it
         to a canonical draft by extracting the source_id, source_type, etc.,
         then looking up the connector in the registry and calling its 
         to_canonical_draft method..."""
     ```

2. **No unrequested abstractions**
   - No interfaces with one implementation
   - No factories for one product
   - No helper functions "for later"
   - Add `DatabaseConnection` Protocol only because multiple tasks use db; makes interface explicit for juniors

3. **Minimal code**
   - One task, one job (fetch OR process OR cluster OR discover — never call each other)
   - Flows wire the sequence (src/pipeline/tasks.py imports only, no interdependencies)
   - Stubs raise `NotImplementedError("...: see spec section X")` so they fail loud if called before implementation

4. **Types matter; Any doesn't**
   - Use `Protocol` for structural typing (what methods must db have?)
   - Never `Any` on function params if you can avoid it
   - Example: `db: DatabaseConnection` tells juniors what interface to implement

5. **Deletion > Addition**
   - Remove dead code immediately (the `deduped` counter that never incremented)
   - Don't keep "in case we need it later"

6. **Correct > Clever**
   - Exception handling must be specific (not `except OSError` for DB operations)
   - Defaults prevent crashes (config.get("key", "7") instead of config["key"])
   - ON CONFLICT (upsert) makes replays safe without code trying to catch duplicates

### Code Structure

**Layers** (see [tech design](phase1-technical-design.md) §1-2):

```
src/
├── config.py           # Settings loader (pydantic-settings)
├── models.py           # Data shapes: RawItem, CanonicalDraft, Enrichment, etc.
├── connectors/         # Source adapters (RSS, Reddit, GitHub)
│   ├── base.py         # Connector ABC
│   ├── rss.py, reddit.py, github_trending.py
│   └── __init__.py     # ConnectorRegistry (factory)
├── pipeline/           # Prefect tasks (orchestration only, not logic)
│   ├── tasks.py        # fetch_source, process_batch, cluster_stories, discover_topics
│   ├── enrichment.py   # LLM prompting (Phase 2)
│   ├── story_matching.py
│   ├── text_utils.py
│   └── topic_discovery.py
├── ml/                 # LLM + embedding clients (Phase 2+)
└── gold/               # Query layer (S-01, Phase 5)
```

**Task Pattern**:
```python
@task(retries=N, retry_delay_seconds=X)
def my_task(db: DatabaseConnection, ..., since: datetime | None = None) -> None:
    """Docstring."""
    is_replay = since is not None
    watermark = since or _get_watermark(db, "task_name")
    
    # Do work, reading from watermark
    
    if not is_replay:
        _advance_watermark(db, "task_name", datetime.now(UTC))
```

Every task follows this: **since parameter is None on scheduled runs (read watermark), explicit on manual replays (don't update watermark).**

---

## Testing & Deployment

### Quick Start

```bash
# Full stack startup + verification
./scripts/e2e_test.sh

# Inspect database after a run
docker compose exec postgres psql -U knowledge -c \
  "SELECT source_id, COUNT(*) FROM bronze.raw_items GROUP BY source_id;"

# Re-run verification only (without restarting)
docker compose exec -T prefect-worker python -m scripts.verify_pipeline

# Stop everything (keeps database)
docker compose stop

# Full reset (wipes database, next start re-bootstraps)
docker compose down -v
```

### How It Works

**1. Docker Compose Startup** (`docker-compose.yml`)
- `postgres:16` with auto-bootstrap:
  - Runs `sql/migrations/001_initial_schema.sql` on first boot → creates all schemas + tables
  - Runs `sql/seeds/002_source_registry_phase1.sql` on first boot → seeds 11 sources
- `prefect-server:3-latest` — API + dashboard (http://localhost:4200)
- `prefect-worker` (built from `Dockerfile`) — runs Prefect tasks

**2. Verification Script** (`scripts/verify_pipeline.py`)

Runs inside the `prefect-worker` container (same image as production).

**Checks** (in order):
```
✓ Schema        — bronze.raw_items, silver.items, gold.source_registry, gold.pipeline_watermarks exist
✓ Registry      — all 11 Phase 1 sources in gold.source_registry
✓ Ingestion     — fetch_source(db, source_id) for each source via real Prefect task engine
✓ Bronze data   — rows inserted into bronze.raw_items per source
✓ Watermarks    — fetch:<source_id> rows recorded in gold.pipeline_watermarks
```

Each source's fetch may return 0 items (normal if no new content in watermark window, or rate-limited by external API). Success = task completes without error and watermark is written.

**3. Orchestrator Script** (`scripts/e2e_test.sh`)

Simple bash wrapper:
- Starts Docker Compose
- Waits for postgres and prefect-server to report healthy (reuses their existing `docker-compose.yml` healthchecks)
- Runs verification script inside worker

Exit code: 0 = all checks passed, 1 = any check failed.

### Database Details

**Bootstrap files** (postgres runs these once on first boot, in order):
- `sql/migrations/001_initial_schema.sql` — LLD §1.1: creates bronze/silver/gold schemas, all tables with constraints
- `sql/seeds/002_source_registry_phase1.sql` — LLD §1.1: inserts 11 Phase 1 sources with category + badges

**Connection in docker-compose.yml**:
- postgres service: `postgresql://knowledge:knowledge@postgres:5432/knowledge` (internal docker network)
- Host access: `postgresql://knowledge:knowledge@localhost:5433/knowledge` (mapped to 5433 to avoid conflicts)

**To inspect manually**:
```bash
docker compose exec postgres psql -U knowledge knowledge

# Or from host:
psql postgresql://knowledge:knowledge@localhost:5433/knowledge

# Common queries:
SELECT * FROM gold.source_registry;
SELECT source_id, COUNT(*) FROM bronze.raw_items GROUP BY source_id;
SELECT task_name, last_processed_at FROM gold.pipeline_watermarks;
```

---

## Your Requirements & Preferences

Based on the phase1 work, here's what was learned:

### Code Clarity for Junior Devs
- Type hints on all function parameters (use Protocol for structural types)
- Error messages that name the exact problem (NotImplementedError mentions spec section)
- NO `except Exception` or `except Any` — catch only what you expect
- Config has defaults; code doesn't crash on missing keys

### Deployment Compatibility
- Docker Compose is the deploy vehicle (same image for worker = real smoke test)
- Schema + seed are mounted as `docker-entrypoint-initdb.d/` files (Postgres native bootstrap)
- No migration scripts to run by hand; automatic on first boot
- E2E script has same output format each run; easy to log and parse

### Git Discipline
- One commit per logical unit (not per file)
- Commit messages explain WHY, not WHAT (code says WHAT)
- Attribution line: `Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>`
- Branch: `phase1_foundation`; merge to `master` when ready

### Testing Approach
- No mocking or fixtures (test real connectors, real Postgres, real Prefect)
- E2E script is the test (not separate pytest suite; verification happens in production container)
- Pass/fail is clear: ✓ or ✗, no partial passes

---

## Known Gaps (Deliberate)

### Not in Phase 1

- **No Phase 2 (Processing)** — enrichment, deduplication, embeddings, silver layer population
  - Stubs exist (`_to_canonical_draft` now implemented, but `_simhash`, `_enrichment_prompt` still raise NotImplementedError)
  - Won't run until P-01 through P-06 are done

- **No Prefect Deployments** — flows are defined in `flows/flows.py` with `SCHEDULES` dict, but never deployed to the worker
  - Deployment happens in **Phase 5 (S-05)**: wire schedules live and add to prefect-server
  - For now: `fetch_source` can only be called manually or via E2E script

- **No idempotent schema migrations** — F-02 uses `CREATE TABLE` (not `CREATE IF NOT EXISTS`)
  - Changing schema on an existing volume requires `docker compose down -v` (full reset)
  - Add conditional creates if you need to layer schema changes on top of existing data

- **No CI/CD yet** — E2E script is CLI-ready but not wired to GitHub Actions or similar
  - Script returns exit codes (0 = pass, 1 = fail); ready for `if ./scripts/e2e_test.sh then ...`

---

## What's Next (Phase 2+)

### Phase 2 — Processing (P-01 through P-06)
- Implement `_simhash()`, `_enrichment_prompt()`, `_to_canonical_draft()` fully
- Build `LLMClient` (P-01) and `EmbeddingClient` (P-02)
- Implement `process_batch` task (P-06): extract → dedup → enrich → embed → silver upsert

### Phase 3 — Clustering (C-01 through C-03)
- Implement story matching and running centroids
- `cluster_stories` task becomes real

### Phase 4 — dbt Marts (M-01 through M-05)
- Build dbt project with fact/dimension tables
- Tests can be written now but validated only after Phase 1-3 produce rows

### Phase 5 — Serving (S-01 through S-06)
- Implement `GoldRepository` (Postgres query layer)
- Wire Prefect deployments (S-05): flows go live with real schedules
- Build bot + dashboard

### Phase 6+ — Topic Discovery, Hardening, Launch

---

## Files Changed & Created

### New Files
```
docker-compose.yml          (updated: postgres bootstrap mounts)
.env                        (created from .env.example)
scripts/e2e_test.sh         (E2E orchestrator, 3-stage: docker → wait → verify)
scripts/verify_pipeline.py  (verification script, runs in worker container)
docs/deployment.md          (deployment architecture + procedures)
docs/HANDOFF.md             (this file)
sql/migrations/001_initial_schema.sql  (Phase 0 F-02, already existed)
sql/seeds/002_source_registry_phase1.sql (Phase 1 I-06, already existed)
```

### Modified Files
```
pyproject.toml              (added psycopg[binary], litellm dependencies)
src/pipeline/tasks.py       (code clarity: removed dead code, implemented stubs, added Protocol)
src/connectors/base.py      (no changes, working as designed)
src/connectors/rss.py       (no changes, working as designed)
src/connectors/reddit.py    (no changes, working as designed)
src/connectors/github_trending.py (no changes, working as designed)
```

---

## Quick Reference: Key Decisions

| Decision | Rationale | Where |
|----------|-----------|-------|
| PostgreSQL `ON CONFLICT (source_id, external_id) DO NOTHING` for bronze upserts | Makes replays safe; no dedup logic in code | tasks.py:fetch_source |
| One `Connector` per source type (RSS, Reddit, GitHub) not per source | Reduces code; source is config (FEEDS dict), not inheritance | connectors/{rss,reddit,github_trending}.py |
| Watermark pattern: `since=None` reads watermark, explicit `since` is replay | Lets scheduled runs take zero args; manual replays don't corrupt automation | tasks.py:all tasks |
| Docker Compose mounts SQL files to `/docker-entrypoint-initdb.d/` | Postgres bootstraps itself; no hand-run migrations | docker-compose.yml |
| E2E script runs inside `prefect-worker` container | Tests real production image; no parallel harness drift | scripts/e2e_test.sh |
| No mocking in tests | Real connectors, real Postgres, real Prefect engine = confidence it works end-to-end | scripts/verify_pipeline.py |

---

## How to Pass This to a Junior

1. **Read** this document (5 min)
2. **Skim** Phase 1 implementation plan (docs/implementation-plan.md) to see what tiles fit where (5 min)
3. **Read** low-level design (docs/low-level-design.md) sections 1.1-1.4 for schema + task contracts (10 min)
4. **Open** `src/pipeline/tasks.py` and trace one task start-to-finish (10 min)
5. **Run** `./scripts/e2e_test.sh` and watch it work (2 min)
6. **Ask:** "What do I implement next?" (Answer: Phase 2, starting with P-01 `LLMClient`)

They're ready. The code is clear, the flow is linear, the tests are real.

---

**End of Handoff**
