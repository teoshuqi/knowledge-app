"""Integration tests for Prefect pipeline tasks."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.tasks import fetch_source


class TestFetchSourceTask:
    """Integration tests for fetch_source task."""

    def test_fetch_source_task_function_integration(self, mock_db, mock_llm):
        """fetch_source.fn() should execute full integration flow."""
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
                "link": "https://netflixtechblog.com/article",
                "title": "Test Article",
            }
            raw_item.fetch_status = "ok"

            mock_connector = MagicMock()
            mock_connector.fetch.return_value = [raw_item]
            mock_registry.get.return_value = mock_connector

            fetch_source(mock_db, "netflix_blog", since=None)

            # Verify connector was instantiated by source_id
            mock_registry.get.assert_called_once_with("netflix_blog")

            # Verify connector.fetch() was called
            assert mock_connector.fetch.called

            # Verify DB insert was called
            assert mock_db.execute.called

            # Verify watermark was advanced
            assert mock_adv_wm.called

    def test_fetch_source_with_multiple_items(self, mock_db):
        """fetch_source should insert multiple items in one call."""
        with patch("src.pipeline.tasks._get_watermark"), patch(
            "src.pipeline.tasks._advance_watermark"
        ), patch("src.pipeline.tasks.ConnectorRegistry") as mock_registry, patch(
            "src.pipeline.tasks.get_run_logger"
        ):
            raw_items = []
            for i in range(5):
                item = MagicMock()
                item.source_id = "netflix_blog"
                item.source_type = "rss"
                item.fetched_at = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
                item.external_id = f"netflix-{i:03d}"
                item.raw_payload = {"link": f"http://example.com/{i}"}
                item.fetch_status = "ok"
                raw_items.append(item)

            mock_connector = MagicMock()
            mock_connector.fetch.return_value = raw_items
            mock_registry.get.return_value = mock_connector

            fetch_source(mock_db, "netflix_blog", since=None)

            # Should call execute 5 times (once per item)
            assert mock_db.execute.call_count == 5

    def test_fetch_source_replay_window_identical_to_previous(self, mock_db):
        """fetch_source(since=X) called twice should be idempotent."""
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

            # First call
            fetch_source(mock_db, "netflix_blog", since=replay_window)
            first_call_count = mock_db.execute.call_count

            # Reset mock
            mock_db.reset_mock()

            # Second call with same window
            fetch_source(mock_db, "netflix_blog", since=replay_window)
            second_call_count = mock_db.execute.call_count

            # Both should insert same items (connector returns same data)
            assert second_call_count == first_call_count

    def test_fetch_source_uses_string_source_id_not_connector_object(
        self, mock_db
    ):
        """fetch_source should accept source_id string, instantiate connector internally."""
        with patch("src.pipeline.tasks._get_watermark"), patch(
            "src.pipeline.tasks._advance_watermark"
        ), patch("src.pipeline.tasks.ConnectorRegistry") as mock_registry, patch(
            "src.pipeline.tasks.get_run_logger"
        ):
            mock_connector = MagicMock()
            mock_connector.fetch.return_value = []
            mock_registry.get.return_value = mock_connector

            # Call with source_id string (not Connector object)
            fetch_source(mock_db, "netflix_blog", since=None)

            # Registry.get should have been called with string
            mock_registry.get.assert_called_once_with("netflix_blog")

    def test_fetch_source_handles_connector_fetch_error(self, mock_db):
        """fetch_source should handle connector.fetch() raising exceptions."""
        with patch("src.pipeline.tasks._get_watermark"), patch(
            "src.pipeline.tasks._advance_watermark"
        ), patch("src.pipeline.tasks.ConnectorRegistry") as mock_registry, patch(
            "src.pipeline.tasks.get_run_logger"
        ) as mock_logger_factory:
            mock_logger = MagicMock()
            mock_logger_factory.return_value = mock_logger

            mock_connector = MagicMock()
            mock_connector.fetch.side_effect = Exception("Network timeout")
            mock_registry.get.return_value = mock_connector

            # Should not raise, just log and continue
            try:
                fetch_source(mock_db, "netflix_blog", since=None)
            except Exception:
                pytest.fail("fetch_source should not raise on connector error")

    def test_fetch_source_returns_none(self, mock_db):
        """fetch_source task should return None (fire-and-forget)."""
        with patch("src.pipeline.tasks._get_watermark"), patch(
            "src.pipeline.tasks._advance_watermark"
        ), patch("src.pipeline.tasks.ConnectorRegistry") as mock_registry, patch(
            "src.pipeline.tasks.get_run_logger"
        ):
            mock_connector = MagicMock()
            mock_connector.fetch.return_value = []
            mock_registry.get.return_value = mock_connector

            result = fetch_source(mock_db, "netflix_blog", since=None)

            assert result is None


class TestProcessBatchTaskStub:
    """Tests for process_batch task (stubs in Phase 2)."""

    def test_process_batch_task_exists(self):
        """process_batch task should be importable and callable."""
        from src.pipeline.tasks import process_batch

        assert callable(process_batch)

    def test_cluster_stories_task_exists(self):
        """cluster_stories task should be importable and callable."""
        from src.pipeline.tasks import cluster_stories

        assert callable(cluster_stories)

    def test_discover_topics_task_exists(self):
        """discover_topics task should be importable and callable."""
        from src.pipeline.tasks import discover_topics

        assert callable(discover_topics)
