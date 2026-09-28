# Pipeline Overview — Entrypoints & Flow

**As of:** post Phase 1 ingestion validation (see `HANDOFF.md`)
**Scope:** what actually runs today, not what the design docs describe. Live
re-verified against a rebuilt Docker image and a real testcontainers
Postgres — not the design docs alone.

---

## Summary

Three entrypoints converge on `fetch_source()`, which fans out across three
connector classes into `bronze.raw_items` — the only stage that moves data
end to end (783 rows, 11/11 sources, verified live).

Everything past that point is **wired but stubbed**: `process_batch`,
`cluster_stories`, and `discover_topics` are real `@task`-decorated
functions that get called, and each one immediately hits a helper that
raises `NotImplementedError`. In every case, a working implementation of
that exact helper already exists in a sibling module — `text_utils.py`,
`story_matching.py`, `topic_discovery.py` — it's just never called from
`tasks.py`. Wiring these three call sites is the single highest-leverage
next step toward Phase 2.

Serving doesn't exist yet: `GoldRepository` is a `Protocol` with no Postgres
implementation, and `src/bot/` / `src/dashboard/` aren't there.

---

## Diagram

```mermaid
flowchart TB
    classDef live fill:#1F6F5C22,stroke:#1F6F5C,stroke-width:2px,color:#1B1F26
    classDef stub fill:#A5670E22,stroke:#A5670E,stroke-width:2px,color:#1B1F26
    classDef orphan fill:transparent,stroke:#A5670E,stroke-width:1.5px,stroke-dasharray:4 4,color:#1B1F26
    classDef missing fill:#767D8C11,stroke:#767D8C,stroke-width:2px,stroke-dasharray:4 4,color:#5B6270
    classDef absent fill:transparent,stroke:#767D8C,stroke-width:1.5px,stroke-dasharray:2 3,color:#5B6270

    subgraph entry["Entry points"]
        A1["docker-compose.yml<br/>bootstraps schema + seed"]:::live
        A2["scripts/e2e_test.sh<br/>→ verify_pipeline.py"]:::live
        A3["flows/flows.py: ingest_flow<br/>@flow, scheduled hourly —<br/>never deployed to a worker"]:::stub
    end

    FS["fetch_source()<br/>src/pipeline/tasks.py<br/>watermark-idempotent"]:::live

    A1 --> FS
    A2 -- "calls fetch_source() 11x" --> FS
    A3 -. not deployed .-> FS

    subgraph connectors["src/connectors/"]
        C1["RSSConnector<br/>7 sources"]:::live
        C2["RedditConnector<br/>3 sources"]:::live
        C3["GitHubTrendingConnector<br/>1 source"]:::live
    end

    FS --> C1 & C2 & C3

    BRONZE["bronze.raw_items<br/>783 rows, 11/11 sources"]:::live
    C1 & C2 & C3 --> BRONZE

    BRONZE -. "blocked: _simhash() /<br/>_enrichment_prompt()<br/>raise NotImplementedError" .-> PB

    PB["process_batch()"]:::stub
    PB_IMPL["text_utils.py + enrichment.py<br/>+ ml/llm_client.py<br/>real logic, never called"]:::orphan
    PB -.-> PB_IMPL

    SILVER["silver.items<br/>stays empty"]:::missing
    PB -.-> SILVER

    SILVER -. "blocked: _find_matching_story()<br/>raises NotImplementedError" .-> CS

    CS["cluster_stories()"]:::stub
    CS_IMPL["story_matching.py<br/>entity overlap + cosine sim,<br/>never called"]:::orphan
    CS -.-> CS_IMPL

    STORIES["gold.story_clusters<br/>stays empty"]:::missing
    CS -.-> STORIES

    STORIES -. "blocked: _run_bertopic_and_upsert()<br/>raises NotImplementedError" .-> DT

    DT["discover_topics()"]:::stub
    DT_IMPL["topic_discovery.py<br/>BERTopic + zero-shot naming,<br/>never called"]:::orphan
    DT -.-> DT_IMPL

    TOPICS["gold.topic_registry<br/>stays empty"]:::missing
    DT -.-> TOPICS

    DIGEST["digest_flow()<br/>flows/flows.py"]:::missing
    GR["GoldRepository<br/>Protocol only,<br/>no implementation"]:::missing
    DIGEST -.-> GR

    BOT["src/bot/<br/>absent"]:::absent
    DASH["src/dashboard/<br/>absent"]:::absent
    GR -.-> BOT
    GR -.-> DASH
```

**Legend**
- **Live** (solid teal) — runs, tested, verified against a real Postgres.
- **Stub** (amber) — wired in, but the helper it calls raises `NotImplementedError`.
- **Orphaned implementation** (dashed amber) — the real code the stub needs already exists, unused, in a sibling module.
- **Schema, unreached** (dashed grey) — table exists, stays empty because nothing upstream reaches it.
- **Absent** (dotted grey) — no code at this path yet.

---

## Every stage, exact file

| Stage | Entry / task | File | Status |
|---|---|---|---|
| Bootstrap | `docker compose up` | `docker-compose.yml`, `sql/migrations/001_initial_schema.sql` | **live** |
| Manual verify | `verify_pipeline.py` | `scripts/verify_pipeline.py` | **live** |
| Scheduled ingest | `ingest_flow` | `flows/flows.py` | defined, not deployed to prefect-worker |
| Fetch | `fetch_source()` | `src/pipeline/tasks.py` | **live** |
| Connect | `RSSConnector` / `RedditConnector` / `GitHubTrendingConnector` | `src/connectors/{rss,reddit,github_trending}.py` | **live** |
| Process | `process_batch()` | `src/pipeline/tasks.py` calls stub; real code in `text_utils.py`, `enrichment.py`, `ml/llm_client.py` | stub |
| Cluster | `cluster_stories()` | `src/pipeline/tasks.py` calls stub; real code in `story_matching.py` | stub |
| Discover topics | `discover_topics()` | `src/pipeline/tasks.py` calls stub; real code in `topic_discovery.py` | stub |
| Serve | `digest_flow()`, `GoldRepository` | `flows/flows.py`, `src/gold/repository.py` | Protocol only, no implementation |
| Bot / Dashboard | — | `src/bot/`, `src/dashboard/` | directories don't exist |

---

## Related

- Interactive version (same content, rendered SVG): https://claude.ai/artifact/FPEVbkEiQrdpehBQEZPKQM
- `docs/HANDOFF.md` — what Phase 1 covers and the team handover notes
- `docs/phase1-technical-design.md` §8 — the full Phase 1 MVP checklist (broader scope than what's implemented so far)
