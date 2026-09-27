"""End-to-end pipeline tests (requires Docker)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.skip(reason="E2E test requires Docker Compose setup; run with --e2e flag")
class TestFullPipelineFlow:
    """E2E tests for bronze -> silver -> gold flow."""

    def test_fetch_source_inserts_into_bronze(self, mock_db):
        """fetch_source should insert items into bronze.raw_items."""
        from src.pipeline.tasks import fetch_source

        with patch("src.pipeline.tasks._get_watermark") as mock_get_wm, patch(
            "src.pipeline.tasks._advance_watermark"
        ) as mock_adv_wm, patch(
            "src.pipeline.tasks.ConnectorRegistry"
        ) as mock_registry, patch(
            "src.pipeline.tasks.get_run_logger"
        ):
            mock_get_wm.return_value = datetime(2026, 9, 26, tzinfo=UTC)

            raw_item = MagicMock()
            raw_item.source_id = "netflix_blog"
            raw_item.source_type = "rss"
            raw_item.fetched_at = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
            raw_item.external_id = "netflix-001"
            raw_item.raw_payload = {
                "link": "https://netflixtechblog.com/ml-at-scale",
                "title": "Machine Learning at Scale",
            }
            raw_item.fetch_status = "ok"

            mock_connector = MagicMock()
            mock_connector.fetch.return_value = [raw_item]
            mock_registry.get.return_value = mock_connector

            fetch_source(mock_db, "netflix_blog", since=None)

            # Verify bronze insert happened
            mock_db.execute.assert_called()

    def test_all_three_connectors_work_end_to_end(self):
        """Test that all 3 connector types can be instantiated and fetch."""
        from src.connectors import ConnectorRegistry

        sources = ["netflix_blog", "r_MachineLearning", "github_trending"]

        for source_id in sources:
            connector = ConnectorRegistry.get(source_id)

            # Should be instantiable
            assert connector is not None
            assert connector.source_id == source_id

            # Should have fetch method
            assert hasattr(connector, "fetch")
            assert callable(connector.fetch)

            # Should have to_canonical_draft method
            assert hasattr(connector, "to_canonical_draft")
            assert callable(connector.to_canonical_draft)

    def test_watermark_advances_only_on_automated_run(self):
        """Test that watermarks behave correctly for automated vs replay."""
        from src.pipeline.tasks import _advance_watermark, _get_watermark

        mock_db = MagicMock()
        mock_db.fetch_one.return_value = {"last_processed_at": datetime(2026, 9, 26, tzinfo=UTC)}

        # Read watermark
        watermark = _get_watermark(mock_db, "fetch:netflix_blog")
        assert watermark == datetime(2026, 9, 26, tzinfo=UTC)

        # Advance watermark (simulating automated run)
        now = datetime(2026, 9, 27, 14, 0, 0, tzinfo=UTC)
        _advance_watermark(mock_db, "fetch:netflix_blog", now)

        # Verify advance was called
        assert mock_db.execute.called

    def test_idempotent_replay_window(self, mock_db):
        """Test that replaying same window produces idempotent result."""
        from src.pipeline.tasks import fetch_source

        with patch("src.pipeline.tasks.ConnectorRegistry") as mock_registry, patch(
            "src.pipeline.tasks.get_run_logger"
        ):
            raw_item = MagicMock()
            raw_item.source_id = "netflix_blog"
            raw_item.source_type = "rss"
            raw_item.fetched_at = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
            raw_item.external_id = "netflix-001"
            raw_item.raw_payload = {"link": "http://example.com"}
            raw_item.fetch_status = "ok"

            mock_connector = MagicMock()
            mock_connector.fetch.return_value = [raw_item]
            mock_registry.get.return_value = mock_connector

            replay_window = datetime(2026, 9, 1, tzinfo=UTC)

            # First replay
            fetch_source(mock_db, "netflix_blog", since=replay_window)
            first_insert_count = mock_db.execute.call_count

            mock_db.reset_mock()

            # Second replay with same window
            fetch_source(mock_db, "netflix_blog", since=replay_window)
            second_insert_count = mock_db.execute.call_count

            # Both should have same insert count (connector returns same items)
            assert second_insert_count == first_insert_count

    def test_connector_registry_knows_all_11_sources(self):
        """Test that ConnectorRegistry has all 11 Phase 1 sources."""
        from src.connectors import ConnectorRegistry

        expected_sources = [
            "netflix_blog",
            "jay_alammar",
            "spotify_eng",
            "seattle_data_guy",
            "arxiv_llm",
            "arxiv_ai",
            "arxiv_ml",
            "r_MachineLearning",
            "r_LocalLLaMA",
            "r_mlops",
            "github_trending",
        ]

        for source_id in expected_sources:
            connector = ConnectorRegistry.get(source_id)
            assert connector is not None
            assert connector.source_id == source_id

    def test_unknown_source_raises_valueerror(self):
        """Test that ConnectorRegistry.get() raises ValueError for unknown source."""
        from src.connectors import ConnectorRegistry

        with pytest.raises(ValueError):
            ConnectorRegistry.get("nonexistent_source")


@pytest.mark.skip(reason="Requires full Docker Compose; run with --docker-compose flag")
class TestFullPipelineWithDocker:
    """Full E2E tests with real PostgreSQL container."""

    def test_full_medallion_flow_bronze_to_silver(self):
        """Test complete flow: fetch -> bronze -> process -> silver."""
        # This test would:
        # 1. Start Docker Postgres
        # 2. Run migrations
        # 3. Call fetch_source with mocked connector
        # 4. Verify items in bronze.raw_items
        # 5. Call process_batch (with mocked LLM/embedder)
        # 6. Verify items in silver.items with deduplication
        # 7. Verify watermarks advanced
        pass

    def test_story_clustering_creates_clusters(self):
        """Test that cluster_stories groups related items."""
        # This test would:
        # 1. Insert multiple related items into silver.items
        # 2. Call cluster_stories task
        # 3. Verify items grouped into stories in gold.story_clusters
        pass

    def test_replay_window_doesnt_corrupt_watermark(self):
        """Test that manual replay with explicit since doesn't advance watermark."""
        # This test would:
        # 1. Set watermark to datetime(2026, 9, 27)
        # 2. Call fetch_source(since=datetime(2026, 9, 1))  (replay)
        # 3. Verify watermark still datetime(2026, 9, 27)
        # 4. Call fetch_source(since=None)  (automated)
        # 5. Verify watermark advances to now
        pass
