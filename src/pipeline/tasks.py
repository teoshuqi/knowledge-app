"""Every task follows one shape: `since: datetime | None = None`. None means
"since this task's own last successful run" (read from gold.pipeline_watermarks) —
so the scheduled, automated call takes zero arguments. An explicit `since`
is a manual replay: it reprocesses that window without moving the watermark,
so a backfill can never corrupt the automation's forward progress.

Every write is an upsert on a natural key (see sql/schema.sql's UNIQUE
constraints) — that's what makes "re-run this task for any window" safe
rather than "re-run this task and hope it doesn't duplicate data".

One task, one job: fetch, OR process, OR cluster, OR discover. None of these
call each other directly — flows/flows.py wires the order. That's what lets
any single one be re-triggered alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from prefect import get_run_logger, task

from src.connectors import ConnectorRegistry
from src.ml.embedding_client import EmbeddingClient
from src.ml.llm_client import ExtractionFailed, LLMClient
from src.models import Enrichment


class DatabaseConnection(Protocol):
    """Interface that all db objects must match. Implementers: Postgres adapter,
    test fakes, replay tools."""

    def fetch_one(self, sql: str, params: tuple = ()) -> dict | None: ...
    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]: ...
    def execute(self, sql: str, params: tuple = ()) -> None: ...

_WATERMARK_TASKS = ("fetch", "process", "cluster")


def _get_watermark(db: DatabaseConnection, task_name: str) -> datetime:
    row = db.fetch_one(
        "SELECT last_processed_at FROM gold.pipeline_watermarks WHERE task_name = %s",
        (task_name,),
    )
    return row["last_processed_at"] if row else datetime(1970, 1, 1, tzinfo=UTC)


def _advance_watermark(db: DatabaseConnection, task_name: str, up_to: datetime) -> None:
    db.execute(
        """INSERT INTO gold.pipeline_watermarks (task_name, last_processed_at)
           VALUES (%s, %s)
           ON CONFLICT (task_name) DO UPDATE SET last_processed_at = EXCLUDED.last_processed_at""",
        (task_name, up_to),
    )


@task(retries=3, retry_delay_seconds=60)
def fetch_source(db: DatabaseConnection, source_id: str, since: datetime | None = None) -> None:
    """Fetch items from a single source. Upsert into bronze.raw_items with
    watermark tracking. since=None reads watermark; explicit since is a replay.
    """
    logger = get_run_logger()
    is_replay = since is not None
    watermark = since or _get_watermark(db, f"fetch:{source_id}")

    connector = ConnectorRegistry.get(source_id)
    items = connector.fetch(since=watermark)

    inserted = 0
    for raw in items:
        db.execute(
            """INSERT INTO bronze.raw_items
               (source_id, source_type, fetched_at, external_id, raw_payload, fetch_status)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (source_id, external_id) DO NOTHING""",
            (
                raw.source_id,
                raw.source_type,
                raw.fetched_at,
                raw.external_id,
                raw.raw_payload,
                raw.fetch_status,
            ),
        )
        inserted += 1

    if not is_replay:
        _advance_watermark(db, f"fetch:{source_id}", datetime.now(UTC))

    logger.info(
        "fetch_source(%s): %d items fetched, inserted=%d, replay=%s",
        source_id,
        len(items),
        inserted,
        is_replay,
    )


@task(retries=1)
def process_batch(
    db: DatabaseConnection,
    llm: LLMClient,
    embedder: EmbeddingClient,
    since: datetime | None = None,
) -> None:
    """trafilatura extraction -> repost dedup -> enrichment -> embed -> silver insert.
    See technical design §3.2 and §10.1 for the extraction/dedup/enrichment
    methodology itself — this task is the orchestration around it, not the
    algorithm.
    """
    logger = get_run_logger()
    is_replay = since is not None
    watermark = since or _get_watermark(db, "process")

    rows = db.fetch_all(
        "SELECT * FROM bronze.raw_items WHERE fetched_at > %s ORDER BY fetched_at",
        (watermark,),
    )
    for raw in rows:
        draft = _to_canonical_draft(raw)  # per-source, via the connector registry
        if draft.is_near_empty:
            db.execute(
                "UPDATE bronze.raw_items SET fetch_status = 'empty' WHERE id = %s",
                (raw["id"],),
            )
            continue

        existing = db.fetch_one(
            "SELECT id, source_ids FROM silver.items WHERE canonical_url = %s OR title_simhash = %s",
            (draft.canonical_url, _simhash(draft.title)),
        )
        if existing:
            db.execute(
                "UPDATE silver.items SET source_ids = array_append(source_ids, %s) WHERE id = %s",
                (draft.source_id, existing["id"]),
            )
            continue

        try:
            enrichment: Enrichment = llm.extract(_enrichment_prompt(draft), Enrichment)
        except ExtractionFailed:
            logger.warning(
                "enrichment failed for %s, flagging not dropping", draft.canonical_url
            )
            continue
        embedding = embedder.embed([f"{draft.title} {enrichment.summary}"])[0]

        db.execute(
            """INSERT INTO silver.items
               (canonical_url, title, title_simhash, author, published_at, cleaned_text,
                summary, key_entities, embedding, source_ids, item_type)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (canonical_url) DO NOTHING""",
            (
                draft.canonical_url,
                draft.title,
                _simhash(draft.title),
                draft.author,
                draft.published_at,
                draft.cleaned_text,
                enrichment.summary,
                [e.model_dump() for e in enrichment.key_entities],
                embedding,
                [draft.source_id],
                draft.item_type,
            ),
        )

    if not is_replay:
        _advance_watermark(db, "process", datetime.now(UTC))


@task(retries=1)
def cluster_stories(db: DatabaseConnection, since: datetime | None = None) -> None:
    """Matches new items against today's batch + currently open stories only
    (§3.3) — never against full history, so this stays cheap regardless of
    the configurable close window or how much history has accumulated.
    """
    is_replay = since is not None
    watermark = since or _get_watermark(db, "cluster")
    config = _load_config(db)

    new_items = db.fetch_all(
        "SELECT * FROM silver.items WHERE inserted_at > %s", (watermark,)
    )
    open_stories = db.fetch_all(
        "SELECT * FROM gold.story_clusters WHERE status = 'open'"
    )

    for item in new_items:
        match = _find_matching_story(item, open_stories, config)
        if match:
            db.execute(
                """INSERT INTO gold.story_cluster_members (story_id, item_id)
                   VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                (match["id"], item["id"]),
            )
        else:
            db.execute(
                """INSERT INTO gold.story_clusters (status, first_seen_at, last_item_at, representative_embedding, entity_set)
                   VALUES ('open', %s, %s, %s, %s)""",
                (
                    item["published_at"],
                    item["published_at"],
                    item["embedding"],
                    item["key_entities"],
                ),
            )

    close_after_days = int(config.get("story_close_after_days", "7"))
    db.execute(
        """UPDATE gold.story_clusters SET status = 'closed'
           WHERE status = 'open' AND last_item_at < now() - make_interval(days => %s)""",
        (close_after_days,),
    )

    if not is_replay:
        _advance_watermark(db, "cluster", datetime.now(UTC))


@task(retries=1)
def discover_topics(db: DatabaseConnection, llm: LLMClient, window_days: int = 90) -> None:
    """Always a fresh, stateless run over a trailing window from now — not a
    watermark task. Zero-shot-assigns against the *current* active registry
    first (BERTopic), then clusters only the residual. See §10.5 / §2.6.
    Called with window_days=90 on the weekly schedule and window_days=365 on
    the quarterly one — same task, two schedules, no code duplication.
    """
    config = _load_config(db)
    active_topics = db.fetch_all(
        "SELECT id, canonical_name FROM gold.topic_registry WHERE status = 'active'"
    )
    stories = db.fetch_all(
        "SELECT * FROM gold.story_clusters WHERE last_item_at > now() - make_interval(days => %s)",
        (window_days,),
    )
    _run_bertopic_and_upsert(db, llm, active_topics, stories, config)


def _to_canonical_draft(raw):
    # Reconstruct a RawItem from the database row, then delegate to the
    # connector's extraction method (per-source via registry). raw is a dict
    # from bronze.raw_items, keyed by column name.
    from src.models import RawItem

    item = RawItem(
        source_id=raw["source_id"],
        source_type=raw["source_type"],
        fetched_at=raw["fetched_at"],
        external_id=raw["external_id"],
        raw_payload=raw["raw_payload"],
        fetch_status=raw["fetch_status"],
    )
    connector = ConnectorRegistry.get(raw["source_id"])
    return connector.to_canonical_draft(item)


# --- helpers below are algorithm stubs; see technical design §10 for the spec ---


def _simhash(title: str) -> int:
    raise NotImplementedError("_simhash: see technical design §10.3 for spec")


def _enrichment_prompt(draft) -> str:
    raise NotImplementedError("_enrichment_prompt: see LLD §2.2 for spec")


def _find_matching_story(item, open_stories, config):
    raise NotImplementedError("_find_matching_story: see LLD §2.4 for spec")


def _load_config(db: DatabaseConnection) -> dict[str, str]:
    rows = db.fetch_all("SELECT key, value FROM gold.pipeline_config")
    return {r["key"]: r["value"] for r in rows}


def _run_bertopic_and_upsert(db: DatabaseConnection, llm: LLMClient, active_topics, stories, config):
    raise NotImplementedError("_run_bertopic_and_upsert: see LLD §2.5 for spec")
