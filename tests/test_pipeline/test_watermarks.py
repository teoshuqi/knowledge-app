"""Tests for watermark and idempotency semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.tasks import _advance_watermark, _get_watermark, fetch_source


class TestWatermarkFunctions:
    """Tests for watermark read/write helpers."""

    def test_get_watermark_returns_epoch_if_not_set(self, mock_db):
        """_get_watermark should return epoch (1970-01-01) if no watermark exists."""
        mock_db.fetch_one.return_value = None
        watermark = _get_watermark(mock_db, "fetch:netflix_blog")

        assert watermark == datetime(1970, 1, 1, tzinfo=UTC)

    def test_get_watermark_returns_last_processed_time(self, mock_db):
        """_get_watermark should return last_processed_at from DB."""
        expected_time = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
        mock_db.fetch_one.return_value = {"last_processed_at": expected_time}

        watermark = _get_watermark(mock_db, "fetch:netflix_blog")

        assert watermark == expected_time
        mock_db.fetch_one.assert_called_once()

    def test_advance_watermark_inserts_timestamp(self, mock_db):
        """_advance_watermark should INSERT/UPDATE pipeline_watermarks."""
        now = datetime(2026, 9, 27, 14, 30, 0, tzinfo=UTC)
        _advance_watermark(mock_db, "fetch:netflix_blog", now)

        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        assert "pipeline_watermarks" in call_args[0][0]
        assert "ON CONFLICT" in call_args[0][0]

    def test_advance_watermark_uses_on_conflict_do_update(self, mock_db):
        """_advance_watermark should use ON CONFLICT DO UPDATE for idempotency."""
        now = datetime(2026, 9, 27, 14, 30, 0, tzinfo=UTC)
        _advance_watermark(mock_db, "fetch:netflix_blog", now)

        call_args = mock_db.execute.call_args
        sql = call_args[0][0]
        assert "ON CONFLICT (task_name) DO UPDATE" in sql
        assert "SET last_processed_at = EXCLUDED.last_processed_at" in sql


class TestFetchSourceWatermarkSemantics:
    """Tests for fetch_source task watermark behavior."""

    def test_fetch_source_advances_watermark_when_since_none(self, mock_db):
        """fetch_source should advance watermark when called with since=None."""
        with patch("src.pipeline.tasks._get_watermark") as mock_get_wm, patch(
            "src.pipeline.tasks._advance_watermark"
        ) as mock_adv_wm, patch(
            "src.pipeline.tasks.ConnectorRegistry"
        ) as mock_registry:
            mock_get_wm.return_value = datetime(2026, 9, 26, tzinfo=UTC)
            mock_connector = MagicMock()
            mock_connector.fetch.return_value = []
            mock_registry.get.return_value = mock_connector

            fetch_source(mock_db, "netflix_blog", since=None)

            # Should call _advance_watermark when since is None
            assert mock_adv_wm.called

    def test_fetch_source_does_not_advance_watermark_on_replay(self, mock_db):
        """fetch_source should NOT advance watermark when since is explicit (replay)."""
        with patch("src.pipeline.tasks._get_watermark") as mock_get_wm, patch(
            "src.pipeline.tasks._advance_watermark"
        ) as mock_adv_wm, patch(
            "src.pipeline.tasks.ConnectorRegistry"
        ) as mock_registry:
            mock_get_wm.return_value = datetime(2026, 9, 26, tzinfo=UTC)
            mock_connector = MagicMock()
            mock_connector.fetch.return_value = []
            mock_registry.get.return_value = mock_connector

            replay_since = datetime(2026, 9, 1, tzinfo=UTC)
            fetch_source(mock_db, "netflix_blog", since=replay_since)

            # Should NOT call _advance_watermark when since is explicit
            assert not mock_adv_wm.called

    def test_fetch_source_passes_watermark_to_connector(self, mock_db):
        """fetch_source should pass watermark to connector.fetch()."""
        with patch("src.pipeline.tasks._get_watermark") as mock_get_wm, patch(
            "src.pipeline.tasks._advance_watermark"
        ), patch("src.pipeline.tasks.ConnectorRegistry") as mock_registry:
            watermark = datetime(2026, 9, 26, 10, 0, 0, tzinfo=UTC)
            mock_get_wm.return_value = watermark

            mock_connector = MagicMock()
            mock_connector.fetch.return_value = []
            mock_registry.get.return_value = mock_connector

            fetch_source(mock_db, "netflix_blog", since=None)

            # Should pass watermark to connector.fetch()
            mock_connector.fetch.assert_called_once_with(since=watermark)

    def test_fetch_source_logs_replay_flag(self, mock_db):
        """fetch_source should log is_replay=True when since is explicit."""
        with patch("src.pipeline.tasks._get_watermark") as mock_get_wm, patch(
            "src.pipeline.tasks._advance_watermark"
        ), patch("src.pipeline.tasks.ConnectorRegistry") as mock_registry, patch(
            "src.pipeline.tasks.get_run_logger"
        ) as mock_logger_factory:
            mock_get_wm.return_value = datetime(2026, 9, 26, tzinfo=UTC)
            mock_logger = MagicMock()
            mock_logger_factory.return_value = mock_logger

            mock_connector = MagicMock()
            mock_connector.fetch.return_value = []
            mock_registry.get.return_value = mock_connector

            fetch_source(mock_db, "netflix_blog", since=datetime(2026, 9, 1, tzinfo=UTC))

            # Should log with replay=True
            log_call = mock_logger.info.call_args[0]
            assert "replay=True" in str(log_call)


class TestIdempotencySemantics:
    """Tests for ON CONFLICT DO NOTHING idempotency."""

    def test_fetch_source_upserts_with_on_conflict(self, mock_db):
        """fetch_source should INSERT with ON CONFLICT (source_id, external_id) DO NOTHING."""
        with patch("src.pipeline.tasks._get_watermark"), patch(
            "src.pipeline.tasks._advance_watermark"
        ), patch("src.pipeline.tasks.ConnectorRegistry") as mock_registry, patch(
            "src.pipeline.tasks.get_run_logger"
        ):
            mock_connector = MagicMock()
            raw_item = MagicMock()
            raw_item.source_id = "netflix_blog"
            raw_item.source_type = "rss"
            raw_item.fetched_at = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
            raw_item.external_id = "netflix-001"
            raw_item.raw_payload = {"link": "http://example.com"}
            raw_item.fetch_status = "ok"

            mock_connector.fetch.return_value = [raw_item]
            mock_registry.get.return_value = mock_connector

            fetch_source(mock_db, "netflix_blog", since=None)

            # Should call db.execute with INSERT...ON CONFLICT
            mock_db.execute.assert_called()
            call_args = mock_db.execute.call_args
            sql = call_args[0][0]
            assert "INSERT INTO bronze.raw_items" in sql
            assert "ON CONFLICT (source_id, external_id) DO NOTHING" in sql

    def test_fetch_source_counts_inserted_and_deduped(self, mock_db):
        """fetch_source should track inserted vs deduped items."""
        with patch("src.pipeline.tasks._get_watermark"), patch(
            "src.pipeline.tasks._advance_watermark"
        ), patch("src.pipeline.tasks.ConnectorRegistry") as mock_registry, patch(
            "src.pipeline.tasks.get_run_logger"
        ) as mock_logger_factory:
            mock_logger = MagicMock()
            mock_logger_factory.return_value = mock_logger

            raw_items = []
            for i in range(3):
                raw_item = MagicMock()
                raw_item.source_id = "netflix_blog"
                raw_item.source_type = "rss"
                raw_item.fetched_at = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
                raw_item.external_id = f"netflix-{i:03d}"
                raw_item.raw_payload = {"link": f"http://example.com/{i}"}
                raw_item.fetch_status = "ok"
                raw_items.append(raw_item)

            mock_connector = MagicMock()
            mock_connector.fetch.return_value = raw_items
            mock_registry.get.return_value = mock_connector

            fetch_source(mock_db, "netflix_blog", since=None)

            # Should log item counts
            log_call = mock_logger.info.call_args[0]
            assert "3 items fetched" in str(log_call) or "inserted=3" in str(log_call)

    def test_fetch_source_handles_db_errors_gracefully(self, mock_db):
        """fetch_source should catch DB errors and log them."""
        with patch("src.pipeline.tasks._get_watermark"), patch(
            "src.pipeline.tasks._advance_watermark"
        ), patch("src.pipeline.tasks.ConnectorRegistry") as mock_registry, patch(
            "src.pipeline.tasks.get_run_logger"
        ) as mock_logger_factory:
            mock_logger = MagicMock()
            mock_logger_factory.return_value = mock_logger

            mock_connector = MagicMock()
            raw_item = MagicMock()
            raw_item.source_id = "netflix_blog"
            raw_item.source_type = "rss"
            raw_item.fetched_at = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
            raw_item.external_id = "netflix-001"
            raw_item.raw_payload = {}
            raw_item.fetch_status = "ok"

            mock_connector.fetch.return_value = [raw_item]
            mock_registry.get.return_value = mock_connector

            # Mock db.execute to raise OSError
            mock_db.execute.side_effect = OSError("DB connection failed")

            # Should not raise, just log
            fetch_source(mock_db, "netflix_blog", since=None)

            # Should log exception
            assert mock_logger.exception.called or mock_logger.warning.called
