-- Phase 0 F-02. This file is the applied form of low-level-design.md §1.1 —
-- that document is the source of truth; keep the two in sync by hand since
-- there's no schema-generation tool in front of either.

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
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),  -- when the row landed in bronze, distinct
                                                        -- from fetched_at (when the connector fetched it)
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
