# Phase 1 — Low-Level Design

**Purpose:** the concrete fill-in for every item in `low-level-design-scope.md` — real schemas, interface signatures, and formulas. Not code, not a restatement of *why* (that's `phase1-technical-design.md` §10).

---

## 0. Repository Layout

```
knowledge-app/
├── docker-compose.yml
├── pyproject.toml              # one dependency set for now — splitting per-service is
│                                # premature until there's a reason two services need
│                                # conflicting dependency versions
├── .env.example
│
├── sql/
│   └── migrations/              # plain numbered SQL, applied in order — no ORM/Alembic;
│       └── 001_initial_schema.sql   # nothing here is object-relational, it's raw SQL either way
│
├── dbt/                          # its own top-level dir: dbt has its own project
│   ├── dbt_project.yml           # conventions (models/, tests/, seeds/), don't nest it
│   └── models/                   # inside src/ and fight that convention
│       ├── staging/stg_items.sql
│       └── marts/
│           ├── dim_source_registry.sql
│           ├── fct_item_topics_resolved.sql
│           ├── fct_story_clusters.sql
│           ├── fct_story_trend_windows.sql
│           ├── fct_topic_monthly_counts.sql
│           ├── fct_digest_trending.sql
│           ├── fct_digest_new.sql
│           └── fct_topic_affinity.sql        # Phase 2
│
├── src/
│   ├── connectors/            # one file per source family, all implementing base.Connector
│   │   ├── base.py
│   │   ├── rss.py              # Netflix, Jay Alammar, Spotify, SeattleDataGuy, arXiv×3
│   │   ├── reddit.py
│   │   └── github_trending.py
│   │
│   ├── ml/                     # provider-agnostic clients only — no pipeline orchestration
│   │   ├── llm_client.py
│   │   └── embedding_client.py
│   │
│   ├── pipeline/               # where DE orchestration and DS algorithms meet —
│   │   ├── tasks.py            # tasks.py stays thin (Prefect wiring only); the modules
│   │   ├── enrichment.py       # beside it hold the actual logic each task calls
│   │   ├── story_matching.py
│   │   ├── topic_discovery.py
│   │   └── text_utils.py
│   │
│   ├── gold/
│   │   └── repository.py       # the one query layer — bot and dashboard both import this
│   │
│   ├── bot/
│   │   └── handlers.py
│   │
│   └── dashboard/
│       ├── routes.py
│       └── templates/
│
├── flows/
│   └── flows.py                 # schedules + task sequencing only, zero business logic
│
└── tests/
    ├── test_story_matching.py
    ├── test_text_utils.py
    └── fixtures/
        └── labeled_story_pairs.json   # the §2.7 evaluation harness data
```

**Why grouped by module, not by track**: `pipeline/` mixes Data Engineering (orchestration) and Data Science (algorithms) code deliberately — they collaborate tightly at exactly that layer, so a folder-per-track split (`data_engineering/`, `data_science/`, `software_engineering/`) would fossilize an org chart into the code rather than reflect what actually depends on what. Track ownership (§1–§3 below) is documentation on top of this structure, not a mirror of it.

---

## 1. Data Engineering

### 1.1 Exact schema — storage tables

```sql
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

-- ============================================================ bronze (immutable, append-only)

CREATE TABLE bronze.raw_items (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id     TEXT NOT NULL,
    source_type   TEXT NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    external_id   TEXT NOT NULL,
    raw_payload   JSONB NOT NULL,
    fetch_status  TEXT NOT NULL CHECK (fetch_status IN ('ok', 'error', 'empty')),
    UNIQUE (source_id, external_id)             -- re-fetching the same item is a no-op
);
CREATE INDEX idx_raw_items_source_fetched ON bronze.raw_items (source_id, fetched_at);

-- ============================================================ silver (canonical, post-dedup)

CREATE TABLE silver.items (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_url    TEXT NOT NULL UNIQUE,
    title            TEXT NOT NULL,
    title_simhash    BIGINT NOT NULL,
    author           TEXT,
    published_at     TIMESTAMPTZ NOT NULL,
    cleaned_text     TEXT NOT NULL,
    summary          TEXT NOT NULL,
    key_entities     JSONB NOT NULL DEFAULT '[]',    -- [{"name": str, "type": str}]
    embedding        FLOAT4[] NOT NULL,               -- plain array, NOT pgvector's VECTOR type —
                                                        -- phase1-technical-design.md §2.3 rejected pgvector at this scale;
                                                        -- migrate this column's type only if that
                                                        -- decision is revisited, not before
    source_ids       TEXT[] NOT NULL,
    item_type        TEXT NOT NULL CHECK (item_type IN ('article', 'repo')),
    inserted_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_items_simhash ON silver.items (title_simhash);
CREATE INDEX idx_items_published ON silver.items (published_at);

CREATE TABLE silver.item_topics_llm (          -- fast path: per-item LLM tagging
    item_id     UUID NOT NULL REFERENCES silver.items(id) ON DELETE CASCADE,
    topic_id    UUID NOT NULL,                  -- FK added below, after gold.topic_registry exists
    confidence  REAL,
    tagged_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, topic_id)              -- re-tagging the same pair is a no-op
);

-- ============================================================ gold (read surface + user writes)

CREATE TABLE gold.source_registry (
    id               TEXT PRIMARY KEY,
    domain_or_handle TEXT NOT NULL,
    source_type      TEXT NOT NULL,
    category         TEXT NOT NULL,               -- static, set once at onboarding, never per-item
    badge            TEXT NOT NULL
);

CREATE TABLE gold.topic_registry (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name  TEXT NOT NULL,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('proposed', 'active', 'rejected', 'merged')),
    merged_into_id  UUID REFERENCES gold.topic_registry(id),   -- alias target, resolved at query time
    origin          TEXT NOT NULL CHECK (origin IN ('llm_fast_path', 'discovery', 'user_created')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_name, category)
);
CREATE INDEX idx_topic_registry_pending ON gold.topic_registry (status) WHERE status = 'proposed';

CREATE TABLE gold.story_clusters (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status                   TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    first_seen_at            TIMESTAMPTZ NOT NULL,
    last_item_at             TIMESTAMPTZ NOT NULL,
    representative_title     TEXT NOT NULL,        -- seed item's title; set once, never updated —
                                                     -- BERTopic needs real text per story, not just a vector
    representative_embedding FLOAT4[] NOT NULL,     -- running centroid, updated on every attach
    entity_set               JSONB NOT NULL DEFAULT '[]'
);
CREATE INDEX idx_story_clusters_open ON gold.story_clusters (status, last_item_at) WHERE status = 'open';

CREATE TABLE gold.story_cluster_members (
    story_id    UUID NOT NULL REFERENCES gold.story_clusters(id) ON DELETE CASCADE,
    item_id     UUID NOT NULL REFERENCES silver.items(id),
    attached_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (story_id, item_id)                 -- re-attaching is a no-op
);

CREATE TABLE gold.story_topics_discovered (      -- discovery path — story grain, kept separate
    story_id      UUID NOT NULL REFERENCES gold.story_clusters(id) ON DELETE CASCADE,
    topic_id      UUID NOT NULL REFERENCES gold.topic_registry(id),
    cluster_score REAL,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (story_id, topic_id)
);

CREATE TABLE gold.user_topic_overrides (          -- additive corrections, same pattern as save/mute
    item_id    UUID NOT NULL REFERENCES silver.items(id),
    topic_id   UUID NOT NULL REFERENCES gold.topic_registry(id),
    action     TEXT NOT NULL CHECK (action IN ('add', 'remove')),
    edited_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, topic_id)                -- one override per (item, topic); re-editing upserts `action`
);

CREATE TABLE gold.user_prefs (
    id             TEXT PRIMARY KEY DEFAULT 'alex',   -- single-user; exactly one row
    muted_sources  TEXT[] NOT NULL DEFAULT '{}',
    muted_topics   TEXT[] NOT NULL DEFAULT '{}',
    saved_item_ids UUID[] NOT NULL DEFAULT '{}'
);

CREATE TABLE gold.engagement_events (               -- append-only, system- and user-generated
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_type TEXT NOT NULL CHECK (subject_type IN ('item', 'cluster')),
    subject_id   UUID NOT NULL,
    event_type   TEXT NOT NULL CHECK (event_type IN ('sent', 'opened', 'saved', 'muted', 'ignored')),
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subject_type, subject_id, event_type)     -- e.g. "sent" only ever fires once per subject
);

CREATE TABLE gold.pipeline_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO gold.pipeline_config (key, value) VALUES
    ('story_close_after_days', '60'),
    ('story_match_embedding_threshold', '0.75'),
    ('story_match_embedding_threshold_relaxed', '0.65'),
    ('entity_fuzzy_match_threshold', '0.90'),
    ('simhash_hamming_threshold', '3'),
    ('topic_discovery_min_cluster_size', '5'),
    ('topic_discovery_zeroshot_similarity', '0.7'),
    ('trend_velocity_min_count', '5'),
    ('topic_affinity_prior_strength', '10');

CREATE TABLE gold.pipeline_watermarks (
    task_name         TEXT PRIMARY KEY,
    last_processed_at TIMESTAMPTZ NOT NULL
);

-- cross-schema FK, added last since gold.topic_registry must exist first
ALTER TABLE silver.item_topics_llm
    ADD CONSTRAINT fk_item_topics_llm_topic FOREIGN KEY (topic_id) REFERENCES gold.topic_registry(id);
```

### 1.2 Data contract — dbt marts (what SWE and DS actually query)

These are the output columns each model guarantees — the pinned contract from §4's cross-track section. The SQL that produces them is an implementation detail; this column list is not.

| Model | Columns |
|---|---|
| `dim_source_registry` | source_id, category, source_type, badge |
| `fct_item_topics_resolved` | item_id, topic_id, canonical_name, category |
| `fct_story_clusters` | story_id, representative_title, distinct_source_count, source_diversity_weight, status, first_seen_at, last_item_at |
| `fct_story_trend_windows` | story_id, window (`'7d'\|'30d'\|'90d'`), distinct_source_count |
| `fct_topic_monthly_counts` | topic_id, canonical_name, month, item_count, total_items_that_month, rate |
| `fct_digest_trending` | story_id, representative_title, distinct_source_count, sample_item_id, link, badge |
| `fct_digest_new` | item_id, title, link, badge, published_at |
| `fct_topic_affinity` (Phase 2) | topic_id, canonical_name, save_rate, base_rate, affinity_score |

`representative_title` is a fill-in this pass surfaced: BERTopic needs real text per story for its document-based naming step, not just embeddings/entities — without it, topic discovery (§2.5) has nothing to cluster on.

### 1.3 Connector contract
`fetch(since: datetime|None) -> list[RawItem]`, `to_canonical_draft(raw) -> CanonicalDraft`. `since=None` reads the connector's own watermark; an explicit `since` is a replay window and never touches the watermark. Per-source specifics unchanged from `phase1-technical-design.md` §3.1.

### 1.4 Task/flow structure — this is the answer to "recreate from any step"

| Task | Trigger param | Idempotency | Schedule |
|---|---|---|---|
| `fetch_source` | `since` (default: watermark) | `UNIQUE(source_id, external_id)` | hourly, per connector |
| `process_batch` | `since` | `UNIQUE(canonical_url)` upsert | hourly, after fetch |
| `cluster_stories` | `since` | `UNIQUE(story_id, item_id)` on attach | hourly, after process |
| `discover_topics` | `window_days` (90 or 365 — always a fresh full window, not watermark-based) | `UNIQUE(story_id, topic_id)` | weekly / quarterly |
| `digest_flow` | — (always "now") | `UNIQUE(subject, event_type)` on sent | daily |

Every task is independently callable with an explicit override — that's the whole mechanism, not a separate "replay system." Scheduled calls pass no arguments; manual replay passes `since`/`window_days` explicitly and never advances the watermark.

### 1.5 dbt models (grain + core logic)

| Model | Grain | Logic |
|---|---|---|
| `stg_items` | item | typing/staging pass |
| `dim_source_registry` | source | static badge/category |
| `fct_item_topics_resolved` | item×topic | union(fast-path, discovery-via-story-membership) − rejected, resolve `merged_into_id`, apply user overrides, filter `status='active'` |
| `fct_story_clusters` | story | distinct-source-count, source-diversity weight (join `dim_source_registry`) |
| `fct_story_trend_windows` | story×window | `COUNT(DISTINCT source)` over 7/30/90-day slices |
| `fct_topic_monthly_counts` | topic×month | count from `fct_item_topics_resolved`, rate-normalized by total items that month |
| `fct_digest_trending` | story | `fct_story_clusters` where distinct_source_count ≥ 2 AND no `sent` event yet |
| `fct_digest_new` | item | items outside any qualifying story, not yet sent |
| `fct_topic_affinity` (Phase 2) | topic | shrinkage formula, §2.6 |

### 1.6 Deployment
Docker Compose: `postgres`, `prefect-server`, `prefect-worker`, `bot`, `dashboard`, optional `llama-server` (health-checked before any task depends on it).

---

## 2. Data Science

### 2.1 `LLMClient` / `EmbeddingClient` interfaces
- `LLMClient.extract(prompt: str, schema: type[T]) -> T` — **one** concrete class; provider is a LiteLLM model string in config (an Anthropic model name, or an OpenAI-compatible URL pointed at `llama-server`). Retries once on schema-validation failure, then raises for the caller to flag-not-drop.
- `EmbeddingClient.embed(texts: list[str]) -> list[list[float]]` — **two** adapters (fastembed default, sentence-transformers for custom/fine-tuned models), backend chosen once via config, never per-call.

### 2.2 Enrichment
One call per item → `{summary, key_entities: [{name, type}], topics: []}`. Entity types: `model|tool|company|paper|dataset|benchmark|person`. Prompt carries 3 worked examples (repo README, benchmark post, opinion piece) and the current active-topic list. Malformed response: retry once, then flag — same handling as a near-empty trafilatura extraction.

*Deferred, not built yet*: top-K topic retrieval by embedding similarity (§10.6) — the full active-topic list is passed as-is under ~100 topics; retrieval only earns its cost once the list is actually that large.

### 2.3 Entity canonicalization
Normalize (lowercase, strip punctuation), fuzzy-match at comparison time only — no persisted alias table. Overlap-scoring weights: model/paper = 3.0, dataset/benchmark = 2.5, tool = 1.5, company/person = 1.0.

### 2.4 Story matching
Match if **(**weighted entity overlap ≥ 0.3 **AND** embedding cosine ≥ `story_match_embedding_threshold`**)** **OR** **(**exact match on a model/paper/dataset/benchmark entity **AND** cosine ≥ the relaxed threshold**)**. On attach: centroid = running mean; entity set = union. Closes to new matches after `story_close_after_days` of inactivity; history stays queryable regardless of status.

### 2.5 Topic Discovery — BERTopic
Zero-shot list = current `status='active'` topic names, re-read fresh every run (no persisted model state between runs). Clusters *story* titles/embeddings, not raw items. Naming: one LLM call per discovered cluster over its 5 representative stories, checked against the zero-shot list for duplicates. Runs at two cadences (weekly/90-day, quarterly/365-day) — same logic, different window parameter, no forked code. Every new name enters the registry as `proposed`; noise-labeled stories get no topic, correctly.

### 2.6 Trend & affinity formulas
- Rate, not raw count, for any cross-period comparison: mentions ÷ total items that period.
- Velocity: EWMA or a minimum-count floor (`trend_velocity_min_count`) before computing week-over-week change.
- Topic affinity (Phase 2): `(saves + k×base_rate) / (shown + k)`, `k = topic_affinity_prior_strength` (starting 10).

### 2.7 Evaluation harness
One labeled set first — story-pairs (same/different story), ~30-50 samples, monthly review, precision/recall tracked against current thresholds. Topic-coherence/entity/faithfulness sets are added only if a specific stage is later suspected of underperforming, not built in parallel from day one. BERTopic's zero-shot assignment precision is checked as part of this same review, not a separate harness.

---

## 3. Software Engineering

### 3.1 `GoldRepository` — one interface, two callers
`trending_candidates()`, `for_you_candidates()`, `new_candidates()`, `cluster_coverage(story_id)`, `record_events(subject_ids, event_type)`, `save_item(id)`, `mute_source(id)`, `mute_topic(id)`, `pending_topic_proposals()`, `resolve_topic_proposal(topic_id, action, merge_into=None)` (`action` ∈ `confirm|reject|merge`).

`mute_topic(id)` was a gap this pass caught: `user_prefs.muted_topics` exists in the schema and US-D1 requires muting a topic outright, not just individual items or whole sources — the method list above was missing it.

### 3.2 DigestBuilder
Assembles trending + for-you + new candidates into cards, records one `sent` event per card. No ranking/scoring logic here — all of it lives in the dbt models (§1.5).

**Degraded states**: an item flagged with a failed extraction/enrichment never reaches a digest candidate query — the dbt marts (§1.5) select only successfully-enriched items, so a failure is an absence, not a broken card. An empty digest (no trending/new candidates at all) still sends, with a one-line "nothing new today" message — never a skipped send and never an empty, card-less message with no explanation.

### 3.3 Telegram commands
`/digest`, `/trending [source_type]`, `/review_topics` (confirm/reject/merge, batched weekly), `/saved`, inline save/mute buttons (item or source). Muting a topic outright is a dashboard-only action (§3.4) — it's a registry-level edit, not a natural fit for a per-item inline button.

### 3.4 Dashboard routes
`GET /items`, `GET /saved`, `GET /clusters/{id}` (coverage view), `GET /topics/pending` (review), `POST /items/{id}/save`, `POST /items/{id}/mute`, `POST /topics/{id}/mute`, `POST /items/{id}/topics` (override).

**Degraded states**: an item with a flagged extraction/enrichment failure renders with an explicit "not fully processed" marker instead of blank/empty fields.

### 3.5 Still open — not silently defaulted
- Dashboard auth: network-restriction vs. login.
- `bronze.raw_items` retention policy.

---

## 4. Cross-Track Contracts
- **DE → DS**: bronze/silver schema (§1.1) is pinned before DS builds extraction/clustering against it.
- **DS → SWE**: gold views (`fct_*`/`dim_*`) are pinned before SWE builds the bot/dashboard — SWE never reads silver or raw model output directly.
- **DE → SWE**: `user_prefs` / `engagement_events` / `user_topic_overrides` shapes — SWE writes, DE's next pipeline run reads back.
- **DE ↔ DS** (`llama-server`): DE owns uptime/health; DS owns prompt correctness and response validation — kept as separate on-call concerns.
