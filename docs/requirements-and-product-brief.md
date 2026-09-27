# Knowledge & Discovery Tool — Requirements & Product Brief (Phase 1)

**Audience:** Lead Engineer and Lead Data Scientist, joint review before technical design begins.
**Supersedes:** `phase1-product-brief-ai-engineering.md` and `requirements-and-architecture.md` — both are merged, reframed, and updated into this single document; treat those two as historical only.
**Companion doc:** `phase1-technical-design.md` (connector contract in code, pipeline pseudocode, data schemas, tooling decisions). Kept in sync with this brief — see §12 for what changed and why.
**Scope:** Phase 1 MVP, single domain (AI Engineering), single user (Alex), Telegram bot + minimal web dashboard.

---

## 1. What This Tool Actually Is

The original framing was "give Alex a trustworthy daily catch-up." That's still true, but it undersells what's being built. Alex isn't a one-time reader of a feed — over months, this becomes a place Alex keeps returning to for a growing, structured understanding of a fast-moving field. That reframes the product: this is a **personal knowledge/discovery tool**, not a digest bot. It ingests a fixed set of AI engineering sources, and on top of filtering and displaying them, it builds real structure out of them — which developments are validated by more than one independent source right now, which themes have had staying power over months (not just this week), and what Alex personally keeps coming back to, independent of what's popular.

This shift changes what Phase 1 needs to build. Content extraction (topics, key entities, summary) moves from "explicitly out of scope" in the original brief to a **core requirement** — the analytics below depend on it, not just the eventual `/ask` feature. See §12 for a full list of what changed and why.

---

## 2. Persona & Core Jobs-to-be-Done

**Alex, an AI engineer.** Four distinct jobs, not one:

1. *"Give me a short, trustworthy daily catch-up"* — the original core loop. Still the table-stakes job.
2. *"Tell me what's actually happening right now, validated by more than one source"* — distinguishes a real cross-source development (an arXiv paper + several blogs + a Reddit thread all covering the same release) from one enthusiastic post that happened to get upvoted.
3. *"Show me what's had sustained interest over the last few months, not just this week"* — a slower, thematic view ("agent skills" and "MCP" were the story of H1 2026), structurally different from day-to-day trending.
4. *"Learn what I actually care about, even when it's not popular"* — a niche interest shouldn't need to out-compete hype to get surfaced.

Jobs 2–4 didn't exist in the original brief's scope. They're the reason this rewrite exists.

---

## 3. Grounding in Prior Research (retained)

This research from the original `requirements-and-architecture.md` still holds and continues to justify specific design choices below — retained as-is, with notes where this brief's design has since diverged from what was originally borrowed.

| App | What it does | What we borrowed | Status here |
|---|---|---|---|
| **Techmeme** | Clusters coverage of the same story across outlets, ranks by influence/citation count | Corroboration count is a legitimate, cheap trust/trending signal | **Kept**, but see §6.1 — now computed via entity + embedding clustering, not literal-duplicate counting |
| **Ground News** | Shows every story alongside all outlets covering it, flags "blindspots" | The **coverage view** (all sources for one story, at a glance) | **Kept and strengthened** — now backed by real cross-source event clustering (§6.1), not just dedup |
| **Hacker News** | `score = (points-1)/(age+2)^gravity`, no baseline needed | Time-decayed ranking as an alternative to a rolling-baseline trend score | **Retired** — see §12; HN's formula solves a high-volume, continuously-competing, crowd-voted problem this single-user, once-daily, low-volume tool doesn't have |
| **arXiv Sanity / alphaXiv** | Personal library drives similarity recommendations, weekly recap | "More like this" from saves; weekly recap | Personal-library recs remain a Phase 2+ stretch goal (§9); weekly recap is a natural complement to topic-lifecycle tracking (§6.2), also Phase 2 |
| **TLDR AI / Ben's Bites / Import AI** | Dense headline + 1–2 sentence summary + link, no fluff | Validates the digest content shape already planned | **Kept unchanged** |
| **NewsGuard / Ad Fontes / MBFC** | Rate outlets, not articles, against fixed rubrics | Outlet/type-level reliability, not per-article, not a bespoke number | **Kept** — categorical badge from source type (§6.5) |
| **Feedly (Leo)** | Dedups, summarizes, mutes noise; has a dedicated event-type detector (funding/launch/leadership) | Dedup as a first-class pipeline step, not an afterthought | **Kept** — see the repost/corroboration split in §6.1 |

---

## 4. Seed Sources & Ingestion Principles

### 4.1 Flexibility is a first-class requirement, not an afterthought

Alex expects to add sources over time — new blogs, newsletters, possibly other domains' sources later. The ingestion layer must treat "add a source" as a routine, low-effort operation: a new `Connector` implementation, nothing else changes. No source-type-specific branching should leak into the processing pipeline, the schema, or the digest logic. This is a testable requirement (§7, US-A5), not just a design preference.

### 4.2 Phase 1 sources

| Source | Fetch mechanism | Notes |
|---|---|---|
| Netflix Tech Blog | `feedparser` | Standard RSS |
| Jay Alammar's blog | `feedparser` | Standard RSS |
| Spotify Engineering | `feedparser` | Non-slash URL to skip a redirect |
| SeattleDataGuy | `feedparser` | Standard Substack RSS |
| arXiv — cs.LG, cs.CL, cs.AI | `feedparser` | Use `export.arxiv.org` directly (skips a 302) |
| Reddit — r/MachineLearning, r/LocalLLaMA, r/mlops | `feedparser` on `.rss` endpoint, with a browser-style `User-Agent` header | **Decision reversal from the original doc**: no PRAW, no OAuth/API key management. A plain feedparser fetch plus a UA header avoids the 403 and treats Reddit as just another feed source — same `RawItem` contract, no special-cased connector class. Simpler to maintain; accept the tradeoff that this is a fragile, unauthenticated fetch (see §9, source health) |
| GitHub Trending | Scrape trending page or GitHub Search API | Different content type (repo, not article) — routes to a repo card, not the article path |

**Dropped from Phase 1:** Start Data Engineering, and the sitemap-diff connector originally built for it. That source has no RSS/Atom feed, and its only viable ingestion path was a bespoke sitemap-diff-and-trafilatura connector — a one-off shape that didn't pay for itself relative to the other seven sources. The connector architecture (§5) still accommodates adding it back later via a new connector class; it's deferred, not architecturally excluded.

### 4.3 Future source candidates (illustrates the flexibility principle, not committed for Phase 1)

| Source | Why it's worth considering later | Ingestion method |
|---|---|---|
| Hacker News | Free official API, native "points" give a ready-made engagement signal | Firebase API |
| Company/lab blogs (OpenAI, Anthropic, DeepMind, etc.) | Primary-source announcements, highest signal-to-noise for this persona | RSS |
| alphaXiv / Papers with Code trending | Pre-filtered "trending in ML" signal | RSS/API |
| Curated newsletters (Import AI, Ben's Bites) | Free human-curation layer on top of your own | RSS or trafilatura |
| Podcast RSS + show notes | Standard RSS, often has transcripts | RSS |
| Twitter/X | **Not recommended** — paywalled API, ToS-risky scraping; the same discussion surfaces on HN/Reddit anyway | — |

Each of these is "add a Connector subclass" under the architecture in §5 — no redesign implied by adding any of them.

---

## 5. Data Architecture Overview

Full implementation detail lives in `phase1-technical-design.md`. At the requirements level, the two structural commitments that matter for this brief:

- **Medallion layering** (bronze → silver → gold): bronze is immutable raw payloads; silver holds full cleaned text plus everything described in §6 (enrichment, topic tags, cluster membership); gold is the query surface every client reads. Unchanged from the technical design doc.
- **Connector contract**: every source, regardless of fetch mechanism, emits the same `RawItem` shape, and each connector owns its own raw→canonical conversion (rather than the processing pipeline branching on `source_type`). This is what makes §4.1's flexibility requirement actually hold as the source count grows.

What this adds relative to the earliest cron-and-Postgres design, all present in the current technical design doc:
- An **enrichment step** in the processing pipeline (summary + typed key entities + fast-path topic tags per item) — previously deferred, now required (§6).
- A **topic system** split into two separate mechanisms (fast-path LLM tagging, periodic discovery clustering) plus a confirm/edit workflow — required for §6.2.
- A **story_clusters** table with a persistent open/closed lifecycle (event-level grouping across sources, distinct from repost/duplicate collapsing) — required for §6.1.
- An **engagement_events** table (append-only log of save/open/mute/ignore) — required for §6.3, and was cut from an earlier revision of the technical design on the reasonable grounds that nothing read it yet. That reasoning no longer holds now that personalization (§6.3) depends on this history existing from day one — it cannot be reconstructed retroactively.
- A **dbt transformation layer** for every SQL-expressible rollup (badge derivation, cluster stats, windowed trend counts, resolved topics), and **Prefect** for orchestrating the now-multi-stage DAG — see the technical design doc §2 for the full tooling rationale, including what was considered and rejected (vector databases, Airbyte/Meltano, Kubernetes, a dedicated observability stack).

---

## 6. Analytical Capabilities

This section is the substantive change from the original brief. It replaces the single decay-score ranking with a small set of purpose-built mechanisms, each answering one of the jobs in §2.

### 6.0 Category / Topic / Story — the working hierarchy

Three levels of granularity, used consistently across every analytical capability below:

- **Category** (e.g. "AI Engineering", "DevOps") — a static property of the *source*, assigned once at onboarding, not inferred per item. Every Phase 1 source is category "AI Engineering." This makes activating a second domain later (§9) a matter of registering new sources with a different category — no new ML step, no per-item classification cost.
- **Topic** (e.g. "GLM model family", "data quality tools") — a many-to-many tag on items/stories, produced by two distinct mechanisms (§6.2).
- **Story** (e.g. "GLM 5.2 wins benchmark X", "OpenAI/HuggingFace incident") — the finest grain: a specific, time-bounded event that multiple sources may independently cover. Most ingested items (tutorials, opinion pieces, general commentary) will never belong to a multi-source story — that's expected, not a sign anything's broken.

**Modeling approximations, stated so they aren't mistaken for firm rules:** Story↔Topic is many-to-many; Topic↔Category is kept many-to-one (one primary category per topic) purely to keep rollups simple — a topic like "developer tooling" could genuinely span AI Engineering and DevOps, and forcing one primary category will occasionally misclassify. Don't build many-to-many category assignment until that friction actually shows up. Topic granularity itself is a judgment call, not a fixed rule — "specific models" (broad) and "GLM model family" (narrow) are both plausible topics but produce very different rollup behavior (too coarse and trend rollups can't discriminate; too fine and every topic is sparse, noisy data). Both tagging mechanisms in §6.2 should be steered toward topics with at least a handful of items/month at current volume, not left to per-item judgment.

### 6.1 Cross-source story/event clustering — "what's trending right now" (job 2)

**Purpose:** detect that a specific development is being independently covered by multiple sources, and surface that as a validated "this matters right now" signal — not just this week, but tracked as a persistent, ongoing story that can keep accumulating coverage over its natural lifespan.

**Why this needs its own mechanism, distinct from dedup:** the existing repost/duplicate collapsing (URL normalize + title simhash) only catches literal syndication — the same text appearing on a second host. It will not catch an arXiv paper, a Reddit thread, and a blog post independently covering the same underlying event, because none of them repeat each other's words. These are two different phenomena and need two different techniques:

- **Repost/syndication** (unchanged): URL + simhash, inline at ingestion, merges literal duplicates into one silver row.
- **Story clustering** (new): stories are **persistent entities with an open/closed lifecycle**, not recomputed from scratch over a fixed window each run. A new item is matched against today's batch and against every currently *open* story (typically tens to low hundreds at once, not the full history) — using shared named entities/key terms (from enrichment, §6.1.1) as the primary signal, embedding similarity as secondary confirmation. A story closes to new matches after a **configurable** period of inactivity (default 60 days — a fixed 30-day cutoff was too short for slower-burn stories like an ongoing incident or a benchmark controversy that resurfaces weeks later; keep this tunable, not hardcoded). Once closed, its history stays fully queryable for trend rollups. Items are **not merged** into one row (each source's independent write-up is worth keeping); they're tagged with a shared story ID.
- **Trend at multiple horizons (week/month/3-month)** is a rollup over this persistent membership, not three separate clustering runs — once item→story membership with timestamps exists, "how many distinct sources covered this in the last N days" is a parameterized query, so adding or changing a window is cheap.

**What this powers:**
- "🔥 Trending now" digest section: clusters with ≥2 distinct sources active in the window, ordered by distinct-source count.
- **Coverage view** (dashboard): for any cluster, list every contributing item with its source and reliability badge — this is the Ground News-style feature from §3, now backed by real clustering instead of dedup.
- *(Should, cheap once tiering + clustering both exist)* weight the "distinct source count" by source-type diversity, not just raw count — five Reddit threads and (one primary blog + one arXiv paper + three Reddit threads) both count as 5 sources today; the second is a stronger validation signal and should score higher.

#### 6.1.1 Per-item enrichment (the dependency both 6.1 and 6.2 need)

Every canonical item needs, at minimum: a short summary and a small set of typed key entities (name + type — model, tool, company, paper, dataset, benchmark, person). This was originally scoped as an out-of-scope "nice to have" — it's now load-bearing infrastructure for both clustering and tagging, and should be built as part of Phase 1 processing, not deferred. One typed entity field, not two overlapping ones ("entities" vs. "key features/tools") — a single free-text-plus-type extraction is far less prone to inconsistent output than asking the model to draw an arbitrary line between two similar-sounding fields. Method (LLM call per item vs. lighter local NLP) is an open engineering/cost decision — see §13.

### 6.2 Topic tagging, discovery & long-horizon lifecycle — "what's had sustained interest" (job 3)

**Purpose:** answer questions like "what were the high-interest themes in H1 2026" — a coarser, much longer-horizon grouping than event clustering — *and* surface genuinely new/emerging topics before they have an obvious name yet, not just track known ones.

**Two mechanisms, kept deliberately separate — not merged into one tagging step:**

- **Fast path**: per-item LLM tagging (1–3 tags) against the current *active* topic list, part of the same enrichment call as summary/entities (§6.1.1). Cheap, immediate, and it's a labeling mechanism — it only ever assigns a name that already exists or that the model itself thinks to propose. Stored separately from the path below so it's clear which mechanism produced a given tag.
- **Discovery path**: a periodic (weekly) batch job that clusters recent *story*-level embeddings (not raw items — stories are already deduplicated, less noisy) to find groups that don't share an existing tag, then proposes a name for genuinely emergent themes. This is what the fast path structurally cannot do: notice a pattern nobody has named yet. Stored separately from item-level tags, at the story grain.

Both paths write into a shared topic registry, but **every new topic name, from either mechanism, requires confirmation before it's visible anywhere** (digest, search, rollups) — reusing an existing confirmed topic is automatic and silent, minting a new one is not. This isn't optional polish: unsupervised clustering on a corpus this size will sometimes surface a cluster that isn't a coherent topic, and a bad auto-added topic silently pollutes every downstream rollup it touches. Given a single user, a lightweight weekly batch review (not a per-item interruption) is a trivial cost against that failure mode.

**Alex can also edit, not just confirm/reject**: merge a proposed topic into an existing one (handles near-duplicates like "MCP" vs. "Model Context Protocol"), or directly correct an individual item's topic tags from the dashboard if one looks wrong. Corrections are recorded as their own facts layered on top of the computed tags — never by silently rewriting historical extraction output — the same discipline already used for mute/save.

"Trending topic in a date range" becomes a plain `GROUP BY topic, month` query over the reconciled (fast-path + discovery + user-corrected) topic assignments — no fitted statistical model, no retraining cadence, fully interpretable once the mechanism is in place.

**Cold-start caveat, same shape as the original trending design's baseline problem:** a lifecycle curve or "what mattered this quarter" query is only meaningful once enough history has accumulated (a few weeks at minimum, ideally the full quarter being asked about). Build the tagging, discovery, and review mechanism in Phase 1; don't expect a useful lifecycle *view* until Phase 2, once data exists.

**What this powers (Phase 2, once data has accumulated):**
- Topic lifecycle curve (mention-count over time per tag) — is a topic still rising or already past its peak.
- Topic co-occurrence (which tags appear together often) — surfaces emerging combined themes before they'd earn their own tag.
- Rising/established/declining/niche quadrant classification, combining absolute volume with a velocity/acceleration term (mentions this week vs. trailing baseline) — catches a topic accelerating from 2→15 mentions/week as a stronger signal than one flat at 10/week.

### 6.3 Personal affinity tracking — "what Alex actually cares about" (job 4)

**Purpose:** the two mechanisms above are both **global importance estimates** — they say nothing about whether Alex specifically cares. The one input that can fix this is Alex's own behavior (saves, opens, ignores), and it needs to be collected starting Phase 1, even before anything reads it, because historical engagement can't be reconstructed after the fact.

**Approach:** an append-only `engagement_events` log (item_id, event_type, timestamp), written on every save/open/mute action from day one. Once `item_topics` (§6.2) exists alongside enough event history, a simple content-based affinity score — save-rate on topic X versus that topic's base rate in the corpus — is sufficient. No collaborative filtering (meaningless with one user); this is deliberately the smallest model that answers the question.

**What this powers (Phase 2, once both dependencies exist):**
- "⭐ For you" digest section: new items matching topics Alex has a demonstrated higher-than-base-rate save affinity for, independent of whether those topics are globally trending.
- Author/creator-level following, at finer granularity than topic — a specific writer Alex wants surfaced regardless of trending status.
- Occasional, clearly-labeled "outside your usual interests" nudge — a deliberate counterweight to a pure affinity-reinforcing feed becoming a filter bubble.

### 6.4 Extended analytics — later-stage candidates

These follow naturally from the structures above once they're in place, but aren't Phase 1 or Phase 2 commitments — listed so they're captured rather than lost, and so nobody re-derives them from scratch later:

- **Source lead/lag analysis** — does arXiv reliably surface a topic before Reddit picks it up? Identifies which sources are genuinely "early signal" vs. "confirmation."
- **Coverage-gap flagging** — a trending cluster with only community-source members (no primary/editorial coverage) is a different kind of signal ("hype, not yet corroborated") than one with a primary source in it — a qualitative flag alongside the distinct-source count.
- **Novelty/first-mention detection** — flag an entity or topic appearing for the first time ever in the corpus, distinguishing genuinely new concepts from continuations of an existing conversation.
- **Sentiment/stance per topic** — is community reaction to a release enthusiastic or skeptical. Explicitly the heaviest of these — needs a real classifier, more failure-prone than counting — treat as a Phase 3+ stretch, only after the tagging/clustering foundation is stable.

### 6.5 Reliability tiering (retained, role redefined)

Still a static, categorical badge derived automatically from `source_type` — no manual per-source scoring, no false-precision numeric score (0–100 implies a rigor this heuristic doesn't have; a categorical badge is honest about that).

| Badge | source_type examples |
|---|---|
| `Peer-reviewed` | arXiv |
| `Primary source` | Company/lab blogs (Netflix, Spotify) |
| `Editorial` | Independent expert blogs (Jay Alammar, SeattleDataGuy) |
| `Community` | Reddit |
| `Tool/repo` | GitHub Trending (not an editorial claim) |

**What changed:** this no longer feeds a decay-weighted score (there isn't one anymore, see §12). Its role now is (a) a per-item trust display, and (b) an input to the source-diversity weighting in §6.1.

---

## 7. User Stories by Epic

MoSCoW priority for this Phase 1 scope.

### Epic A — Ingestion

**US-A1 (Must).** Pull new posts from RSS blogs (Netflix, Jay Alammar, Spotify, SeattleDataGuy) automatically, on a schedule, without re-emitting already-seen items.

**US-A2 (Must).** Pull new arXiv papers (cs.LG, cs.CL, cs.AI) with title, abstract, authors, link.

**US-A3 (Must).** Pull discussion from r/MachineLearning, r/LocalLLaMA, r/mlops via `feedparser` + a browser-style User-Agent header — no PRAW, no OAuth. A blocked/403 fetch is logged, not silently skipped.

**US-A4 (Should).** Pull trending GitHub repos, displayed as a distinct repo card, not an article card.

**US-A5 (Must, new).** Adding a new source type requires only a new `Connector` implementation — no changes to the processing pipeline's branching logic, schema, or digest logic. *Acceptance:* demonstrate this by adding one new connector (any future candidate from §4.3) with zero edits outside its own connector class.

### Epic B — Processing & Enrichment

**US-B1 (Must).** Every ingested item is reduced to clean readable text via `trafilatura`; near-empty extractions are flagged, not silently stored.

**US-B2 (Must).** Literal reposts/syndication (matching normalized URL or near-identical title) are collapsed into one canonical item with multiple attributed sources. *This is distinct from and does not attempt cross-source corroboration — see US-C1.*

**US-B3 (Must, promoted from originally out-of-scope).** Every canonical item gets a short summary and a small set of extracted key entities/topics at processing time. *Acceptance:* extraction failures are flagged the same way extraction-empty items are (US-B1), not silently dropped — this step is now load-bearing for Epic C, not optional metadata.

**US-B4 (Must).** Every item displays a reliability badge derived automatically from source type (§6.5).

### Epic C — Trending & Topic Analytics

**US-C1 (Must).** Items describing the same underlying development, across different sources, are grouped into a persistent story (entity-overlap primary signal, embedding similarity secondary), matched against today's batch and every currently open story rather than a fixed window. *Acceptance:* a story's distinct-source-count is queryable; a coverage view lists every contributing item with source + badge; a story closes to new matches after a configurable period of inactivity (§6.1).

**US-C2 (Must).** A "trending now" view surfaces clusters with ≥2 distinct sources active in the window, ordered by distinct-source count.

**US-C2a (Should).** Distinct-source count is weighted by source-type diversity, not raw count alone.

**US-C3 (Should).** Topic tags accumulate into a queryable time series (mentions per topic per month), even though a *useful* lifecycle view needs Phase 2's worth of accumulated history (§6.2's cold-start caveat).

**US-C3a (Must, new).** Fast-path (per-item LLM) and discovery-path (periodic story clustering) topic tagging are stored separately, never merged into one mechanism, so it's always traceable which process produced a given tag.

**US-C3b (Must, new).** Any topic new to the registry — from either mechanism — requires Alex's confirmation (weekly batch review, not per-item) before it appears in any digest, search, or rollup.

**US-C3c (Should, new).** Alex can merge a proposed or existing topic into another (handling near-duplicate names), and can directly edit an individual item's topic tags from the dashboard; both are recorded as corrections layered on top of computed tags, never by rewriting the original extraction.

**US-C4 (Could, Phase 2).** Topic lifecycle view (mentions over time per tag).

**US-C5 (Could, Phase 2).** Topic co-occurrence and rising/established/declining/niche quadrant classification.

**US-C6 (Should).** GitHub repo items render as a visibly distinct card type from articles.

### Epic D — Personalization

**US-D1 (Must).** Mute a topic or source; reversible; excluded from future digests.

**US-D2 (Must).** Save an item; retrievable later via dashboard or `/saved`.

**US-D3 (Must, reinstated).** Every save/open/mute/ignore action is written to an append-only engagement event log with a timestamp, starting Phase 1 — even before anything reads it for ranking. *This cannot be retrofitted after the fact; the acceptance criterion is that the log exists and is complete from day one, independent of whether §D4 ships yet.*

**US-D4 (Should, Phase 2, once enough events exist).** A topic-affinity score (save-rate vs. corpus base rate) powers a "for you" digest section.

**US-D5 (Could, Phase 2).** Follow a specific author/creator, independent of topic or trending status.

**US-D6 (Could, Phase 2).** An occasional, clearly-labeled item outside Alex's usual affinity pattern, to counteract filter-bubble reinforcement.

**US-D7 (Should).** A minimal web dashboard for browsing all ingested items and saved items.

### Epic E — Digest & Discovery

**US-E1 (Must).** A daily digest delivered via Telegram at a configured time, composed of sections rather than one flat ranked list: at minimum a "🔥 Trending" section (Epic C) and a "📰 New" catch-all for anything not yet clustered/tagged, so nothing silently disappears while the analytics layer is still accumulating data. A "⭐ For you" section is added once US-D4 ships.

**US-E2 (Must).** Every digest item shows source name, reliability badge, and a working link to the original.

**US-E3 (Should).** `/digest` and `/trending` Telegram commands return current state on demand, independent of the scheduled push.

**US-E4 (Should).** Dashboard coverage view: for a given story cluster, list every contributing item.

**US-E5 (Could, Phase 2).** Dashboard topic-trend view over a selectable date range.

### Epic F — Operational Trust

**US-F1 (Should, deferred).** Source health check (flag a source with zero successful fetches over N days) — deferred past Phase 1 on the same maintainability grounds as the rest of the operational-alerting surface, but recorded here so it isn't lost. Reddit's fragile UA-based fetch (§4.2) is the source most likely to need this first.

**US-F2 (Must).** Fetch success/failure is logged per source at ingestion time regardless of whether an alerting layer exists on top of it yet.

---

## 8. User Flow

### 8.1 Onboarding (one-time)
```
Alex configures seed sources (§4.2)
    → system registers each source, assigns reliability badge from type
    → first ingestion run backfills recent items (day 1 isn't empty)
    → Alex sets digest delivery time
```

### 8.2 Daily core loop
```
Cron: fetch all sources → clean + dedupe (repost only) → enrich (summary/entities/fast-path topics)
    → story clustering job (match against today's batch + open stories, close after configurable inactivity)
    → (weekly) topic discovery job proposes new topics for review
    → Telegram pushes composed digest: 🔥 Trending | ⭐ For you (Phase 2) | 📰 New
    → Alex skims:
        - "save" → engagement_events(save) + user_prefs.saved
        - "mute" → engagement_events(mute) + user_prefs.muted, excluded going forward
        - taps link → engagement_events(open)
        - no action → implicitly "ignored" once the item falls out of the active window
```

### 8.3 On-demand pull (any time)
```
Alex sends /digest or /trending → bot queries current gold-layer state → returns immediately
```

### 8.4 Deeper browsing (dashboard)
```
Alex opens web dashboard → browse ingested/saved items, coverage view for a cluster,
    (Phase 2) topic-trend view over a date range
```

### 8.5 Operational (deferred, silent unless it fires)
```
(Phase 2+) health-check job → source silent N days → flag surfaced to Alex
```

---

## 9. Explicitly Out of Scope for Phase 1

- **Conversational Q&A (`/ask`, `/explain`)** — retrieval + LLM synthesis over the corpus. Distinct feature from the tracking/analytics work in this brief; still a Phase 2+ candidate.
- **Personal-library similarity recommendations** ("more like this," à la arXiv Sanity) — related to but distinct from topic-affinity (§6.3); a Phase 2+ stretch.
- **Multi-domain support** — this brief is AI Engineering only. The taxonomy/tag mechanism in §6.2 is domain-agnostic by construction, but activating a second domain is a deliberate future decision, not a Phase 1 concern.
- **Weekly recap digest** — a natural complement once topic lifecycle tracking (§6.2) exists; Phase 2, not Phase 1.
- **Statistical/unsupervised topic modeling** (LDA, BERTopic) — deliberately not the Phase 1 approach; see §6.2's rationale.
- **Sentiment/stance analysis** — Phase 3+ stretch, see §6.4.
- **Numeric (0–100) reliability scoring** — rejected in favor of the categorical badge (§6.5); implies false precision.
- **Source health alerting** — mechanism recorded (US-F1) but deferred past Phase 1.

---

## 10. Product Management Notes (retained, updated)

- **Two jobs, one backend, separate UX**: "keep up with trends" (frequent, shallow, FOMO-driven) and "understand a topic deeply" (infrequent, intentional) remain different rhythms. The analytics in §6 primarily serve the first job plus a slower thematic view; deep-dive `/ask`-style research remains a separate, later feature — don't let the digest try to double as a research tool.
- **Habit-loop risk unchanged**: trigger (Telegram push) and action (skim) are solid; reward still depends on curation quality, which depends on source selection more than on any scoring sophistication. Investment (save/mute) stays in Phase 1, not deferred — it's cheap and is the reason engagement events (§6.3) need to start logging from day one rather than being bolted on later.
- **Cold-start honesty**: both topic-lifecycle views (§6.2) and personal affinity (§6.3) are statistically meaningless before enough history accumulates — same shape as the original z-score trending's baseline problem. Ship the collection mechanism in Phase 1; be explicit that the *views* built on top of that data are Phase 2, not fake it with too little data in Phase 1.
- **Feedback signal is non-negotiable now, not just "nice to have"**: US-D3's event log isn't only about eventually tuning something — without it, personalization (job 4, the thing that makes this a *personal* tool rather than a generic aggregator) is permanently unreachable, because the history can't be reconstructed after the fact.

---

## 11. Phased Delivery Plan

**Phase 1 (this brief):** 7 sources (§4.2), repost/syndication dedup, per-item enrichment (summary + entities/topics), reliability badges, story clustering + "trending now," topic tagging (storage only, view deferred), mute/save + engagement event logging, composed Telegram digest (Trending + New sections), minimal dashboard with coverage view.

**Phase 2:** Topic lifecycle view, topic co-occurrence, personal affinity scoring + "for you" digest section, weekly recap, author-level follow, exploration nudges, source health alerting, velocity/quadrant classification.

**Phase 3+:** Sentiment/stance, source lead/lag analysis, coverage-gap flagging, conversational `/ask`, personal-library similarity recommendations, multi-domain activation.

---

## 12. Design Evolution Notes (why this looks different from the original two docs)

- **Decay-weighted ranking (HN-style) retired**: it solves "which of thousands of items wins one of 30 continuously-refreshed slots, driven by crowd voting" — none of which describes a single-user, dozens-of-items-a-day, once-daily digest. Replaced by the composed-sections approach in §6/§7 (Epic E), driven by actual signals (cross-source clustering, affinity) rather than a borrowed, untuned formula.
- **Dedup split into two mechanisms**: the original design used one function to catch both literal reposts and cross-source corroboration. Simhash/URL matching can only do the former; the latter needed a separate, entity/embedding-based story-clustering job (§6.1).
- **Topic tagging moved from out-of-scope to core**: the original brief explicitly deferred LLM tagging. The analytics requested in this revision (trending clusters, topic lifecycle, affinity) all depend on it — it's infrastructure now, not a content-classification nice-to-have.
- **Reddit ingestion simplified**: originally recommended PRAW (official API, OAuth). Reversed in favor of `feedparser` + a User-Agent header — less infrastructure, one fewer credential to manage, consistent with the flat connector-contract approach used for every other source, at the accepted cost of a more fragile, unauthenticated fetch.
- **Sitemap-diff connector and Start Data Engineering dropped**: that connector shape was a one-off for a single source with no real feed; not worth the added connector-interface surface area relative to the other seven sources. Deferred, not architecturally excluded — the connector contract still accommodates adding it back.
- **Engagement event logging reinstated**: cut once as apparently-unused, but personalization (job 4) makes it load-bearing — flagged explicitly so it doesn't get cut again for the same reasoning that no longer applies.
- **Category formalized as a hierarchy level, but kept a static source property**: introduced to support "what mattered in AI Engineering vs. DevOps" style questions, but deliberately *not* an LLM classification task — it's assigned once per source at onboarding, costing nothing beyond a column and a join. Scope is unchanged (AI Engineering only, §9); this is a schema decision for when a second category is actually activated, not a signal that's happening sooner than planned.
- **Story clustering changed from a fixed rolling window to a persistent open/closed lifecycle**: a single 1–2 week recompute couldn't represent a story that legitimately develops over a longer, variable span. Stories now persist and accept new matches until a configurable inactivity period elapses (default 60 days) — matching cost stays bounded by the *count of currently open stories*, not by how long the window is or how much history has accumulated.
- **Topic tagging split into two mechanisms, not one**: pure per-item LLM tagging is a labeling mechanism — it can only assign a name that already exists or that the model itself proposes, so it structurally cannot notice an unnamed pattern emerging across many items. A second, periodic discovery mechanism (clustering story-level embeddings) was added specifically to cover that gap, kept in a separate table so provenance is never ambiguous, with every new topic name from either path requiring Alex's confirmation before it affects anything downstream — unconfirmed proposals are expected to sometimes be noise, not a rare failure mode.
