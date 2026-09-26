"""Flows only sequence tasks — they own zero business logic. Every task here
is independently callable (they're plain `@task`-decorated functions in
src/pipeline/tasks.py), so "recreate certain data" means: call the one task
that owns it, with an explicit `since`/`window_days`, without running
anything upstream or downstream. A flow is the automated path, not the only path.
"""
from prefect import flow

from src.connectors.base import Connector
from src.pipeline.tasks import cluster_stories, discover_topics, fetch_source, process_batch


@flow
def ingest_flow(db, llm, embedder, connectors: list[Connector]) -> None:
    for connector in connectors:
        fetch_source(db, connector)          # no `since` — reads its own watermark
    process_batch(db, llm, embedder)
    cluster_stories(db)


@flow
def digest_flow(db) -> None:
    from src.gold.repository import DigestBuilder
    from src.gold.repository import GoldRepository  # concrete Postgres impl, not shown here

    builder = DigestBuilder(repo=GoldRepository(db))
    cards = builder.build()
    _send_to_telegram(cards)


@flow
def topic_discovery_weekly(db, llm) -> None:
    discover_topics(db, llm, window_days=90)


@flow
def topic_discovery_quarterly(db, llm) -> None:
    discover_topics(db, llm, window_days=365)


def _send_to_telegram(cards) -> None: ...


# Manual replay, e.g. after a bad clustering threshold change:
#   cluster_stories(db, since=datetime(2026, 8, 1, tzinfo=timezone.utc))
# reprocesses that window's story assignments without touching bronze, silver,
# or the watermark that the automated hourly flow relies on.

SCHEDULES = {
    ingest_flow: "0 * * * *",              # hourly
    digest_flow: "0 8 * * *",              # daily, 08:00
    topic_discovery_weekly: "0 6 * * 1",   # Mondays
    topic_discovery_quarterly: "0 6 1 1,4,7,10 *",  # first of Jan/Apr/Jul/Oct
}
