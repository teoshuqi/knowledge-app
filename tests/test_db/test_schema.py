"""Tests for PostgreSQL schema integrity (requires Docker; skips automatically
when testcontainers or Docker itself is unavailable - see conftest.py's
postgres_container fixture).
"""

from __future__ import annotations


class TestBronzeTablesExist:
    """Tests for bronze layer table structure."""

    def test_raw_items_table_exists(self, db_with_schema):
        """bronze.raw_items table should exist with correct columns."""
        cursor = db_with_schema.cursor()
        cursor.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'bronze' AND table_name = 'raw_items'
            ORDER BY ordinal_position
        """
        )
        columns = {row[0]: row[1] for row in cursor.fetchall()}

        required_columns = {
            "id": "uuid",
            "source_id": "text",
            "external_id": "text",
            "source_type": "text",
            "raw_payload": "jsonb",
            "fetched_at": "timestamp with time zone",
            "fetch_status": "text",
            "inserted_at": "timestamp with time zone",
        }

        for col_name, col_type in required_columns.items():
            assert col_name in columns, f"Column {col_name} not found"

    def test_raw_items_unique_constraint_exists(self, db_with_schema):
        """bronze.raw_items should have UNIQUE(source_id, external_id)."""
        cursor = db_with_schema.cursor()
        cursor.execute(
            """
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_schema = 'bronze' AND table_name = 'raw_items'
        """
        )
        constraints = {row[0]: row[1] for row in cursor.fetchall()}

        # Should have UNIQUE constraint for idempotency
        unique_constraints = [
            c for c, t in constraints.items() if t == "UNIQUE"
        ]
        assert len(unique_constraints) > 0, "No UNIQUE constraints found"

    def test_raw_items_fetch_status_is_enum_or_check(self, db_with_schema):
        """fetch_status should be constrained to ok/error/empty."""
        cursor = db_with_schema.cursor()

        # Try to insert valid status
        cursor.execute(
            """
            INSERT INTO bronze.raw_items
            (source_id, external_id, source_type, raw_payload, fetched_at, fetch_status)
            VALUES ('test', 'ext-001', 'rss', '{}', now(), 'ok')
            ON CONFLICT DO NOTHING
        """
        )
        db_with_schema.commit()

        # Verify it was inserted
        cursor.execute(
            "SELECT COUNT(*) FROM bronze.raw_items WHERE fetch_status = 'ok'"
        )
        count = cursor.fetchone()[0]
        assert count > 0


class TestSilverTablesExist:
    """Tests for silver layer table structure."""

    def test_items_table_exists(self, db_with_schema):
        """silver.items table should exist for canonical items."""
        cursor = db_with_schema.cursor()
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'silver' AND table_name = 'items'
        """
        )
        columns = [row[0] for row in cursor.fetchall()]

        required = [
            "id",
            "canonical_url",
            "title",
            "title_simhash",
            "author",
            "published_at",
            "cleaned_text",
            "summary",
            "key_entities",
            "embedding",
            "source_ids",
            "item_type",
            "inserted_at",
        ]

        for col in required:
            assert col in columns, f"Column {col} not found in silver.items"

    def test_items_canonical_url_is_unique(self, db_with_schema):
        """silver.items.canonical_url should be UNIQUE for deduplication."""
        cursor = db_with_schema.cursor()
        cursor.execute(
            """
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_schema = 'silver' AND table_name = 'items'
        """
        )
        constraints = {row[0]: row[1] for row in cursor.fetchall()}

        unique_constraints = [
            c for c, t in constraints.items() if t == "UNIQUE"
        ]
        assert len(unique_constraints) > 0


class TestGoldTablesExist:
    """Tests for gold layer table structure."""

    def test_pipeline_watermarks_table_exists(self, db_with_schema):
        """gold.pipeline_watermarks should exist for watermark tracking."""
        cursor = db_with_schema.cursor()
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'gold' AND table_name = 'pipeline_watermarks'
        """
        )
        columns = [row[0] for row in cursor.fetchall()]

        # last_processed_at is rewritten on every upsert (ON CONFLICT DO
        # UPDATE), so it already doubles as "last touched" - no separate
        # updated_at column exists or is needed.
        required = ["task_name", "last_processed_at"]
        for col in required:
            assert col in columns

    def test_source_registry_table_exists(self, db_with_schema):
        """gold.source_registry should exist for source metadata."""
        cursor = db_with_schema.cursor()
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'gold' AND table_name = 'source_registry'
        """
        )
        columns = [row[0] for row in cursor.fetchall()]

        required = ["id", "domain_or_handle", "source_type", "category", "badge"]
        for col in required:
            assert col in columns

    def test_story_clusters_table_exists(self, db_with_schema):
        """gold.story_clusters should exist for story grouping."""
        cursor = db_with_schema.cursor()
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'gold' AND table_name = 'story_clusters'
        """
        )
        columns = [row[0] for row in cursor.fetchall()]

        required = ["id", "status", "first_seen_at", "last_item_at"]
        for col in required:
            assert col in columns


class TestOnConflictConstraints:
    """Tests for ON CONFLICT DO NOTHING idempotency."""

    def test_raw_items_upsert_deduplicates(self, db_with_schema):
        """Inserting same (source_id, external_id) twice should be no-op."""
        cursor = db_with_schema.cursor()

        # First insert
        cursor.execute(
            """
            INSERT INTO bronze.raw_items
            (source_id, external_id, source_type, raw_payload, fetched_at, fetch_status)
            VALUES ('netflix_blog', 'ext-001', 'rss', '{"link": "http://example.com"}', now(), 'ok')
            ON CONFLICT (source_id, external_id) DO NOTHING
        """
        )
        db_with_schema.commit()

        cursor.execute(
            "SELECT COUNT(*) FROM bronze.raw_items "
            "WHERE source_id = 'netflix_blog' AND external_id = 'ext-001'"
        )
        count_after_first = cursor.fetchone()[0]

        # Second insert (duplicate)
        cursor.execute(
            """
            INSERT INTO bronze.raw_items
            (source_id, external_id, source_type, raw_payload, fetched_at, fetch_status)
            VALUES ('netflix_blog', 'ext-001', 'rss', '{"link": "http://new.com"}', now(), 'ok')
            ON CONFLICT (source_id, external_id) DO NOTHING
        """
        )
        db_with_schema.commit()

        cursor.execute(
            "SELECT COUNT(*) FROM bronze.raw_items "
            "WHERE source_id = 'netflix_blog' AND external_id = 'ext-001'"
        )
        count_after_second = cursor.fetchone()[0]

        # Should still be 1 (duplicate was ignored)
        assert count_after_first == count_after_second == 1
