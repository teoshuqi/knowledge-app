# Phase 1 — Implementation Plan & Tickets

**Purpose:** turns `requirements-and-product-brief.md`, `phase1-technical-design.md`, and `low-level-design.md` into a dependency-ordered sequence of tickets. Order follows what actually blocks what — schema before pipeline, pipeline before serving — not the order things were designed in.
**Ticket format:** `ID | Track | Ticket | Depends on | Size | Spec`. Size is a rough relative signal (S/M/L), not an estimate in hours. Spec points at the exact section to implement against — nothing here re-derives content already fixed elsewhere.

---

## Phase 0 — Foundation

Nothing downstream can be built or tested without this existing first.

| ID | Track | Ticket | Depends on | Size | Spec |
|---|---|---|---|---|---|
| F-01 | DE | Repo scaffold: directory tree, `pyproject.toml`, `.env.example` | — | S | LLD §0 |
| F-02 | DE | Apply schema migration (`sql/migrations/001_initial_schema.sql`) | F-01 | M | LLD §1.1, with the two ponytail fixes: drop `action` from `user_topic_overrides`' PK, drop `pipeline_watermarks.updated_at` |
| F-03 | DE | Docker Compose skeleton: `postgres`, `prefect-server`, `prefect-worker` stubs, health checks | F-01 | S | Tech design §2.7 |
| F-04 | SWE | Config/secrets loader (`pydantic-settings`): Postgres DSN, Telegram token, LLM key/URL, llama-server URL | F-01 | S | LLD §2.1 |
| F-05 | DS | **Gate**: embedding model domain-validation test (20-30 hand-picked pairs) — decides fastembed's default model | — | S | Tech design §10.2 |
| F-06 | DS | **Gate**: CPU `llama-server` throughput benchmark against the per-item SLA — decides local vs. API for the hourly fast path | — | M | Tech design §2.4 consideration |

F-05/F-06 are go/no-go gates, not just tickets — their outcomes are config values Phase 2 tickets read, not something to guess ahead of them.

---

## Phase 1 — Ingestion

| ID | Track | Ticket | Depends on | Size | Spec |
|---|---|---|---|---|---|
| I-01 | DE | `Connector` ABC (`src/connectors/base.py`) | F-01 | S | LLD §1.3 |
| I-02 | DE | RSS pool connector (Netflix, Jay Alammar, Spotify, SeattleDataGuy, arXiv×3) | I-01 | M | Tech design §3.1 table |
| I-03 | DE | Reddit connector (feedparser + User-Agent header, no PRAW) | I-01 | S | Tech design §3.1 |
| I-04 | DE | GitHub Trending connector (repo-shaped draft, not article path) | I-01 | M | Tech design §3.1 |
| I-05 | DE | `fetch_source` Prefect task — watermark default, idempotent bronze upsert | I-01, F-02 | S | LLD §1.4 |
| I-06 | DE | Seed `gold.source_registry` — all Phase 1 sources, `category='AI Engineering'`, badges | F-02 | S | LLD §1.1, tech design §3.1 badge table |

I-02/I-03/I-04 collectively double as the US-A5 acceptance check — three independent connectors landing with zero shared-pipeline/schema/digest edits is the proof the contract holds, not a separate ticket.

---

## Phase 2 — Processing (bronze → silver)

| ID | Track | Ticket | Depends on | Size | Spec |
|---|---|---|---|---|---|
| P-01 | DS | `LLMClient` — structured extraction, retry-once, LiteLLM-routed | F-06 | M | LLD §2.1 |
| P-02 | DS | `EmbeddingClient` — fastembed default + sentence-transformers adapter | F-05 | S | LLD §2.1 |
| P-03 | DS | Repost dedup: simhash + URL normalize, short-title fallback (`text_utils.py`) | — | S | Tech design §10.3 |
| P-04 | DS | Enrichment module: prompt + schema + call (`enrichment.py`) | P-01 | M | LLD §2.2 |
| P-05 | DE | Per-connector `to_canonical_draft` bodies: trafilatura extraction, near-empty flagging | I-02, I-03, I-04 | M | Tech design §3.2 |
| P-06 | DE | `process_batch` Prefect task: extract → dedup → enrich → embed → silver upsert, watermark default | P-01–P-05, F-02 | L | LLD §1.4 |

---

## Phase 3 — Story Clustering

| ID | Track | Ticket | Depends on | Size | Spec |
|---|---|---|---|---|---|
| C-01 | DS | Entity canonicalization + weighted overlap scoring | P-04 | S | LLD §2.3 |
| C-02 | DS | Dual-threshold matching rule + running-centroid update (`story_matching.py`) | C-01, P-02 | M | LLD §2.4 |
| C-03 | DE | `cluster_stories` Prefect task: match against batch + open stories, close-after-inactivity sweep | C-01, C-02, F-02 | M | LLD §1.4 |

---

## Phase 4 — dbt Core Marts

Models can be written before real data exists; tests can't be *validated* until Phase 1-3 have produced rows.

| ID | Track | Ticket | Depends on | Size | Spec |
|---|---|---|---|---|---|
| M-01 | DE | dbt project init | F-02 | S | LLD §0 |
| M-02 | DE | `stg_items`, `dim_source_registry` + tests | M-01 | S | LLD §1.5 |
| M-03 | DE | `fct_story_clusters`, `fct_story_trend_windows` + tests | M-01, C-03 (for validation) | M | LLD §1.5 |
| M-04 | DE | `fct_item_topics_resolved` — **fast-path only for now**, discovery/override inputs land in Phase 6 — + tests, incl. no non-`active` topic ever surfaces and the merge-chain-cycle check | M-01, P-04 | M | LLD §1.5, §1.2; tech design §3.6 |
| M-05 | DE | `fct_digest_trending`, `fct_digest_new` + tests | M-03, M-04 | M | LLD §1.5 |

---

## Phase 5 — Serving MVP

Closes the loop on every Must-priority story in the requirements brief's Epics A–C, E. This is the first demoable version.

| ID | Track | Ticket | Depends on | Size | Spec |
|---|---|---|---|---|---|
| S-01 | SWE | `GoldRepository` interface + Postgres implementation (`resolve_topic_proposal` collapsed per the ponytail pass, not three methods; includes `mute_topic`, added to close the US-D1 gap) | M-05 | M | LLD §3.1 |
| S-02 | SWE | `DigestBuilder`: pure assembly, `sent`-event logging, degraded-state handling (flagged items excluded, empty-digest message) | S-01 | S | LLD §3.2 |
| S-03 | SWE | Telegram bot: `/digest`, `/trending`, save/mute inline actions (item/source), `/saved` | S-02 | M | LLD §3.3 |
| S-04 | SWE | Dashboard: `/items`, `/saved`, `/clusters/{id}` coverage view, save/mute routes (item, source, and topic), degraded-item display | S-01 | M | LLD §3.4 |
| S-05 | DE | `ingest_flow` + `digest_flow` Prefect wiring, schedules live | I-02, I-03, I-04, I-05, I-06, P-06, C-03, S-02 | M | LLD §1.4 |
| S-06 | SWE | **Decision + implementation**: dashboard auth (network-restriction vs. login) | S-04 | S | LLD §3.5 open item — a product decision first, not just code |

---

## Phase 6 — Topic Discovery & Review Workflow

| ID | Track | Ticket | Depends on | Size | Spec |
|---|---|---|---|---|---|
| T-01 | DS | BERTopic wiring (`topic_discovery.py`): zero-shot list, LLM naming — verify exact API against the installed BERTopic version first | C-03, P-01 | M | LLD §2.5; tech design §2.6 API caveat |
| T-02 | DE | `discover_topics` Prefect task: weekly (90-day) + quarterly (365-day), same task, different window | T-01 | S | LLD §1.4 |
| T-03 | DE | Extend `fct_item_topics_resolved` with discovery-path + user overrides + merge-alias resolution | M-04, T-02 | M | LLD §1.2, tech design §3.4 |
| T-04 | SWE | `/review_topics` bot command + `/topics/pending` dashboard route + item topic-edit route | S-01, T-03 | M | LLD §3.3, §3.4 |

---

## Phase 7 — Evaluation & Tuning

E-01 has a calendar dependency, not just a code one — it needs several weeks of real clustering output to label against.

| ID | Track | Ticket | Depends on | Size | Spec |
|---|---|---|---|---|---|
| E-01 | DS | Story-pairs labeled eval set (~30-50 samples) + precision/recall script | C-03 (running for 2+ weeks) | M | LLD §2.7 |
| E-02 | DS | DuckDB workbench (`postgres_scanner` attach) | F-02 | S | Tech design §2.3 |
| E-03 | DS | First threshold retune pass (story-match thresholds, BERTopic `min_cluster_size`) against E-01 | E-01 | M | LLD §2.4, §2.5 |

---

## Phase 8 — Hardening & Launch

| ID | Track | Ticket | Depends on | Size | Spec |
|---|---|---|---|---|---|
| H-01 | DE | Backfill flow (pre-day-1 historical ingest) | I-05, P-06 | M | Tech design §8 |
| H-02 | DE | **Decision + implementation**: `bronze.raw_items` retention policy | F-02 | S | LLD §3.5 open item |
| H-03 | DE | Full Docker Compose: all services incl. optional `llama-server`, resource limits | F-03, all prior | M | Tech design §2.7/§2.8 |
| H-04 | DE+DS | Dependency pinning + image build (BERTopic + sub-deps, embedding backend, LLM libs) | T-01, P-01, P-02 | S | Tech design §2.4–§2.6 |
| H-05 | SWE | Degraded-state UX: empty digest, failed-enrichment item display | S-02, S-04 | S | LLD §3.2, §3.4 |

**Launch gate**: Phase 5 demoable + Phase 8 complete = Phase 1 ships. Phases 6-7 can run concurrently with 8, not strictly before it — topic discovery and evaluation are additive, not launch-blocking for the core daily-digest loop.

---

## Phase 9 — Backlog (Phase 2 product scope, not ticketed here)

Topic affinity + "For You" section, weekly recap, author-follow, exploration nudges, source health alerting, velocity/quadrant classification, coverage-gap flagging, sentiment, source lead/lag analysis. Full list and rationale: requirements brief §9/§11. Ticket these when Phase 2 is actually scheduled, not now — several depend on data that only exists after Phase 1 has run for a while (engagement history, topic time series).
