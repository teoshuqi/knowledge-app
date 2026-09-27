"""Unit tests for RSSConnector."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.rss import RSSConnector
from src.models import RawItem


@pytest.fixture
def rss_connector():
    """Create RSSConnector instance for testing."""
    return RSSConnector("netflix_blog")


class TestRSSConnectorFetch:
    """Tests for RSSConnector.fetch() method."""

    def test_fetch_returns_raw_items(self, rss_connector, rss_sample_payload):
        """Fetch should return list of RawItems from parsed feed."""
        with patch("feedparser.parse") as mock_parse:
            mock_feed = MagicMock()
            mock_feed.bozo = False
            mock_feed.entries = rss_sample_payload["entries"]
            mock_parse.return_value = mock_feed
            items = rss_connector.fetch(since=None)

            assert len(items) == 2
            assert all(isinstance(item, RawItem) for item in items)
            assert items[0].external_id == "netflix-001"
            assert items[1].external_id == "netflix-002"

    def test_fetch_filters_by_watermark(self, rss_connector, rss_sample_payload):
        """Fetch should filter items older than watermark (since)."""
        with patch("feedparser.parse") as mock_parse:
            mock_feed = MagicMock()
            mock_feed.bozo = False
            mock_feed.entries = rss_sample_payload["entries"]
            mock_parse.return_value = mock_feed
            # Set watermark to after both items
            watermark = datetime(2026, 9, 28, tzinfo=UTC)
            items = rss_connector.fetch(since=watermark)

            # Both items are older than watermark, so empty result
            assert len(items) == 0

    def test_fetch_sets_source_metadata(self, rss_connector, rss_sample_payload):
        """Fetch should set source_id and source_type on items."""
        with patch("feedparser.parse") as mock_parse:
            mock_feed = MagicMock()
            mock_feed.bozo = False
            mock_feed.entries = rss_sample_payload["entries"]
            mock_parse.return_value = mock_feed
            items = rss_connector.fetch(since=None)

            assert all(item.source_id == "netflix_blog" for item in items)
            assert all(item.source_type == "rss" for item in items)
            assert all(item.fetch_status == "ok" for item in items)

    def test_fetch_handles_parse_error(self, rss_connector):
        """Fetch should handle feedparser failure gracefully."""
        with patch("feedparser.parse") as mock_parse:
            # feedparser.parse should raise OSError for network issues
            mock_parse.side_effect = OSError("Network error")
            items = rss_connector.fetch(since=None)

            # Should return error item on exception
            assert len(items) == 1
            assert items[0].fetch_status == "error"
            assert "Network error" in items[0].raw_payload.get("error", "")

    def test_fetch_empty_feed(self, rss_connector):
        """Fetch should handle empty feeds gracefully."""
        with patch("feedparser.parse") as mock_parse:
            mock_feed = MagicMock()
            mock_feed.bozo = False
            mock_feed.entries = []
            mock_parse.return_value = mock_feed
            items = rss_connector.fetch(since=None)

            assert items == []


class TestRSSConnectorToCanonicalDraft:
    """Tests for RSSConnector.to_canonical_draft() method."""

    def test_to_canonical_draft_extracts_text(self, rss_connector, sample_raw_item):
        """to_canonical_draft should extract text via trafilatura."""
        with patch("trafilatura.extract") as mock_extract:
            long_text = "This is a long article with meaningful content " * 3
            mock_extract.return_value = long_text
            draft = rss_connector.to_canonical_draft(sample_raw_item)

            assert draft.canonical_url == sample_raw_item.raw_payload["link"]
            assert draft.title == sample_raw_item.raw_payload["title"]
            assert len(draft.cleaned_text) > 50
            assert draft.is_near_empty is False

    def test_to_canonical_draft_marks_near_empty(self, rss_connector, sample_raw_item):
        """to_canonical_draft should mark items <50 chars as near_empty."""
        with patch("trafilatura.extract") as mock_extract:
            mock_extract.return_value = "Short"  # Only 5 characters
            draft = rss_connector.to_canonical_draft(sample_raw_item)

            assert draft.is_near_empty is True

    def test_to_canonical_draft_handles_extraction_failure(
        self, rss_connector, sample_raw_item
    ):
        """to_canonical_draft should handle trafilatura returning None."""
        with patch("trafilatura.extract") as mock_extract:
            mock_extract.return_value = None
            draft = rss_connector.to_canonical_draft(sample_raw_item)

            assert draft.is_near_empty is True
            assert draft.cleaned_text == ""

    def test_to_canonical_draft_preserves_source_id(
        self, rss_connector, sample_raw_item
    ):
        """to_canonical_draft should preserve source_id from RawItem."""
        with patch("trafilatura.extract") as mock_extract:
            mock_extract.return_value = "Content"
            draft = rss_connector.to_canonical_draft(sample_raw_item)

            assert draft.source_id == sample_raw_item.source_id

    def test_to_canonical_draft_sets_item_type(
        self, rss_connector, sample_raw_item
    ):
        """to_canonical_draft should set item_type to 'article' for RSS."""
        with patch("trafilatura.extract") as mock_extract:
            mock_extract.return_value = "Article content"
            draft = rss_connector.to_canonical_draft(sample_raw_item)

            assert draft.item_type == "article"


class TestRSSConnectorRegistry:
    """Tests for connector instantiation via registry."""

    def test_all_rss_sources_instantiate(self):
        """All RSS sources should instantiate via ConnectorRegistry.get()."""
        from src.connectors import ConnectorRegistry

        sources = ["netflix_blog", "jay_alammar", "spotify_eng", "arxiv_llm"]
        for source_id in sources:
            connector = ConnectorRegistry.get(source_id)
            assert isinstance(connector, RSSConnector)
            assert connector.source_id == source_id
