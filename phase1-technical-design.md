# Phase 1 — Technical Design (HLD + Tooling + Data Flow)

**Audience:** Lead Engineer and Lead Data Scientist, implementation-level review.
**Companion doc:** `requirements-and-product-brief.md` — read that first for *why* each analytical capability exists (§6) and the full user stories (§7). This doc is the *how*: pipeline design, tooling choices, schemas.
**Scope:** Phase 1 MVP — single domain (AI Engineering), single user (Alex), Telegram bot + minimal web dashboard.

**Key framing:** This is a small, ML-augmented data pipeline, not a request/response app. Two things drive every design choice below:
1. **Volume is tiny** (dozens of items/day across 7 sources). Tools sized for millions-of-rows or high-QPS problems (vector databases, Spark, Kubernetes) would be pure overhead here — every tool choice is justified against this actual scale, not against what's popular.
2. **The pipeline has a real DAG now**, not a single linear script: ingest → clean/dedupe → enrich (ML) → embed (ML) → cluster into stories (ML, stateful) → discover topics (ML, periodic) → roll up (SQL) → serve. Each stage has one job and a clear handoff.

---

## 1. High-Level Design

### 1.1 Category / Topic / Story hierarchy

Three levels of granularity, used consistently across the whole design:

- **Category** (e.g. "AI Engineering", "DevOps") — a static property of each *source*, assigned once at source onboarding (`source_registry.category`), not inferred per item. Every Phase 1 source is category "AI Engineering." Adding a DevOps source later is "register a source with `category='DevOps'`," not a new ML step — category costs nothing beyond a column and a join.
- **Topic** (e.g. "GLM model family", "data quality tools") — a tag, many-to-many with items/stories, sourced from two distinct mechanisms (§3.4).
- **Story** (e.g. "GLM 5.2 wins benchmark X", "OpenAI/HuggingFace incident") — the finest grain: a specific, time-bounded event that multiple items may independently cover. Most items (tutorials, opinion pieces) never join a story — that's expected, not a bug.

**Modeling approximations, stated explicitly so they're not mistaken for firm truths:**
- Story↔Topic is many-to-many (a story can reasonably carry two tags). Topic↔Category is many-to-one — each topic has one primary category, purely to keep rollups simple. A topic like "developer tooling" could genuinely span AI Engineering and DevOps; don't build many-to-many category assignment preemptively, revisit only if that friction actually shows up in practice.
- Topic granularity is a judgment call, not a hard rule — "specific models" (broad) and "GLM model family" (narrow) are both plausible topics but produce very different rollup behavior (too coarse and trend rollups can't discriminate; too fine and every topic is sparse, noisy data). Both the fast-path tagging prompt and the discovery job's naming step should be steered toward topics with at least a handful of items/month at current volume — a data-driven granularity heuristic, not a fixed rule, and one to revisit as volume grows.

### 1.2 System Topology

```
                    +-------------------------------------------+
                    |         Prefect (orchestration)            |
                    |  ingest flow (hourly) | digest flow (daily)|
                    |  | topic discovery flow (weekly)           |
                    +-----------------+---------------------------+
                                      |
        +-----------------------------+-----------------------------+
        |                             |                             |
        v                             v                             v
+----------------+          +------------------+          +--------------------+
| feedparser pool |          | Reddit connector |          | GitHub Trending    |
| (4 blogs, arXiv |          | (feedparser +    |          | (scrape/Search API)|
|  x3)            |          |  User-Agent)     |          |                    |
+--------+---------+         +--------+---------+          +----------+---------+
         |                            |                               |
         +----------------------------+-------------------------------+
                                       |   all emit RawItem; each source
                                       |   is pre-tagged with a category
                                       v   (source_registry, §3.1)
                    +------------------------------------+
                    |  BRONZE (Postgres)                  |
                    |  raw_items — immutable, append-only |
                    +-------------------+------------------+
                                        |
                                        v
                    +------------------------------------+
                    |  Processing (Python/Prefect task)    |
                    |  1. trafilatura extraction           |
                    |  2. repost dedup (URL + simhash)     |
                    |  3. enrichment (LLM: summary +       |
                    |     typed entities + fast-path topic |
                    |     tags, validated)                 |
                    |  4. embedding (local sentence-        |
                    |     transformer, CPU)                |
                    +-------------------+------------------+
                                        |
                                        v
                    +------------------------------------+
                    |  SILVER (Postgres)                  |
                    |  items, item_topics_llm              |
                    +-------------------+------------------+
                                        |
                                        v
                    +------------------------------------+
                    |  Story Clustering (Python/Prefect,   |
                    |  incremental — matches new items      |
                    |  against today's batch + currently     |
                    |  OPEN stories only, §3.3)              |
                    +-------------------+------------------+
                                        |
                    +-------------------+------------------+
                    |  Topic Discovery (Python/Prefect,    |
                    |  periodic, batch — clusters recent    |
                    |  STORY embeddings to propose new       |
                    |  topics, §3.4)                         |
                    +-------------------+------------------+
                                        |
                                        v
                    +------------------------------------+
                    |  dbt (SQL rollups, tested + docs)    |
                    |  badge derivation, cluster stats,    |
                    |  windowed trend rollups, resolved     |
                    |  topics view                          |
                    +-------------------+------------------+
                                        |
                                        v
                    +------------------------------------+
                    |  GOLD (Postgres)                    |
                    |  items, story_clusters, topic_*,     |
                    |  user_prefs, engagement_events,       |
                    |  topic_registry (proposal/confirm)    |
                    +----+-----------------------+----+
                         |                       |
                         v                       v
              +--------------------+   +----------------------+
              | Telegram Bot       |   | Web Dashboard         |
              | (thin presentation, |   | FastAPI + HTMX        |
              |  + weekly topic     |   | + coverage/topic views|
              |  review prompt)     |   | + topic review/edit   |
              +--------------------+   +----------------------+
                         ^
                         |
                    +----+----+
                    |  Alex   |
                    +---------+

              (side capability, not in the serving path)
                    +----------------------------+
                    | DuckDB — DS workbench       |
                    | attaches to Postgres for    |
                    | EDA / clustering quality     |
                    | spot-checks                  |
                    +----------------------------+
```

### 1.3 Why this shape (SRP at the system level)

| Stage | Owns | Does not own |
|---|---|---|
| Connectors | Fetching + parsing one source, tagged with a static category | Cleaning, dedup, enrichment |
| Processing | Clean text, collapse literal reposts, per-item enrichment (summary/entities/fast-path topics), embed | Cross-source story matching, topic discovery |
| Story Clustering | Deciding which items describe the same event, over time | Aggregating stats from that decision |
| Topic Discovery | Proposing new topics from patterns across stories | Deciding whether a proposal is confirmed — that's Alex's call (§3.5) |
| dbt | SQL rollups over already-decided facts | Any ML inference or stateful clustering |
| Bot / Dashboard | Presenting resolved gold rows, capturing user actions and topic-review decisions | Any scoring, clustering, or tagging logic |

This split is the direct fix for a problem in the earliest design: `DigestBuilder` used to embed scoring logic (the now-retired decay score) directly in the presentation layer. All business logic now lives in reviewable, tested dbt models; the bot/dashboard layer is pure assembly.

---

## 2. Tooling & Stack Decisions

For each capability: what it's for, what was considered, what was chosen, and why.

### 2.1 Orchestration — **Prefect**

Three scheduled flows: ingest (hourly), digest (daily), topic discovery (weekly — deliberately less frequent; see §3.4). Chosen for a pure-Python, decorator-based (`@flow`/`@task`) model with built-in retries and a self-hosted UI for run history — proportionate to a single-developer project.

| Option | Verdict | Why |
|---|---|---|
| **Prefect** | **Chosen** | Low operational footprint (one process), retries via `@task(retries=3)`, free local UI |
| Dagster | Considered | Its asset-based model (declare each medallion table as a software-defined asset with lineage) is conceptually a strong fit — worth revisiting if a second developer joins and wants first-class lineage as a feature, not yet justified by the ops overhead (webserver + daemon) |
| Airflow | Rejected | Built for large multi-team, many-DAG environments; disproportionate for 7 sources and a handful of daily jobs |
| Cron scripts (original design) | Rejected, superseded | Adequate when the pipeline was "ingest, then digest." No longer adequate with real inter-stage dependencies (clustering needs enrichment done; dbt needs clustering done) needing explicit ordering and retry |

### 2.2 Transformation layer — **dbt-core**

Every SQL-expressible rollup (badge derivation, cluster stats, windowed trend counts, the resolved-topics view) is a tested, documented dbt model — not logic buried in application code. Tunables (e.g. the story-close window, §3.3) live in a small Postgres `pipeline_config` table, read by both the Python jobs and dbt model configs — one place to change a tunable, not hardcoded in either layer.

| Option | Verdict | Why |
|---|---|---|
| **dbt-core** | **Chosen** | Tests (`not_null`, `unique`, `accepted_values`, referential integrity) + auto-generated docs with a lineage graph — a broken join or schema drift fails a dbt test before it reaches the bot |
| Hand-written SQL in application code | Rejected, previous approach | No tests, no lineage, rollup correctness was invisible outside reading Python |
| Full warehouse (Snowflake/BigQuery) + dbt Cloud | Rejected | Solves a scale problem (huge data, many analysts) this system doesn't have |

What stays Python, never dbt: trafilatura extraction, the enrichment LLM call, embedding generation, story clustering, topic discovery clustering — anything that's ML inference or stateful grouping. dbt reads the *output* of these and rolls it up; it never does the inference.

### 2.3 Storage — **Postgres** (system of record), **DuckDB** (DS workbench)

| Option | Verdict | Why |
|---|---|---|
| **Postgres** | **Chosen**, system of record | One engine for bronze/silver/gold as separate schemas; handles both OLTP reads (bot/dashboard) and OLAP-shaped rollups fine at this row count |
| **DuckDB** | **Chosen**, DS workbench only, not production | Attaches directly to Postgres (`postgres_scanner`) or reads Parquet snapshots, zero server to run — the right tool for ad hoc EDA, backtesting clustering/tagging precision against a hand-labeled sample, prototyping a rollup before it becomes a dbt model |
| Vector DB (Pinecone/Weaviate/Qdrant) | **Rejected** | Solves approximate nearest-neighbor search at millions-of-vectors, high-QPS, live-serving scale. Every similarity computation here is offline batch: story matching compares a new item against *currently open stories* (tens to low hundreds at once, §3.3), and topic discovery clusters *story-level* embeddings (thousands per year, not raw items) periodically. A `numpy`/`scipy` linear scan is milliseconds at both scales — a vector DB would be infrastructure with no measurable benefit |
| `pgvector` | **Rejected for now, flagged as the scaling path** | Even an index is unnecessary at these row counts. If sources/categories expand enough that the relevant corpus grows by orders of magnitude, `pgvector` — an extension on the Postgres already in use, not new infrastructure — is the natural next step, not a dedicated vector DB |

### 2.4 Enrichment & LLM Provider (summary + entities + fast-path topics) — **structured call, provider-flexible**

| Option | Verdict | Why |
|---|---|---|
| **One structured LLM call** returning `{summary, key_entities, topics}`, routed via **LiteLLM** to either the **Anthropic API** or a **self-hosted `llama-server`** (llama.cpp, OpenAI-compatible endpoint) | **Chosen** | `key_entities` is a single typed field (`{name, type}`), not two overlapping free-text fields — avoids the model drawing an arbitrary, inconsistent line between similar-sounding fields. Fast-path topic tags are checked against the current *active* topic registry so the model prefers reuse over minting near-duplicates. LiteLLM makes the provider a config value, not a code path — the API for volume-sensitive calls, a local model for infrequent ones, or either, per call-site |
| Local NLP stack (spaCy NER + zero-shot classifier + extractive summarizer) | Rejected | Lower quality (general NER misses AI/ML-specific entities) and more maintenance surface (three models to version-pin) than one structured call |

**Consideration**: local (llama.cpp) inference is meaningfully slower than the API on CPU, and the per-item SLA (§6) assumes API latency — throughput on the actual server needs testing before the hourly fast path runs locally; grammar-constrained decoding guarantees valid *shape*, not extraction *quality*, so format reliability and content quality should be judged separately when comparing providers.

**General principle applied here and elsewhere**: no field gets added to this schema without a concrete downstream reader. `key_entities` and `topics` each have one (story matching; topic rollups). A speculative "other descriptive columns" field would not — don't add one without first naming the query or view that needs it.

### 2.5 Embeddings — **fastembed (default), sentence-transformers (custom/fine-tuned models)**

| Option | Verdict | Why |
|---|---|---|
| **fastembed** (ONNX Runtime, no torch) | **Chosen, default** | Free, no API cost, no rate limits, lightweight (no PyTorch dependency) for its curated model list — used at two grains: per-item (secondary confirmation in story matching) and per-story (representative embedding, input to topic discovery) |
| **sentence-transformers** | **Chosen, escape hatch** | Loads any HuggingFace model natively, including custom fine-tunes, with zero conversion step — used specifically when a model isn't in fastembed's curated list |

**Consideration**: fastembed can load custom/fine-tuned models too, but anything outside its curated list needs a one-time ONNX export first — sentence-transformers avoids that friction at the cost of the heavier torch dependency, so the pluggable `EmbeddingClient` interface (§3) picks the backend per model, not globally.

### 2.6 Topic Discovery — **BERTopic**

| Option | Verdict | Why |
|---|---|---|
| **BERTopic** (embeddings → UMAP → HDBSCAN, with zero-shot topic assignment + pluggable LLM labeling) | **Chosen** | Packages the pipeline §10.5 already specified, plus zero-shot assignment against the active topic registry *before* clustering (structurally enforces "prefer an existing topic," not just an after-the-fact naming check) and reduces topic-identity churn between weekly re-runs, since anything matching a confirmed topic is assigned directly rather than re-discovered |
| Hand-rolled UMAP + HDBSCAN | Superseded | Same underlying algorithm, but BERTopic's zero-shot mode and representative-document selection for labeling replace custom code that would otherwise need to be built and maintained |
| LLM-native topic induction (no embeddings/clustering) | Rejected | Trades away the fixed, deterministic, evaluable pipeline this design depends on, and implies many more LLM calls per run — a worse fit given a possibly CPU-bound local model |

**Consideration**: BERTopic still depends on the same UMAP/HDBSCAN hyperparameters from §10.5 (`min_cluster_size`, dimensionality) — adopting the library doesn't remove the need to validate those against the labeled eval set, it removes the need to hand-write the pipeline around them.

### 2.7 Packaging & deployment — **Docker Compose**

Services: `postgres`, `prefect-server` (or Prefect Cloud free tier), `prefect-worker` (runs all scheduled flows), `bot`, `dashboard`, and optionally `llama-server` if the local LLM path (§2.4) is used. Single-host `docker-compose.yml`. No Kubernetes — that solves multi-node scheduling and rolling deployment across a fleet, a problem a single-user personal tool doesn't have.

### 2.8 Explicitly rejected, with reasoning

| Tool | Why it's not here |
|---|---|
| Airbyte / Meltano (EL platforms) | Built for connecting to well-known SaaS/DB sources via pre-built connectors. All 7 sources here are bespoke (feedparser + a UA header, a trending-page scrape) — no pre-built connector to gain from, and standing up Airbyte's own infrastructure (its own Postgres, scheduler, UI) to run 7 custom Python fetchers is strictly more operational surface than the fetchers themselves |
| Message queue (Kafka/RabbitMQ/Redis Streams) | Scheduled batch pipeline, not high-throughput event-driven — nothing here produces events faster than the daily/hourly/weekly cadence already handles |
| Full observability stack (Prometheus/Grafana) | Prefect's own UI already gives per-task run history and failure visibility at this pipeline's scale; a dedicated metrics stack is overhead with no additional signal to show yet |
| Kubernetes | See §2.7 |

---

## 3. Application / Component Design

### 3.1 Connector Contract & Source Registry

```python
class SourceRegistryEntry(BaseModel):
    id: str
    domain_or_handle: str
    source_type: str
    category: str          # static, set at onboarding — e.g. "AI Engineering" for every Phase 1 source
    badge: str              # reliability badge, derived from source_type — see table below

class RawItem(BaseModel):
    source_id: str          # joins to SourceRegistryEntry — this is how category reaches every item,
    source_type: str        # with zero per-item inference cost
    fetched_at: datetime
    external_id: str
    raw_payload: dict

class Connector(ABC):
    source_id: str
    source_type: str

    @abstractmethod
    def fetch(self) -> list[RawItem]:
        """Fetch new items since last run. Must be idempotent."""

    @abstractmethod
    def to_canonical_draft(self, raw: RawItem) -> CanonicalDraft:
        """Each connector owns its own raw→canonical conversion (e.g. github_trending
        routes to a repo shape, everything else to trafilatura's article path) —
        the processing pipeline calls this polymorphically and never branches on
        source_type itself."""
```

| Connector | Fetch mechanism | Notes |
|---|---|---|
| RSS pool (Netflix, Jay Alammar, Spotify, SeattleDataGuy, arXiv×3) | `feedparser` on feed URL | Spotify: non-slash URL; arXiv: `export.arxiv.org` |
| Reddit (r/MachineLearning, r/LocalLLaMA, r/mlops) | `feedparser` on `.rss` endpoint + User-Agent header | No PRAW/OAuth — plain feedparser + UA avoids the 403, treated as just another feed source |
| GitHub Trending | Scrape trending page or Search API | Routes to a repo card, not the article path |

Adding a new source (a new category, or a new source within AI Engineering) is registering a `Connector` subclass with a `category` — no pipeline, schema, or digest-logic change.

**Reliability badges** (derived automatically from `source_type`, no per-item override):

| source_type | Badge |
|---|---|
| arxiv | `Peer-reviewed` |
| netflix, spotify | `Primary source` |
| jay_alammar, seattle_data_guy | `Editorial` |
| reddit | `Community` |
| github_trending | `Tool/repo` |

No numeric (0–100) score — a categorical badge is honest about being a coarse heuristic rather than implying false precision. Feeds two things: a per-item trust display, and the source-diversity weighting input to `fct_story_clusters` (§3.6).

### 3.2 Processing Pipeline (per-item, Prefect task)

```python
class ProcessingPipeline:
    def run(self, since: datetime) -> None:
        for raw in bronze.new_rows(since):
            connector = registry.get(raw.source_type)
            draft = connector.to_canonical_draft(raw)         # polymorphic, no branching here
            if draft.is_near_empty:
                flag_extraction_failure(raw)
                continue

            existing = self._find_repost(draft)               # URL + simhash only — literal duplicates
            if existing:
                existing.attach_source(draft.source_id)
                continue

            enrichment = enrich(draft.cleaned_text)            # LLM call, Pydantic-validated
            embedding = embed(draft.title + enrichment.summary) # local sentence-transformer
            silver.insert(draft, enrichment, embedding)

    def _find_repost(self, draft) -> SilverItem | None:
        return silver.query_url_or_simhash(draft.normalized_url, draft.title_simhash)
```

`enrich()` returns a validated `Enrichment(summary: str, key_entities: list[{name, type}], topics: list[str])`; a schema-invalid response is retried once, then flagged — never silently stored as partial/malformed data. This is deliberately the only place per-item dedup happens: it catches literal reposts/syndication only, and does not attempt cross-source corroboration — that's a different phenomenon, handled next.

### 3.3 Story Clustering — persistent lifecycle, not recompute-from-scratch

Stories are **persistent entities with an open/closed lifecycle**, not recomputed fresh from a fixed window every run. This is what lets a story keep accumulating coverage over its actual lifespan (days for a fast-moving release, weeks for a slower incident) instead of being artificially bounded by a fixed clustering window.

```python
class StoryClusteringJob:
    def run(self) -> None:
        new_items = silver.items_since_last_run()
        open_stories = gold.story_clusters.where(status="open")   # tens to low hundreds, not full history

        for item in new_items:
            match = self._find_matching_story(item, new_items, open_stories)
            if match:
                match.attach(item)
            else:
                gold.story_clusters.create(seed_item=item, status="open")

        close_after = pipeline_config.get("story_close_after_days")   # configurable, see below
        gold.story_clusters.where(
            status="open", last_item_at__older_than=close_after
        ).update(status="closed")

    def _find_matching_story(self, item, batch, open_stories) -> StoryCluster | None:
        # 1. entity overlap against other items in today's batch (intra-batch grouping)
        # 2. entity overlap against open stories' entity sets (primary signal)
        # 3. embedding cosine similarity as secondary confirmation, threshold 0.75
        ...
```

**Story-close window is configurable, not hardcoded.** An earlier 30-day default was flagged as too short — some stories (a slow-burn incident, a benchmark controversy resurfacing weeks later) legitimately extend past a month. Default is now **60 days**, read from `pipeline_config.story_close_after_days`, changeable without a code deploy. Once closed, a story stops accepting new matches — a genuinely resurrected story starts a new one rather than reopening an old one, favoring occasional missed reunification over the more common failure mode of false-positive merges against stale context — but its historical record stays fully queryable for trend rollups regardless of open/closed state.

**Windowed trend (week/month/3-month) is a rollup, not a re-clustering.** Once item→story membership is persistent with timestamps, "trending in the last N days" is a parameterized `COUNT(DISTINCT source) WHERE item.published_at > now() - interval` slice in a single dbt model (`fct_story_trend_windows`, §3.6) — adding a fourth window is a config change, not new pipeline work. Don't add a window without a concrete consumer for it (a specific digest section or dashboard view) — the mechanism being cheap to extend isn't a reason to extend it speculatively.

### 3.4 Topic System — two separate mechanisms, kept separate in schema, reconciled only at read time

Two genuinely different extraction paths, answering different questions, **deliberately not merged into one table** — they have different grains and different failure modes, and mixing them would erase which mechanism produced a given tag:

```python
class TopicRegistryEntry(BaseModel):
    id: UUID
    canonical_name: str
    category: str                  # inherited from the category of contributing items/stories
    status: str                    # "proposed" | "active" | "rejected" | "merged"
    merged_into_id: UUID | None    # alias target when status == "merged" — resolved at query time,
                                    # never by rewriting historical tag rows
    origin: str                    # "llm_fast_path" | "discovery" | "user_created"
    created_at: datetime

class ItemTopicLLM(BaseModel):     # fast path — item-level, from per-item enrichment
    item_id: UUID
    topic_id: UUID
    confidence: float | None
    tagged_at: datetime

class StoryTopicDiscovered(BaseModel):   # discovery path — story-level, from periodic clustering
    story_id: UUID
    topic_id: UUID
    cluster_score: float | None
    discovered_at: datetime

class UserTopicOverride(BaseModel):      # manual correction — additive fact, same pattern as mute/save
    item_id: UUID
    topic_id: UUID
    action: str                    # "add" | "remove"
    edited_at: datetime
```

**Fast path** (`item_topics_llm`): part of the per-item enrichment call (§2.4/§3.2) — cheap, immediate, handles anything with an existing name. Runs on the item grain because every item gets enriched regardless of story membership. Structurally, this is a labeling mechanism — it can only assign a name that already exists or that the model itself thinks to propose; it cannot notice a pattern across many items that nobody has named yet.

**Discovery path** (`story_topics_discovered`): a weekly Prefect flow, deliberately separate from the daily pipeline, because it needs a batch of recent stories to find patterns in, not one item at a time:

```python
class TopicDiscoveryJob:
    def run(self, window_days: int = 90) -> None:
        stories = gold.story_clusters.recent(window_days)
        embeddings = [s.representative_embedding for s in stories]
        clusters = hdbscan_cluster(embeddings)             # unsupervised, story-level, not item-level
        for cluster in clusters:
            name = llm_propose_topic_name(cluster.stories)   # checked against active topic_registry first
            topic = topic_registry.get_or_create(name, status="proposed", origin="discovery")
            for story in cluster.stories:
                gold.story_topics_discovered.upsert(story.id, topic.id)
```

Runs on the **story** grain (not raw items) deliberately — stories are already deduplicated, consolidated units, so clustering them is less noisy and more semantically meaningful for "is a new theme emerging" than clustering raw articles would be.

**Any new topic name, from either path, enters `topic_registry` with `status="proposed"`** — reusing an existing *active* topic is automatic and silent; minting a new one always needs confirmation (§3.5). One consistent rule across both mechanisms, not two different approval policies.

**Resolved view** (`fct_item_topics_resolved`, dbt model): the only thing search, rollups, and the digest ever read. Unions `item_topics_llm` + topics inherited via story membership from `story_topics_discovered`, filters to `topic_registry.status = 'active'` (resolving `merged_into_id` chains to their canonical topic), then applies `user_topic_overrides` (add/remove) as the final, highest-precedence layer. The three raw input tables are never mutated to fix a bad tag — corrections are new rows in `user_topic_overrides`, exactly the same discipline used for mute/save and for bronze/silver immutability generally.

### 3.5 Topic Review & Confirmation Workflow

Every `status="proposed"` topic (from either mechanism) needs Alex's confirmation before it affects anything downstream — a bad auto-added topic silently pollutes every rollup it touches, and catching it later costs far more than a lightweight upfront confirm. Discovery-path proposals in particular are expected to sometimes be noise, not exceptional failures — unsupervised clustering on a corpus this size will occasionally surface a cluster that isn't a coherent topic; reject is a normal, frequent outcome here, not a rare override.

- **Batched, not real-time.** Proposals accumulate and are reviewed weekly (a dashboard page `/topics/pending`, or a `/review_topics` Telegram command) — never interrupting the daily digest with a per-item approval prompt.
- **Confirm** → `status="active"`; now visible everywhere (resolved view, search, trending topics).
- **Reject** → `status="rejected"`; excluded from the resolved view. Underlying `story_topics_discovered`/`item_topics_llm` rows are untouched (audit trail preserved), just filtered out at read time.
- **Merge** (Alex judges a proposal is a duplicate of an existing active topic, e.g. "Model Context Protocol" vs. an existing "MCP") → `status="merged"`, `merged_into_id` set. Historical tag rows are never rewritten; alias resolution happens in `fct_item_topics_resolved` at query time.
- **Direct item-level edit**: on the dashboard, Alex can add/remove a topic on a specific item if a tag looks wrong — writes to `user_topic_overrides`, same additive pattern as everything else user-initiated.

### 3.6 dbt Models

| Model | Grain | Reads | Purpose |
|---|---|---|---|
| `stg_items` | item | `silver.items` | Staging/typing layer |
| `dim_source_registry` | source | static seed | Reliability badge + category |
| `fct_item_topics_resolved` | item × topic | `item_topics_llm`, `story_topics_discovered`, `topic_registry`, `user_topic_overrides` | The single read path for topics — resolves fast-path + discovery + overrides + merge-aliasing, filtered to `status='active'` |
| `fct_story_clusters` | story | `gold.story_clusters`, `stg_items`, `dim_source_registry` | Distinct-source-count, source-diversity weight, open/closed status |
| `fct_story_trend_windows` | story × window | `fct_story_clusters` | Parameterized week/month/3-month distinct-source-count slices |
| `fct_topic_monthly_counts` | topic × month | `fct_item_topics_resolved` | Long-horizon topic time series |
| `fct_digest_trending` | story | `fct_story_clusters`, `gold.engagement_events` | Open stories, ≥2 distinct sources, not yet sent |
| `fct_digest_new` | item | `stg_items`, `fct_story_clusters`, `gold.engagement_events` | Fallback: items not in a qualifying story, not yet sent |
| `fct_topic_affinity` (Phase 2) | topic | `fct_item_topics_resolved`, `gold.engagement_events` | Save-rate vs. base rate |

Every model has dbt tests (`not_null`, `unique` on grain, `accepted_values` on status/type columns), including: `fct_item_topics_resolved` never surfaces a topic whose registry status isn't `active` (the concrete guardrail against an unconfirmed proposal leaking into the digest), and a merge-chain-cycle check (topic A merged into B merged into A) on `topic_registry`.

### 3.7 Digest Builder — pure presentation, no scoring

```python
class DigestBuilder:
    def build(self, user_prefs: UserPrefs) -> list[DigestCard]:
        trending = gold.fct_digest_trending.where(not_muted(user_prefs))
        for_you = gold.fct_topic_affinity_matches(user_prefs) if affinity_ready() else []   # Phase 2
        new = gold.fct_digest_new.where(not_muted(user_prefs))

        cards = self._to_cards(trending, section="🔥 Trending") \
              + self._to_cards(for_you, section="⭐ For You") \
              + self._to_cards(new, section="📰 New")

        gold.engagement_events.batch_insert(subject_ids=[c.id for c in cards], event_type="sent")
        return cards
```

Every item shown gets a `sent` event logged — this is what lets `fct_digest_trending`/`fct_digest_new` anti-join against already-shown items, and it's the same `engagement_events` table that captures user-initiated `saved`/`opened`/`muted` events (one append-only log for both system- and user-generated timestamped facts).

### 3.8 Telegram Bot — commands (Phase 1 subset)

```
(scheduled push, no command)  → composed daily digest (Trending + New; For You once Phase 2 ships)
/digest                        → DigestBuilder.build() right now
/trending [source_type]        → gold.fct_digest_trending, optionally filtered
/review_topics                 → surfaces pending topic_registry proposals for confirm/reject/merge
save <item_id> (inline button) → user_prefs.saved.add(item_id); engagement_events(saved)
mute <item_id|source> (inline) → user_prefs.muted_*.add(...); engagement_events(muted)
/saved                          → list currently saved items
```

Muting a whole topic (`user_prefs.muted_topics`) is deliberately not an inline bot action — it's a registry-level edit, handled on the dashboard (§3.9) alongside the other topic-review actions instead.

### 3.9 Web Dashboard

Routes: `GET /items`, `GET /saved`, `GET /clusters/{id}` (coverage view — every item in a story cluster with source + badge), `GET /topics/pending` (review surface for proposed topics — confirm/reject/merge), `POST /items/{id}/save`, `POST /items/{id}/mute`, `POST /topics/{id}/mute`, `POST /items/{id}/topics` (edit an item's resolved topics — writes `user_topic_overrides`). Phase 2 adds `GET /topics/{tag}` (lifecycle time series from `fct_topic_monthly_counts`). All routes read gold tables only — the same query layer the bot uses.

---

## 4. Data Quality & DS Correctness

- **dbt tests** on every model (§3.6) catch schema drift, broken joins, and unexpected nulls before they reach the bot.
- **Pydantic validation** on every LLM structured-output call (enrichment, topic naming) — a malformed response is retried once, then flagged, never silently coerced.
- **Discovery-cluster false positives are expected, not exceptional** (§3.5) — the confirm workflow is the primary defense, not a formality.
- **Alias/merge correctness**: a dbt test asserts no cycles in the `topic_registry` merge chain, since resolution in `fct_item_topics_resolved` assumes a terminating chain.
- **Clustering quality spot-checks**: the lead data scientist periodically pulls a sample of story clusters and topic-discovery proposals via the DuckDB workbench and hand-checks precision against a small labeled set — a recurring review, not a one-time launch gate, since thresholds (§3.3's `0.75`) are expected to need retuning as more sources are added.
- **Topic vocabulary drift** is reviewed the same way — periodically check `topic_registry` for near-duplicate active topics that should be merged.

---

## 5. Data Schemas

```python
# bronze
class RawItemRow(BaseModel):
    id: UUID
    source_id: str
    source_type: str
    fetched_at: datetime
    external_id: str
    raw_payload: dict            # JSONB
    fetch_status: str            # "ok" | "error" | "empty"

# silver
class SilverItem(BaseModel):
    id: UUID
    canonical_url: str
    title: str
    title_simhash: str
    author: str | None
    published_at: datetime
    cleaned_text: str              # full text, internal only
    summary: str                   # from enrichment
    key_entities: list[dict]       # [{name, type}], type ∈ model|tool|company|paper|dataset|benchmark|person
    embedding: list[float]         # local sentence-transformer output
    source_ids: list[str]          # sources attributing this canonical item (repost collapsing)
    item_type: str                 # "article" | "repo"

class ItemTopicLLM(BaseModel):     # fast path
    item_id: UUID
    topic_id: UUID
    confidence: float | None
    tagged_at: datetime

# gold
class SourceRegistryEntry(BaseModel):    # dim_source_registry
    id: str
    domain_or_handle: str
    source_type: str
    category: str
    badge: str

class TopicRegistryEntry(BaseModel):
    id: UUID
    canonical_name: str
    category: str
    status: str                    # "proposed" | "active" | "rejected" | "merged"
    merged_into_id: UUID | None
    origin: str                    # "llm_fast_path" | "discovery" | "user_created"
    created_at: datetime

class StoryCluster(BaseModel):
    id: UUID
    status: str                    # "open" | "closed"
    first_seen_at: datetime
    last_item_at: datetime
    representative_embedding: list[float]
    distinct_source_count: int

class StoryTopicDiscovered(BaseModel):   # discovery path
    story_id: UUID
    topic_id: UUID
    cluster_score: float | None
    discovered_at: datetime

class UserTopicOverride(BaseModel):      # manual correction, additive
    item_id: UUID
    topic_id: UUID
    action: str                    # "add" | "remove"
    edited_at: datetime

class PipelineConfig(BaseModel):       # tiny key/value table — tunables, not hardcoded
    key: str                           # e.g. "story_close_after_days"
    value: str

class UserPrefs(BaseModel):
    muted_sources: set[str]
    muted_topics: set[str]
    saved_item_ids: set[UUID]

class EngagementEvent(BaseModel):
    id: UUID
    subject_type: str               # "item" | "cluster"
    subject_id: UUID
    event_type: str                 # "sent" | "opened" | "saved" | "muted" | "ignored"
    occurred_at: datetime
```

---

## 6. Performance & Observability

### Target SLAs
- Ingestion (all connectors): < 5 minutes per run.
- Processing per item (extraction + enrichment call + embedding): < 5 seconds (dominated by the LLM call).
- Story clustering per run: bounded by open-story count (tens to low hundreds), not corpus size — < 15 seconds regardless of how much history accumulates.
- Topic discovery run (weekly, HDBSCAN over ~90 days of story embeddings): < 2 minutes — offline, non-blocking to the daily pipeline.
- dbt run: < 1 minute at this row count.
- Digest generation: < 5 seconds.

### Metrics (Prefect UI + light logging, no dedicated observability stack per §2.8)
- Fetch success rate per connector.
- Repost-dedup rate (canonical items / raw items).
- Extraction/enrichment failure rate — leading indicator of a source's layout changing or an LLM schema-validation regression.
- dbt test pass rate per run.
- Story cluster count and average distinct-source-count — sanity-checks whether the matching threshold needs retuning.
- **Proposal-to-confirmation rate** per topic-discovery run — a high reject rate is the leading signal that the clustering threshold needs retuning, surfaced the same way extraction-failure rate flags a source's layout changing.

---

## 7. Deployment

`docker-compose.yml` services: `postgres`, `prefect-server`, `prefect-worker` (runs the ingest/process/cluster/topic-discovery/dbt/digest flows on schedule), `bot`, `dashboard`, optionally `llama-server`. Single host. No Kubernetes, no managed warehouse — see §2.7/§2.8.

---

## 8. Implementation Checklist

- [ ] Define `RawItem`/`Connector` interface with polymorphic `to_canonical_draft`; implement feedparser pool (4 blogs + 3 arXiv categories)
- [ ] Implement Reddit connector (feedparser + User-Agent, no PRAW)
- [ ] Implement GitHub Trending connector (repo card path)
- [ ] Register each Phase 1 source with `category="AI Engineering"` in `source_registry`
- [ ] Set up Postgres with `bronze`/`silver`/`gold` schemas
- [ ] Implement processing pipeline: trafilatura extraction, repost dedup (URL+simhash), enrichment (LLM call + Pydantic validation, typed `key_entities`, fast-path topics), embedding
- [ ] `pipeline_config` table; wire `story_close_after_days` (default 60) into the clustering job
- [ ] Implement `StoryClusteringJob`: incremental matching against today's batch + open stories only; close-after-inactivity logic
- [ ] `topic_registry` + `item_topics_llm` + `story_topics_discovered` + `user_topic_overrides` tables
- [ ] Implement `TopicDiscoveryJob` (weekly): story-level embeddings, HDBSCAN, LLM cluster naming, writes `status="proposed"`
- [ ] Set up dbt project: `stg_items`, `dim_source_registry`, `fct_item_topics_resolved`, `fct_story_clusters`, `fct_story_trend_windows`, `fct_topic_monthly_counts`, `fct_digest_trending`, `fct_digest_new`, with tests on each including the merge-chain-cycle test
- [ ] Implement `DigestBuilder` as pure gold-table assembly (no scoring logic)
- [ ] Implement Telegram bot: scheduled push, `/digest`, `/trending`, `/review_topics`, save/mute, `/saved`
- [ ] Implement web dashboard: browse/save/mute, coverage view (`/clusters/{id}`), topic review (`/topics/pending`), item topic-edit action
- [ ] Wire Prefect flows: ingest (hourly) → process → cluster → dbt run → digest (daily); topic discovery (weekly)
- [ ] Set up DuckDB workbench (postgres_scanner attach) for DS spot-checks
- [ ] Docker Compose for local deployment
- [ ] Backfill run before day 1 for non-empty first digest

---

## 9. Phase 2 Follow-ups (not blocking Phase 1, tracked so they aren't lost)

- `fct_topic_affinity` dbt model + "⭐ For You" digest section, once enough `engagement_events` history exists.
- Topic lifecycle view and co-occurrence in the dashboard (data collection starts Phase 1; the *view* is Phase 2 per the cold-start reasoning in the requirements brief §6.2).
- Author-level follow, exploration nudges, source lead/lag analysis, coverage-gap flagging, sentiment (requirements brief §6.4).
- Source health alerting (deferred per requirements brief US-F1) — revisit once there's operational history to justify the added surface.

---

## 10. DS Methodology — Per-Stage Detail

§§2–3 establish *what* each ML-bearing stage does and *which tools* it uses. This section is the *how* underneath each one — concrete algorithms, parameters, and validation approach — scoped deliberately against this project's actual constraints (tiny volume, single-user, one or two maintainers). Every threshold named below is a starting point to validate against real data, not a constant to hardcode and forget.

### 10.1 Enrichment (§3.2) — extraction methodology

- **Structured extraction via tool-calling, not free-text-then-parse.** Use function-calling against a strict JSON schema so the model's output is constrained to valid structure at generation time, rather than relying on a regex/parser to recover from malformed free text after the fact.
- **Entity normalization stays lightweight — not a parallel registry.** The same real-world entity gets written inconsistently ("GLM-5.2" vs. "GLM 5.2"), which would break exact-match entity overlap in story clustering (§10.4). The fix is a normalization pass (lowercase, strip punctuation/whitespace) plus fuzzy matching (e.g. Jaro-Winkler) applied *at comparison time* — deliberately **not** a full alias-registry-with-confirmation-workflow like the topic registry. Topics get that workflow because Alex directly reviews and edits them; entities are purely an internal matching signal nobody reviews directly, and mirroring the topic workflow here would be maintenance overhead disproportionate to the problem.
- **Entity weighting: fixed type-weight schedule first, corpus-wide IDF only if needed.** Not all entity matches are equally informative — two items both mentioning "OpenAI" is weak evidence of the same story; both mentioning "GLM-5.2" is strong evidence. Phase 1 default: a fixed weight schedule biasing `model`/`paper`/`dataset`/`benchmark` types above `company`/`person` types. A more adaptive corpus-wide inverse-frequency weighting is a real refinement, but it requires maintaining a live entity-frequency table — reach for it only if the fixed schedule demonstrably produces bad matches, not as a Phase 1 requirement.
- **LLM-reported confidence scores are not calibrated probabilities.** If `confidence` fields are ever used as a filter threshold, that threshold must be chosen against a hand-labeled sample — LLMs are well-documented to be overconfident, and a stated 0.8 does not reliably mean 80% correct.
- **Summary faithfulness is a periodic sampled check, not a per-item pipeline addition.** Adding a second LLM call on every item to judge faithfulness would double per-item cost and latency for a signal nobody's acting on in real time. Instead: a monthly sampled batch check (~20-30 items) using a cheap LLM-as-judge call against the source text, flagging likely-unfaithful summaries for human review — same cadence and mechanism as the clustering spot-checks (§10.4).

### 10.2 Embeddings (§2.5) — model and representation choices

- **Validate the embedding model against this domain before committing, don't pick one off a leaderboard.** General-purpose sentence-transformer benchmarks don't guarantee transfer to AI/ML technical text. Before implementation: construct ~20-30 pairs from the actual seed sources ("should cluster" / "should not cluster") and confirm the candidate model (`all-MiniLM-L6-v2` vs. e.g. `bge-small-en-v1.5`) separates them with a reasonable margin. This is a one-time pre-implementation task, not ongoing overhead.
- **Embed title + summary, not full text.** MiniLM-class models have an effective context of roughly 256 tokens; full articles would truncate unpredictably. The enrichment summary is already a distilled "aboutness" signal — embedding it directly is more reliable than embedding truncated raw text.
- **Story representative embedding is a running centroid, updated on every attach**, not a frozen snapshot of the seed item: `new_centroid = old_centroid * (n / (n+1)) + new_embedding * (1 / (n+1))`. Cheap (O(1) per update), and necessary — a story's embedding should reflect all its coverage, not just how it started.

### 10.3 Repost Dedup (§3.2) — simhash specifics

- Shingle the title into 3-4 word n-grams, hash to a 64-bit fingerprint via the standard weighted-majority-bit construction, flag near-duplicates at Hamming distance ≤3 — but validate this distance against real repost/non-repost title pairs from the actual sources rather than assuming the textbook default transfers.
- **Fallback for short/generic titles.** Titles like "Update" or "New Release" carry little shingle-able signal on their own; when a title is very short, fall back to shingling the first ~100 characters of body text (or comparing URL path segments) rather than relying on a weak title-only fingerprint.
- **Repost-dedup recall directly affects corroboration correctness, not just tidiness** — a syndicated repost that slips past dedup will likely still get grouped into the right story by entity/embedding matching (§10.4), but it inflates that story's `distinct_source_count` by counting one piece of content as two independent sources. Repost-dedup quality is a direct input to whether the trending signal is honest, not merely a cleanliness concern.

### 10.4 Story Clustering (§3.3) — matching rule and evaluation

- **Concrete matching rule**: a candidate match requires *either* (a) weighted entity overlap above a threshold **and** embedding cosine similarity above 0.75, *or* (b) an exact match on a highly specific entity (a model/paper/dataset name) with a relaxed embedding bar (starting point ~0.6-0.65). Both threshold values are starting points to validate, not final answers — see the evaluation approach below.
- **Optimize for precision over recall, but state the tradeoff honestly.** The two error types aren't equivalent, but neither is free: a missed merge splits a real story into quiet singletons, which means it never surfaces in "🔥 Trending" at all — a real, if quiet, product cost, not a "benign" one. A false merge actively asserts that unrelated stories are the same event, which is a more actively misleading failure than an absent signal. Given that asymmetry, every threshold here should be tuned to minimize false merges even at some cost to recall — but "we'll miss some trending stories sometimes" should be an accepted, named tradeoff, not treated as costless.
- **Build one labeled evaluation set first, not several at once.** Story clustering is the highest-stakes ML component (it feeds the trending signal directly) and the one with an explicit precision-over-recall requirement — so it's where a real evaluation set pays for itself first. Monthly, sample ~30-50 item pairs, hand-label "same story / different story," and compute precision/recall of the current thresholds against that set; retune thresholds against this set, not by intuition. Extend the same discipline to topic-cluster coherence, entity-extraction spot checks, or summary faithfulness *only if* a specific stage is later suspected of underperforming — maintaining all four in parallel from day one is a real ongoing labeling burden disproportionate to a one- or two-person team.

### 10.5 Topic Discovery (§3.4) — clustering pipeline and a coverage gap

- **UMAP dimensionality reduction before HDBSCAN, not raw HDBSCAN on embeddings.** HDBSCAN's density-based approach degrades in high dimensions; the standard pipeline (the same one BERTopic uses) reduces the 384-dim embeddings to roughly 5-15 dimensions via UMAP first, preserving local neighborhood structure, then clusters. This adds two small, local Python dependencies (`umap-learn`, `hdbscan`) — libraries, not new infrastructure, consistent with everything else in §2.
- **Why HDBSCAN specifically**: the number of emerging topics is unknown and shouldn't be fixed in advance (unlike k-means), and it natively leaves ambiguous stories as unclustered "noise" rather than forcing every point into some cluster — important given most stories at any time won't belong to an emerging topic.
- **`min_cluster_size` starts conservative.** Reviewing proposals is a human bottleneck (weekly, one person), and low-quality proposals cause real reviewer fatigue — bias initial tuning toward fewer, higher-confidence proposals, loosening only if a periodic look at the "noise" bucket shows genuine emerging topics being missed.
- **Naming methodology**: feed the LLM the 5 stories closest to each cluster's centroid (not all members, which could be dozens and dilute the signal), asking for a name plus an explicit duplicate check against the active topic list.
- **Track rejection *reasons*, not just the reject rate.** "Not a coherent topic" points at retuning `min_cluster_size` or the UMAP dimensionality; "duplicate of an existing topic" points at improving the fast-path's reuse-preference (§10.6) instead — conflating these into one reject-rate number tells you something's off but not what to fix.
- **Coverage gap: the weekly 90-day rolling window can miss slow-building themes.** A theme that accumulates gradually over 4-6 months might never have enough stories within any single 90-day slice to cross `min_cluster_size`, even though it's genuinely significant in aggregate — the near-term scan can't see this by construction. Mitigation: a secondary, quarterly discovery pass over a trailing 12-month window, run alongside (not instead of) the weekly scan, specifically to catch slower-building themes the fast pass structurally misses.

### 10.6 Fast-Path Topic Tagging (§3.4) — retrieval, not a full registry dump

Once the active topic registry grows past 50-200 entries, listing all of them in every enrichment prompt is both wasteful and risks loose matching. Instead: maintain a representative embedding per active topic (a centroid of its tagged items, updated incrementally the same way story centroids are), retrieve the top-K most similar existing topics to the new item's embedding, and show only those as candidates in the prompt plus an explicit escape hatch to propose a new one — retrieval-augmented tagging, more accurate and more scalable than matching against the full list every time.

### 10.7 Reliability Tiering (§3.1) — an empirical sanity check, not a model

Stays a static, rule-based heuristic by design — no learned model is justified at this scale. Once engagement events accumulate, a periodic sanity check is worth doing: does Alex's save-rate roughly track tier as expected (higher tiers shouldn't systematically underperform lower ones)? A persistent, large outlier is a signal to reconsider that *specific source's* tier assignment manually — this stays a human judgment call, not an automated adjustment.

### 10.8 Trend Rollups (§3.3, §3.6) — rate normalization and velocity smoothing

- **Compare rates, not raw counts, across periods.** A topic's raw monthly mention count conflates genuine interest change with total ingestion volume change (adding a new source mid-year inflates every topic's raw count). Cross-period comparisons should use mentions ÷ total items that period, not an absolute count.
- **Velocity needs a floor or smoothing, or it's mostly noise.** Going from 2→5 mentions is a "150% increase" that's almost entirely small-number randomness. Before computing week-over-week velocity for the Phase 2 quadrant classification, require a minimum absolute count (an empirically-chosen floor, not a guessed one) or smooth with an EWMA — otherwise the "rising" quadrant will mostly reflect noise in sparse topics rather than real signal.

### 10.9 Topic Affinity (Phase 2, §3.6) — shrinkage, not a raw ratio

A raw save-rate vs. corpus base-rate ratio is too noisy at low sample sizes — a topic shown 5 times with 2 saves gives a raw affinity of 40% on essentially no evidence. Use a shrinkage estimator instead: `affinity = (saves + k × base_rate) / (shown + k)`, with a starting prior strength `k ≈ 10` (a deliberate, revisitable default, not a derived constant) — this regresses thin-data topics toward the corpus base rate instead of letting a handful of data points swing the score to 0% or 100%, and should be revisited once real engagement history exists to check whether `k` is well-calibrated.
