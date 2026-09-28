# Phase 1 Handoff Document

**Project:** Knowledge App — AI Engineering Daily Digest
**Phase:** Phase 0 (Foundation) + Phase 1 (Ingestion) — see `docs/implementation-plan.md` for the full ticket breakdown this maps to
**Last updated:** 2026-09-28
**Status:** ✅ Ingestion validated live, for real, against the currently committed code — not just a hand-run E2E script

---

## Read this first if you're picking this up cold

1. **`docs/pipeline-overview.md`** — a diagram (Mermaid, renders on GitHub) of exactly what runs today versus what's wired-but-stubbed. Read this before touching code; it'll save you from re-discovering the same gaps this handoff documents.
2. This document, in full — it covers what Phase 1 actually is (ingestion only — don't confuse it with `phase1-technical-design.md`'s bigger "Phase 1 MVP" checklist, which spans what `implementation-plan.md` splits into Phases 0–8), how it was validated, and a list of specific, real bugs found and fixed along the way that are worth knowing about even though they're closed.
3. `docs/implementation-plan.md` — the ticket-by-ticket breakdown. Phase 0 = F-01–F-06, Phase 1 = I-01–I-06. That's the authoritative phase numbering; this document follows it.

---

## What Was Built

### Phase 0 Foundation (F-01 through F-06)
- ✅ **F-01** — Repo scaffold (directory tree, `pyproject.toml`, `.env.example`)
- ✅ **F-02** — Schema migration (`sql/migrations/001_initial_schema.sql`): `bronze`, `silver`, `gold` schemas + all tables. Since this handoff was first written, one real column was added: `bronze.raw_items.inserted_at` (when the row landed in bronze, distinct from `fetched_at` — when the connector fetched it upstream). See "Bug fixes" below.
- ✅ **F-03** — Docker Compose skeleton: `postgres`, `prefect-server`, `prefect-worker`, plus an optional commented-out `llama-server` service for local LLM inference
- ✅ **F-04** — Config/secrets loader (`src/config.py`): DSN, LLM key, embedding model, and now a `create_llm_client()` factory that routes to Anthropic or a local llama-server based on `LLAMA_SERVER_URL`
- ✅ **F-05** — Embedding model validation gate (default: `sentence-transformers/all-MiniLM-L6-v2`)
- ⚠️ **F-06** — `scripts/benchmark_llama_server.py` exists and is real, but there's no recorded evidence it has actually been *run* against a live llama-server yet. A working llama-server is now available (OpenAI-compatible endpoint, tested via curl and wired into `LLMClient`/`config.py`) — running this gate before Phase 2 starts is still open.

### Phase 1 Ingestion (I-01 through I-06)
- ✅ **I-01** — `Connector` ABC (`src/connectors/base.py`): `fetch()` + `to_canonical_draft()` interface
- ✅ **I-02** — RSS pool connector: Netflix, Jay Alammar, Spotify, SeattleDataGuy, arXiv×3
- ✅ **I-03** — Reddit connector: r/MachineLearning, r/LocalLLaMA, r/mlops (RSS feeds, no PRAW)
- ✅ **I-04** — GitHub Trending connector (repo-shaped drafts, not article path)
- ✅ **I-05** — `fetch_source` Prefect task: watermark idempotency, bronze upsert
- ✅ **I-06** — Seed `gold.source_registry` with Phase 1 sources, `category='AI Engineering'`

**This is genuinely done now** — re-verified live against a freshly rebuilt Docker image and a real testcontainers Postgres, not just the design docs or a stale container. See "How Phase 1 was actually validated" below for why that distinction matters.

---

## How Phase 1 was actually validated (read this before trusting any prior "✓ E2E tested" claim)

The first version of this handoff (2026-09-27) reported an E2E pass. That pass was real, but it was validated against a **stale Docker image** — built before two subsequent commits (a code-clarity cleanup and this handoff's own first draft) ever landed. The running container's `tasks.py` had already diverged from what was actually committed to the branch. Nobody had rebuilt the image since.

The fix and the lesson: `scripts/e2e_test.sh` already does `docker compose up -d --build` (forces a rebuild every run) — the gap was purely that later manual `docker compose exec` sessions bypassed that script and ran stale state without anyone noticing, because nothing *looked* wrong. **Always run through `scripts/e2e_test.sh`, or explicitly `docker compose build` first, before trusting a container's behavior as a proxy for "the current code works."**

Once rebuilt and re-verified for real:
```
schema             ✓ all 4 tables exist
source registry    ✓ 11/11 sources seeded
ingestion          ✓ 11/11 fetch_source tasks completed
bronze data        ✓ all 11 sources have rows (783 total, live data)
watermarks         ✓ 11/11 recorded
PASS
```

---

## Bug fixes made during validation (all closed, but worth knowing about)

Validation surfaced real bugs — not doc inconsistencies, actual defects that were silently masked or untested. Fixed in two triage rounds, each following the same process: **triage → ponytail-review (catches speculative/yagni additions to the fix plan) → confirm open decisions with the person who owns the call → implement → verify live.**

### Round 1
| Bug | Root cause | Fix |
|---|---|---|
| RSS/Reddit watermark filter untested | `entry.published_parsed` (attribute access) fails silently on a plain-dict test fixture, falls back to `datetime.now()`, defeating the watermark filter in the test | Changed connectors to `entry.get("published_parsed")` — more defensive, matches the `.get()` style already used elsewhere in the same function |
| Config test asserted the wrong "unset" shape | `.env` has `TELEGRAM_BOT_TOKEN=` (empty string); pydantic-settings loads that as `''`, not `None` | Fixed the test's assertion to check falsy, not `is None` — no caller in the codebase does an `is None` check |
| Host `.venv` out of sync with `pyproject.toml` | `litellm`, `psycopg`, `testcontainers` were added as dependencies but never installed locally | Installed them directly (a broken, unrelated `dot-layered-transform>=1.0` pin in `pyproject.toml`'s dev extras blocks a full `pip install -e ".[dev]"` — still open, see "Known Gaps") |
| Prefect task-caching threw non-fatal `HashError`s | The `DB` shim classes (in `verify_pipeline.py` and test fixtures) aren't hashable/picklable; Prefect's default caching tries to hash all task inputs | Added `cache_policy=NO_CACHE` to all 4 `@task` decorators in `tasks.py` |

### Round 2 — surfaced only after Round 1 unblocked test collection
| Bug | Root cause | Fix |
|---|---|---|
| Two tests asserted a pre-formatted log substring | `tasks.py` uses lazy `%`-style logging (`logger.info("...replay=%s", is_replay)`); `mock_logger.info.call_args[0]` is the raw unformatted tuple, never a string containing `"replay=True"` | Assert against the tuple's actual contents, not `str()` of it |
| Two tests hung for ~180s each | `fetch_source` has no try/except around `connector.fetch()` or `db.execute()`; with `retries=3, retry_delay_seconds=60`, a raised exception triggers real 60-second sleeps between retries in Prefect's sync task engine (`task_engine.py:903`, real `time.sleep`) | Confirmed the intended contract is **retry, then propagate failure** (not swallow) — both `fetch_source`'s inserts are idempotent (`UNIQUE` + `ON CONFLICT DO NOTHING`), so retrying the whole task after a mid-loop failure is safe. Used `fetch_source.with_options(retry_delay_seconds=0)(...)` per-test to skip the real delay — **not** a global `time.sleep` patch, which was tried first and found to break Prefect's own ephemeral test-server startup (shares the same global `time.sleep`) |
| DB schema tests (9 tests) permanently disabled | Hardcoded `@pytest.mark.skip(reason="...run with --docker flag")` referencing a `--docker` pytest flag that was never registered anywhere | Removed the hardcoded skips; the fixture's own `try: import testcontainers / except ImportError: skip` is now the single availability gate — no flag needed |
| `db_with_schema` fixture loaded nothing | Pointed at `sql/schema.sql`, which doesn't exist — the real migration lives at `sql/migrations/001_initial_schema.sql` | Fixed the path |
| `test_raw_items_table_exists` expected the wrong PK type | Expected `id: bigint`; the real schema (and the LLD) specifies `id UUID` | Corrected the expectation |
| Testcontainers Postgres wouldn't start | Fixture hardcoded `.with_bind_ports(5432, 5432)`, colliding with another local Postgres already on 5432 (this project's own compose stack uses 5433, so it wasn't a self-collision) | Removed the fixed port binding — testcontainers assigns a free host port automatically |
| Testcontainers DSN unusable by psycopg3 | `container.get_connection_url()`'s default includes a SQLAlchemy-style `+psycopg2` driver suffix that psycopg3's `connect()` can't parse | `container.get_connection_url(driver=None)` |
| Schema re-application failed on the 2nd test | `db_with_schema` (function-scoped) re-ran the non-idempotent `CREATE TABLE` migration against the same session-scoped container on every test | Apply the schema once, inside the session-scoped `postgres_container` fixture; `db_with_schema` just opens a connection |
| `test_pipeline_watermarks_table_exists` expected a nonexistent `updated_at` column | The test predates a documented decision: `implementation-plan.md`'s F-02 row explicitly calls out dropping `pipeline_watermarks.updated_at` as a "ponytail fix" — `last_processed_at` already doubles as "last touched" since it's rewritten on every upsert | Dropped the stale expectation from the test (confirmed correct after the fact by re-reading the implementation plan) |
| `test_raw_items_upsert_deduplicates` failed on cross-test pollution, not a real bug | Query filtered only on `external_id`, not the actual unique key `(source_id, external_id)`; a different test in the same file also uses `external_id='ext-001'` with a different `source_id`, and both share one session-scoped container | Added `AND source_id = 'netflix_blog'` to the query |

**Net result:** 52 tests pass in ~14 seconds (was: 2 known failures + 2 collection errors + 9 permanently-skipped before this session started). One test remains intentionally out of scope — see "Known Gaps."

---

## What's actually next — and it's smaller than it looks

The stub functions in `src/pipeline/tasks.py` (`_simhash`, `_enrichment_prompt`, `_find_matching_story`, `_run_bertopic_and_upsert`) all raise `NotImplementedError`. **But the real implementations already exist**, written and unused, in sibling modules:

| Stub in `tasks.py` | Real implementation | Module |
|---|---|---|
| `_simhash` | `title_simhash()` | `src/pipeline/text_utils.py` |
| `_enrichment_prompt` | `build_prompt()` / `enrich()` | `src/pipeline/enrichment.py` |
| `_find_matching_story` | `find_matching_story()` | `src/pipeline/story_matching.py` |
| `_run_bertopic_and_upsert` | `run_discovery()` | `src/pipeline/topic_discovery.py` |

Wiring these four call sites — not writing new logic — is the highest-leverage next step toward Phase 2 (P-01 through P-06 in `implementation-plan.md`). See `docs/pipeline-overview.md` for the full picture of what's live vs. stub vs. absent.

---

## Code Style & Conventions

### Philosophy: "Ponytail" (Lazy, Efficient)

**Core principle:** The shortest path to done is the right path. No speculation, no premature abstractions.

#### Rules enforced in this codebase:

1. **No over-documentation**
   - Only comment WHY (why is non-obvious), never WHAT (names should say that)
   - No multi-line docstrings; one short line max

2. **No unrequested abstractions**
   - No interfaces with one implementation
   - No factories for one product
   - No helper functions "for later"
   - Add a `Protocol` only because multiple call sites need the interface explicit — see `DatabaseConnection` in `tasks.py`

3. **Minimal code**
   - One task, one job (fetch OR process OR cluster OR discover — never call each other)
   - Flows wire the sequence; tasks don't call each other
   - Stubs raise `NotImplementedError("...: see spec section X")` so they fail loud if called before implementation

4. **Types matter; Any doesn't**
   - Use `Protocol` for structural typing
   - Never `Any` on function params if avoidable

5. **Deletion > Addition**
   - Remove dead code immediately — don't keep "in case we need it later"
   - This cuts both ways: it also means don't delete a test just because its docstring *sounds* like it references dead functionality — read the actual assertion first. (`test_fetch_source_counts_inserted_and_deduped`'s docstring mentioned a "deduped" counter that really was removed as dead code, but its actual assertion never checked one — it had the same lazy-logging bug as its neighbor. Fixing beats deleting when the test is salvageable.)

6. **Correct > Clever**
   - Exception handling must be specific
   - Defaults prevent crashes (`config.get("key", "7")`, not `config["key"]`)
   - `ON CONFLICT` upserts make replays safe without app-level dedup logic

### A workflow preference worth preserving

When triaging a batch of bugs or planning a change, this project's owner wants:
1. A written **triage plan** (root cause, fix, decision points, validation) — no code touched yet.
2. That plan run through the **`ponytail-review`** skill to strip speculative/yagni additions before anyone signs off on it.
3. **Open decisions flagged explicitly and confirmed**, not assumed — even ones that look obvious (whether a schema column is real vs. a stale test expectation; whether swallowing vs. propagating an error is the right contract; whether wiping a dev volume is acceptable). Get the call, then implement.
4. Implementation only after an explicit go-ahead, verified live afterward (not just "tests pass locally" — rebuild the image, re-run against the actual stack when the change touches anything Docker/schema/pipeline).

This produced a materially better outcome twice in this session: once when a "delete the test" plan turned out to be wrong after actually reading the assertion body, and once when a "patch `time.sleep`" fix broke something unrelated (Prefect's own test-server startup) that a narrower, Prefect-native fix (`with_options(retry_delay_seconds=0)`) avoided entirely.

### Code Structure

```
src/
├── config.py           # Settings loader (pydantic-settings) + create_llm_client() factory
├── models.py            # Data shapes: RawItem, CanonicalDraft, Enrichment, etc.
├── connectors/           # Source adapters (RSS, Reddit, GitHub) — all live
│   ├── base.py           # Connector ABC
│   ├── rss.py, reddit.py, github_trending.py
│   └── __init__.py       # ConnectorRegistry (factory)
├── pipeline/             # Prefect tasks (orchestration) + the DS logic beside them
│   ├── tasks.py           # fetch_source (live), process_batch/cluster_stories/
│   │                        discover_topics (wired, but call stubs — see above)
│   ├── enrichment.py, story_matching.py, text_utils.py, topic_discovery.py
│   │                        # real logic for the 4 stubs above, not yet called
├── ml/                   # LLMClient (litellm-routed, Anthropic or local llama-server),
│   │                        EmbeddingClient
└── gold/
    └── repository.py      # GoldRepository — Protocol only, no Postgres implementation yet
```

---

## Testing & Deployment

### Quick Start

```bash
# Full stack startup + verification (always rebuilds first)
./scripts/e2e_test.sh

# Full test suite (unit + integration + real DB via testcontainers)
pytest tests/ --ignore=tests/test_e2e

# Inspect database after a run
docker compose exec postgres psql -U knowledge -c \
  "SELECT source_id, COUNT(*) FROM bronze.raw_items GROUP BY source_id;"

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
- `llama-server` — optional, commented out by default; uncomment to run local LLM inference. If running one externally (e.g. on another host), set `LLAMA_SERVER_URL` in `.env` instead.

**2. Verification Script** (`scripts/verify_pipeline.py`)

Runs inside the `prefect-worker` container (same image as production). Checks schema, source registry, ingestion per source, bronze data, watermarks. Exit code 0 = pass.

**3. Test Suite** (`pytest tests/`)

Unlike the original version of this handoff, there now **is** a real pytest suite, not just the E2E script:
- `tests/test_connectors/` — connector unit tests, mocked feeds
- `tests/test_pipeline/` — `fetch_source` integration tests, watermark semantics, idempotency
- `tests/test_db/` — schema integrity tests against a **real** testcontainers Postgres (auto-skips if Docker/testcontainers unavailable, no flag needed)
- `tests/test_config.py` — settings loader
- `tests/test_e2e/` — still `@pytest.mark.skip`-gated pending real Docker Compose E2E test infra; separate from `scripts/e2e_test.sh`, which already covers that ground manually

Run `pytest tests/ --ignore=tests/test_e2e` for the full suite (~14s, 52 passing).

### Database Details

**Bootstrap files** (postgres runs these once on first boot, in order):
- `sql/migrations/001_initial_schema.sql` — LLD §1.1: bronze/silver/gold schemas, all tables. Now includes `bronze.raw_items.inserted_at`.
- `sql/seeds/002_source_registry_phase1.sql` — LLD §1.1: 11 Phase 1 sources with category + badges

**Connection:**
- Docker network: `postgresql://knowledge:knowledge@postgres:5432/knowledge`
- Host access: `postgresql://knowledge:knowledge@localhost:5433/knowledge` (5433, not 5432 — avoids clashing with any other local Postgres; this exact clash is what broke the testcontainers fixture until it was fixed to stop hardcoding a fixed port)

---

## Your Requirements & Preferences

### Code Clarity for Junior Devs
- Type hints on all function parameters (use Protocol for structural types)
- Error messages that name the exact problem (`NotImplementedError` mentions spec section)
- NO `except Exception` or `except Any` — catch only what you expect
- Config has defaults; code doesn't crash on missing keys

### Validation Discipline (new — learned this session)
- **A green E2E run only proves the code that was actually running, not the code currently committed.** Always confirm the Docker image was rebuilt from the current commit before trusting its output.
- **Fix root causes over patching test assertions to match broken behavior** — but check which side is actually wrong first (schema vs. test, connector vs. fixture) rather than assuming the test is the stale one.
- **A test hang is a symptom, not just an inconvenience** — the two ~180s hangs in this codebase both pointed at a real, undocumented contract question (should this task swallow or propagate an error?) that needed an explicit answer, not just a faster mock.
- **Global patches (`patch("time.sleep")`) can have invisible blast radius** in a system with its own internal timing (Prefect's ephemeral test server, in this case) — prefer the framework's own narrow override mechanism (`task.with_options(...)`) when one exists.

### Deployment Compatibility
- Docker Compose is the deploy vehicle (same image for worker = real smoke test) — **and must be rebuilt, not just restarted, whenever `src/` changes**
- Schema + seed are mounted as `docker-entrypoint-initdb.d/` files (Postgres native bootstrap)
- No migration scripts to run by hand; automatic on first boot — but `CREATE TABLE` isn't idempotent, so a schema change (like the `inserted_at` addition) currently requires `docker compose down -v` to apply to an existing volume. Confirmed acceptable for this dev environment; revisit before this matters in a shared/staging environment.
- E2E script has same output format each run; easy to log and parse

### Git Discipline
- One commit per logical unit (not per file)
- Commit messages explain WHY, not WHAT (code says WHAT)
- Branch: `phase1_foundation`; merge to `master` when ready
- **Nothing from this session is committed yet** — see "Files Changed & Created" below for the full list. `docs/tools_research.md` also shows as deleted in the working tree; that wasn't done by any of the work described in this document — confirm its origin before committing.

### Testing Approach
- Real pytest suite now exists (connectors, pipeline tasks, watermark semantics, DB schema against a real Postgres via testcontainers) — this supersedes the original handoff's "E2E script is the test, not a separate pytest suite" note, which is no longer accurate
- `tests/test_db/` needs Docker running; skips automatically otherwise, no flag required
- Pass/fail is clear: pytest's own reporting, no custom ✓/✗ wrapper needed beyond `scripts/verify_pipeline.py`'s own output for the manual E2E path

---

## Known Gaps (Deliberate or Otherwise)

### Deliberately not in Phase 1
- **No Phase 2 (Processing)** — enrichment, deduplication, embeddings, silver layer population. The four stub call sites in `tasks.py` need wiring to their already-written implementations (see "What's actually next" above) — this is the real starting point for P-01 through P-06.
- **No Prefect Deployments** — `flows/flows.py` defines `ingest_flow`/`digest_flow`/`topic_discovery_weekly`/`topic_discovery_quarterly` with a `SCHEDULES` dict, but nothing has been deployed to `prefect-worker`. That's **S-05** in the implementation plan, part of Phase 5.
- **`GoldRepository` has no Postgres implementation** — it's a `Protocol` only. That's **S-01**.
- **`src/bot/` and `src/dashboard/` don't exist** — S-03/S-04.

### Not deliberate — genuinely open
- **`pyproject.toml`'s dev extras won't fully install**: `dot-layered-transform>=1.0` doesn't exist on PyPI at that version (max published is `0.0.8a0`). Blocks `pip install -e ".[dev]"` end to end; worked around this session by installing the specific packages actually needed (`litellm`, `psycopg[binary]`, `testcontainers`) directly. Fix the pin or drop the dependency before the next person hits this.
- **F-06 (llama-server throughput gate) hasn't been run** against the now-available local llama-server. `scripts/benchmark_llama_server.py` is ready; just needs `LLAMA_SERVER_URL` set and a run before trusting local inference for the hourly fast path.
- **`test_fetch_source_handles_db_errors_gracefully`-adjacent territory is otherwise closed**, but note the pattern: any *new* task added to `tasks.py` that doesn't wrap a call in try/except will hang for real minutes in its test if that call can raise and the task has `retries>0` — use `.with_options(retry_delay_seconds=0)` in tests from the start, don't wait to discover the hang.
- **CI/CD**: `scripts/e2e_test.sh` and the pytest suite are both CI-ready (clean exit codes) but not wired to GitHub Actions or similar yet.
- **Uncommitted `docs/tools_research.md` deletion** — showed up in `git status` during this session's work but wasn't caused by anything described here. Confirm intent before it gets swept into a commit.

---

## What's Next (Phase 2+, per `docs/implementation-plan.md`)

### Phase 2 — Processing (P-01 through P-06)
- Wire the four stub call sites to their existing implementations (the real work here is smaller than "implement enrichment/clustering from scratch" — it's mostly done, just disconnected)
- `LLMClient` (P-01) and `EmbeddingClient` (P-02) already exist in `src/ml/` — `LLMClient` now also supports routing to a local llama-server via `api_base`
- `process_batch` task (P-06): extract → dedup → enrich → embed → silver upsert

### Phase 3 — Clustering (C-01 through C-03)
- `story_matching.py` has the matching rule and centroid update already written; `cluster_stories` just needs to call it

### Phase 4 — dbt Marts (M-01 through M-05)
- No `dbt/` directory exists yet

### Phase 5 — Serving (S-01 through S-06)
- `GoldRepository` Postgres implementation, Prefect deployments (S-05), bot + dashboard

### Phase 6+ — Topic Discovery, Hardening, Launch
- `topic_discovery.py` (BERTopic) is written; `bertopic`/`umap-learn`/`hdbscan` aren't in `pyproject.toml` yet — needed before T-01 can run

---

## Files Changed & Created (this session, on top of the original handoff)

### New
```
docs/pipeline-overview.md     (Mermaid diagram + file-by-file status table)
```

### Modified (all uncommitted as of this writing)
```
.env.example                            (documented both LLM provider paths; llama-server URL example)
docker-compose.yml                      (optional llama-server service, updated comments)
sql/migrations/001_initial_schema.sql   (added bronze.raw_items.inserted_at)
src/config.py                           (create_llm_client() factory)
src/connectors/reddit.py                (entry.get("published_parsed") — defensive fix)
src/connectors/rss.py                   (same)
src/ml/llm_client.py                    (api_base support for local llama-server)
src/pipeline/tasks.py                   (cache_policy=NO_CACHE on all 4 tasks)
tests/test_config.py                    (assertion fix — falsy, not is None)
tests/test_db/conftest.py               (schema path fix, port-binding fix, DSN driver fix,
                                          schema-applied-once fix)
tests/test_db/test_schema.py            (removed hardcoded skips, id type fix, updated_at
                                          removed, dedup query fix)
tests/test_pipeline/test_tasks.py       (connector-fetch-error test: with_options + pytest.raises)
tests/test_pipeline/test_watermarks.py  (2 lazy-logging assertion fixes, db-error test:
                                          with_options + pytest.raises)
```

### Deleted (uncommitted, unclear origin — see "Known Gaps")
```
docs/tools_research.md
```

---

## Quick Reference: Key Decisions

| Decision | Rationale | Where |
|----------|-----------|-------|
| PostgreSQL `ON CONFLICT (source_id, external_id) DO NOTHING` for bronze upserts | Makes replays safe; no dedup logic in code | `tasks.py:fetch_source` |
| One `Connector` per source type (RSS, Reddit, GitHub) not per source | Reduces code; source is config (`FEEDS` dict), not inheritance | `connectors/{rss,reddit,github_trending}.py` |
| Watermark pattern: `since=None` reads watermark, explicit `since` is replay | Lets scheduled runs take zero args; manual replays don't corrupt automation | `tasks.py`: all tasks |
| Docker Compose mounts SQL files to `/docker-entrypoint-initdb.d/` | Postgres bootstraps itself; no hand-run migrations | `docker-compose.yml` |
| No mocking in `scripts/verify_pipeline.py` | Real connectors, real Postgres, real Prefect engine = confidence it works end-to-end | `scripts/verify_pipeline.py` |
| `LLMClient` routes to Anthropic or local llama-server via one `api_base` param | Provider is a config value (`LLAMA_SERVER_URL`), not a code path — matches tech design §2.4 | `src/ml/llm_client.py`, `src/config.py` |
| Task-level retry-then-fail, not swallow-and-continue, for `connector.fetch()`/`db.execute()` errors | Inserts are idempotent, so retrying the whole task after a failure is safe; a raw exception escaping a connector is unexpected (connectors already handle known failure modes internally) and should surface, not be silently absorbed | `tasks.py:fetch_source` + its tests |
| DB schema tests gate on availability (try/except), not a manual `--docker` flag | One skip mechanism instead of two; runs automatically whenever Docker + testcontainers are present | `tests/test_db/conftest.py` |
| `bronze.raw_items.inserted_at` added; `gold.pipeline_watermarks.updated_at` confirmed intentionally absent | The first is a real gap (persist time vs. fetch time are genuinely different); the second was already a documented "ponytail fix" in `implementation-plan.md`'s F-02 row — `last_processed_at` already serves that purpose | `sql/migrations/001_initial_schema.sql`, `implementation-plan.md` F-02 |

---

## How to Pass This to a Junior

1. **Read** `docs/pipeline-overview.md` first (5 min) — the diagram will orient you faster than prose.
2. **Read** this document in full (10 min), especially "How Phase 1 was actually validated" and "Bug fixes made during validation" — several of those bugs are the kind that silently comes back if you don't know the pattern.
3. **Skim** `docs/implementation-plan.md` to see how Phase 0/1 map to the bigger ticket sequence (5 min).
4. **Read** `docs/low-level-design.md` §1.1–1.4 for schema + task contracts (10 min).
5. **Open** `src/pipeline/tasks.py` and trace `fetch_source` start to finish — then look at `process_batch`/`cluster_stories`/`discover_topics` and their matching orphaned-implementation modules.
6. **Run** `./scripts/e2e_test.sh` and `pytest tests/ --ignore=tests/test_e2e`, and watch both pass.
7. **Ask:** "What do I implement next?" — Answer: wire the four stub call sites in `tasks.py` to their existing implementations (`text_utils.py`, `enrichment.py`, `story_matching.py`, `topic_discovery.py`). That's P-01 through P-06's real starting point, and it's mostly plumbing, not new design.

---

**End of Handoff**
