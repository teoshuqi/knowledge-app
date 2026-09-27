#!/usr/bin/env python3
"""Runs inside the prefect-worker container (same image as production) to
smoke-test the Phase 1 ingestion path against a live Postgres. Reuses the
real fetch_source task and ConnectorRegistry — no separate insert logic to
drift out of sync with production.

Usage: docker compose exec -T prefect-worker python scripts/verify_pipeline.py
"""

from __future__ import annotations

import sys

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.config import get_settings
from src.pipeline.tasks import fetch_source

SOURCES = [
    "netflix_blog", "jay_alammar", "spotify_eng", "seattle_data_guy",
    "arxiv_llm", "arxiv_ai", "arxiv_ml",
    "r_MachineLearning", "r_LocalLLaMA", "r_mlops",
    "github_trending",
]


class DB:
    # ponytail: minimal shim matching the {fetch_one,fetch_all,execute}
    # shape fetch_source already expects — not the real repository (that's
    # S-01's Postgres GoldRepository). Don't grow this; if more than this
    # script needs a db object, build S-01 instead.
    def __init__(self, dsn: str) -> None:
        self.conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    @staticmethod
    def _adapt(params):
        # psycopg3 needs dicts explicitly marked as JSON(B); it won't guess.
        return tuple(Jsonb(p) if isinstance(p, dict) else p for p in params)

    def fetch_one(self, sql, params=()):
        return self.conn.execute(sql, self._adapt(params)).fetchone()

    def fetch_all(self, sql, params=()):
        return self.conn.execute(sql, self._adapt(params)).fetchall()

    def execute(self, sql, params=()):
        self.conn.execute(sql, self._adapt(params))


def check(label: str, ok: bool) -> bool:
    print(f"  {'✓' if ok else '✗'} {label}")
    return ok


def main() -> int:
    db = DB(get_settings().postgres_dsn)
    passed = True

    print("\nschema")
    tables = {
        f"{r['table_schema']}.{r['table_name']}"
        for r in db.fetch_all(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('bronze', 'silver', 'gold')"
        )
    }
    for t in ("bronze.raw_items", "silver.items", "gold.source_registry", "gold.pipeline_watermarks"):
        passed &= check(t, t in tables)

    print("\nsource registry")
    count = db.fetch_one("SELECT count(*) AS n FROM gold.source_registry")["n"]
    passed &= check(f"{count} sources seeded (expect >= {len(SOURCES)})", count >= len(SOURCES))

    print("\ningestion (fetch_source per Phase 1 source)")
    for source_id in SOURCES:
        try:
            fetch_source(db, source_id)
            passed &= check(source_id, True)
        except Exception as e:  # noqa: BLE001 - report and keep going
            passed = check(f"{source_id}: {e}", False)

    print("\nbronze.raw_items")
    rows = db.fetch_all(
        "SELECT source_id, count(*) AS n FROM bronze.raw_items GROUP BY source_id ORDER BY source_id"
    )
    for r in rows:
        print(f"  {r['source_id']}: {r['n']} rows")
    passed &= check("has data", len(rows) > 0)

    print("\nwatermarks")
    marks = db.fetch_all("SELECT task_name, last_processed_at FROM gold.pipeline_watermarks ORDER BY task_name")
    for w in marks:
        print(f"  {w['task_name']}: {w['last_processed_at']}")
    passed &= check("recorded", len(marks) > 0)

    print(f"\n{'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
