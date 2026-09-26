# Phase 1 — Low-Level Design Scope

**Purpose:** this is not the LLD itself — it's the checklist of exactly what each LLD section must specify before implementation starts, organized by the three tracks this application splits into (§1.3 of the technical design doc): Data Engineering, Data Science, Software Engineering. Each item below is a concrete artifact (a schema, a formula, a route contract), not a restatement of the HLD's intent.
**Companion docs:** `requirements-and-product-brief.md` (product rationale), `phase1-technical-design.md` (HLD, tooling decisions, DS methodology — §10 in particular is the direct source for most of Track 2 below).

---

## 1. Data Engineering — Pipelines & Data Models

### 1.1 Schema DDL
- Real table definitions for every bronze/silver/gold table in §5 of the technical design: exact types, nullability, constraints.
- Specific indexes, not left implicit: `story_clusters(status, last_item_at)` (the exact predicate the close-after-inactivity sweep and trend rollups filter on), a partial index on `topic_registry(status)` for `status='proposed'` (the weekly review query).
- `pipeline_config` schema, and the **full key list** it must hold — not just `story_close_after_days`: the two embedding-similarity thresholds (primary ~0.75, relaxed ~0.6-0.65), the entity fuzzy-match threshold, the simhash Hamming distance, BERTopic's `min_cluster_size` and zero-shot similarity cutoff, the trend-rollup velocity floor, the affinity shrinkage prior `k`. One shared read/write utility, not scattered per-job config reads.
- **Open decision, not yet made anywhere**: `bronze.raw_items` retention/archival policy.

### 1.2 Connector implementations
- Per-connector spec: exact fetch config (feed URLs, the Reddit User-Agent string, GitHub Trending scrape/API choice), retry/backoff policy, and the specific idempotency guarantee (`external_id` uniqueness enforcement).
- The `Connector` ABC's concrete contract: what `to_canonical_draft` must return per source type.

### 1.3 Prefect flow graphs
- **Ingest flow** (hourly): fetch → bronze insert → processing (extract/dedup/enrich/embed) → silver insert → story clustering → dbt run, as an explicit task DAG with per-task retries.
- **Digest flow** (daily).
- **Topic discovery flow** (weekly, 90-day window).
- **Topic discovery long-window flow** (quarterly, 12-month window) — its own schedule, not folded into the weekly one.
- Concurrency limits (cap concurrent enrichment LLM calls) and the actual cron schedule strings for each.

### 1.4 dbt project structure
- Folder layout (staging vs. marts) and the real SQL for every model in §3.6: `stg_items`, `dim_source_registry`, `fct_item_topics_resolved`, `fct_story_clusters`, `fct_story_trend_windows`, `fct_topic_monthly_counts`, `fct_digest_trending`, `fct_digest_new`, `fct_topic_affinity` (Phase 2).
- `schema.yml` test coverage per model (`not_null`, `unique`, `accepted_values`, referential integrity) plus the custom merge-chain-cycle test on `topic_registry`.

### 1.5 Idempotency & retry contracts
- Exact re-run behavior: does a partially-completed enrichment batch resume or reprocess from scratch? What state does a crashed story-clustering run leave `story_clusters` rows in?

### 1.6 Backfill procedure
- A runnable flow (not a manual script) for the pre-day-1 backfill referenced in §8.

### 1.7 Deployment / Docker Compose
- Service definitions: `postgres`, `prefect-server`, `prefect-worker`, `bot`, `dashboard`, optional `llama-server`.
- Health checks and startup ordering (bot/dashboard must wait on Postgres; Prefect tasks calling `llama-server` must wait on its health check).
- Resource limits for `llama-server` specifically (CPU/RAM allocation on the host).
- Secrets/env var wiring.

### 1.8 Dependency management
- Pinned versions for BERTopic and its sub-dependencies (UMAP, HDBSCAN or scikit-learn's built-in variant, the embedding backend).
- A stated tolerance for the resulting image size/build time — BERTopic's dependency tree is non-trivial and this should be a checked tradeoff, not an accident.

---

## 2. Data Science — Analytics, Methodology, LLM/NLP, Rule-Based

### 2.1 `LLMClient` / `EmbeddingClient` interfaces — currently a real gap
- §2 of the technical design describes routing through LiteLLM and choosing between fastembed/sentence-transformers, but no interface actually exists yet in §3's component design. This needs: method signatures, how a call-site selects a provider/backend, and — for `LLMClient` specifically — the structured-output contract (Pydantic schema in, validated object out, retry-once-then-flag on malformed response).
- Module/package boundary: this interface is genuinely cross-track (DE deploys `llama-server`, DS implements the backend adapters against it) — needs to be agreed as one contract, not built twice.

### 2.2 Prompt specifications, written in full
- The enrichment prompt: schema, few-shot examples covering a repo README, a benchmark table, and an opinion piece specifically (the edge cases §10.1 names but doesn't spell out).
- BERTopic's cluster-naming prompt: the 5-medoid-story input, the output spec, the explicit duplicate-check instruction against the active registry.
- The monthly summary-faithfulness judge prompt.

### 2.3 Entity canonicalization spec
- The normalization function (case-folding, punctuation stripping) and the `rapidfuzz` match threshold, applied at comparison time — not a parallel registry-with-workflow (rejected in §10.1's review pass).
- The Phase 1 default entity type-weight schedule (fixed weights per `{model, tool, company, paper, dataset, benchmark, person}`), with corpus-wide IDF weighting explicitly deferred unless the fixed schedule underperforms.

### 2.4 Embedding pipeline spec
- Exact model pin for fastembed's curated default, and the sentence-transformers fallback model name for the custom-model escape hatch.
- The domain-validation fixture (the 20-30 hand-picked "should/shouldn't cluster" pairs) and the acceptance criterion that decides between candidate models.
- The story representative-embedding running-centroid update formula.

### 2.5 Story matching algorithm spec
- The weighted entity-overlap formula with real per-type weights (not placeholders).
- The dual-threshold matching rule (primary embedding threshold AND entity overlap, OR exact specific-entity match with the relaxed threshold) with both values validated against the labeled eval set, not asserted.

### 2.6 Topic Discovery (BERTopic) configuration spec
- UMAP hyperparameters (`n_neighbors`, `min_dist`, `n_components`) and HDBSCAN's `min_cluster_size`/`min_samples`.
- Zero-shot topic list population: a query against `topic_registry WHERE status='active'`, re-run fresh every job run.
- **Explicit decision**: each weekly/quarterly run instantiates a fresh, stateless BERTopic instance (no persisted model artifact to version or drift-check between runs) — consistent with keeping this rule-plus-clustering, not a maintained learned model.
- Rejection-reason tracking (not coherent vs. duplicate-of-existing) feeding back into which parameter needs retuning.

### 2.7 Fast-path tagging retrieval spec
- Topic centroid embedding maintenance (incremental update rule, same pattern as story centroids) and the top-K retrieval value for the "candidate existing topics" shown in the enrichment prompt.

### 2.8 Reliability tiering
- The fixed `source_type → badge` table (already settled).
- The periodic empirical sanity-check query (once `engagement_events` accumulate): does save-rate roughly track tier as expected, flagged as a manual-review trigger, not an automated adjustment.

### 2.9 Trend rollup formulas
- The rate-normalization formula (mentions ÷ total items that period) used for cross-period comparisons.
- The velocity/EWMA smoothing spec and its minimum-count floor (an empirically chosen value, tracked in `pipeline_config`).

### 2.10 Topic affinity model (Phase 2)
- The shrinkage formula `(saves + k × base_rate) / (shown + k)` with starting `k ≈ 10`, and the process for revisiting `k` once real engagement history exists.

### 2.11 Evaluation harness
- The story-pairs labeled dataset schema and the precision/recall computation script — built first, before the other three (topic coherence, entity extraction, summary faithfulness), which are added only if a specific stage is later suspected of underperforming.
- **New addition**: the eval set must also check BERTopic's zero-shot assignment precision specifically (correctly matched to an existing topic vs. incorrectly force-fit), not just cluster coherence for new topics.
- Monthly review cadence, and the explicit threshold-update process: manual review → `pipeline_config` update, never automatic retraining.

### 2.12 Pre-implementation validation tasks (one-time, gate implementation decisions)
- Embedding model domain-validation test.
- CPU `llama-server` throughput benchmark against the per-item processing SLA (§6) — a go/no-go on whether the hourly fast path can run locally, or must stay on the API.

### 2.13 Dependency/model versioning
- Pinned versions: embedding model(s), BERTopic and its sub-dependencies, and the specific LLM model name/version if the local path is used.

---

## 3. Software Engineering — Bot & Dashboard

### 3.1 Telegram bot command handlers
- Exact handler function per command (`/digest`, `/trending`, `/review_topics`, `/saved`, save/mute inline actions).
- Inline-button callback-data format.
- Message templates per card type (article, repo, cluster-coverage).
- Multi-step state handling for `/review_topics` (confirm/reject/merge across several pending proposals in one session).

### 3.2 Dashboard route contracts
- FastAPI route signature (path, method, request/response model) for every route in §3.9: `/items`, `/saved`, `/clusters/{id}`, `/topics/pending`, `/items/{id}/save`, `/items/{id}/mute`, `/items/{id}/topics`, and Phase 2's `/topics/{tag}`.
- HTMX partial-template structure per page.

### 3.3 Shared query/repository layer
- One module both the bot and dashboard call for every gold-table read — the actual implementation of "one query layer, two thin clients."

### 3.4 User-action write paths
- Save/mute/topic-edit/topic-merge/topic-confirm-reject: idempotency handling (muting an already-muted source doesn't error) and the exact write sequence across `engagement_events`, `user_prefs`, `user_topic_overrides`, `topic_registry.status`.

### 3.5 Degraded-state UX
- Empty-digest state (zero trending stories, zero new items) renders as a real empty state, not a broken template.
- An item with a failed/flagged enrichment displays title + link only, never a blank or partially-rendered card.

### 3.6 Auth & security — an open decision
- Dashboard access model: network-level restriction (localhost/VPN-only) vs. a login system. Needs an explicit choice, not an implicit assumption.

### 3.7 Config/secrets management
- Env vars via `pydantic-settings`: Telegram bot token, LLM API key (if using the Anthropic path), Postgres connection string, `llama-server` URL (if using the local path).

### 3.8 Testing
- Unit tests for `DigestBuilder`'s assembly logic (no scoring logic to test, by design — just correct section composition).
- Integration tests for bot command flows and dashboard routes.

---

## 4. Cross-Track Contracts

These are the seams that let all three tracks build in parallel without drifting — pin these first.

### 4.1 DE → DS: the schema contract
Bronze/silver DDL, column-level types and nullability pinned before DS builds extraction/clustering logic against it.

### 4.2 DS → SWE: the gold view contract
Every `fct_*`/`dim_*` view's column contract pinned early enough that SWE can build the bot/dashboard against a stub of these views while DS is still tuning thresholds underneath them.

### 4.3 DE → SWE: the user-action table contract
`user_prefs`, `engagement_events`, `user_topic_overrides` shapes — SWE writes to these, DE's next pipeline run reads them back.

### 4.4 DE ↔ DS: infra vs. logic split for the local LLM path
DE owns whether `llama-server` is running and healthy (infra — an on-call concern). DS owns what gets sent to it and how the response is validated (logic — a prompt/schema concern). A slow-but-up model is DE's problem; a fast-but-malformed response is DS's problem — keep these separate so failures route to the right owner.

### 4.5 Revisit triggers — documented so they aren't only remembered in conversation
- **Prefect → Dagster**: a third developer joins wanting first-class asset lineage, or the asset graph grows materially (e.g. multi-category actually landing, not just schema-ready for it).
- **fastembed → sentence-transformers** (per model): needed the moment a custom/fine-tuned model outside fastembed's curated list is actually used, not preemptively.
- **Local LLM ↔ API, per call-site**: decided by the §2.12 throughput benchmark outcome, and revisited if that outcome changes (e.g. a faster server, a smaller/faster model).
