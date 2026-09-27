"""Unit tests for GitHubTrendingConnector."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.github_trending import GitHubTrendingConnector
from src.models import RawItem


@pytest.fixture
def github_connector():
    """Create GitHubTrendingConnector instance for testing."""
    return GitHubTrendingConnector("github_trending")


class TestGitHubTrendingConnectorFetch:
    """Tests for GitHubTrendingConnector.fetch() method."""

    def test_fetch_returns_raw_items(self, github_connector, github_api_sample):
        """Fetch should return RawItems from GitHub API response."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = github_api_sample
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            items = github_connector.fetch(since=None)

            assert len(items) == 2
            assert all(isinstance(item, RawItem) for item in items)
            # external_id is repo ID (int as string), not full_name
            assert items[0].external_id == "1"
            assert items[1].external_id == "2"

    def test_fetch_uses_correct_github_api_url(self, github_connector, github_api_sample):
        """Fetch should use GitHub Search API with correct endpoint."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = github_api_sample
            mock_get.return_value = mock_response

            github_connector.fetch(since=None)

            # Verify API endpoint was called
            assert mock_get.called
            call_args = mock_get.call_args
            assert "api.github.com/search/repositories" in call_args[0][0]

    def test_fetch_filters_by_creation_date(self, github_connector, github_api_sample):
        """Fetch should filter repos by creation date when since is provided."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {"items": [], "total_count": 0}
            mock_get.return_value = mock_response

            watermark = datetime(2026, 5, 1, tzinfo=UTC)
            github_connector.fetch(since=watermark)

            # Verify query params include date filter
            call_args = mock_get.call_args
            params = call_args[1].get("params", {})
            assert "q" in params
            assert "created:" in params["q"]

    def test_fetch_sets_source_metadata(self, github_connector, github_api_sample):
        """Fetch should set source_id and source_type on items."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = github_api_sample
            mock_get.return_value = mock_response

            items = github_connector.fetch(since=None)

            assert all(item.source_id == "github_trending" for item in items)
            assert all(item.source_type == "github_trending" for item in items)

    def test_fetch_handles_api_error(self, github_connector):
        """Fetch should handle HTTP errors gracefully."""
        with patch("httpx.get") as mock_get:
            import httpx

            mock_get.side_effect = httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=MagicMock()
            )

            items = github_connector.fetch(since=None)

            # Should return error item
            assert isinstance(items, list)
            assert len(items) == 1
            assert items[0].fetch_status == "error"


class TestGitHubTrendingConnectorToCanonicalDraft:
    """Tests for GitHubTrendingConnector.to_canonical_draft() method."""

    def test_to_canonical_draft_creates_repo_shaped_item(
        self, github_connector, sample_raw_item
    ):
        """to_canonical_draft should create repo-shaped draft (not article)."""
        # Create GitHub-format raw item with correct payload
        github_item = sample_raw_item
        github_item.source_id = "github_trending"
        github_item.raw_payload = {
            "name": "awesome-llm",
            "url": "https://github.com/awesome/awesome-llm",
            "description": "Curated list of awesome LLM projects",
            "stars": 5000,
            "language": "Python",
            "updated_at": "2026-09-27T12:00:00Z",
        }
        github_item.fetch_status = "ok"

        draft = github_connector.to_canonical_draft(github_item)

        assert draft.item_type == "repo"
        assert draft.title == "awesome-llm"
        assert "5000" in draft.cleaned_text
        assert "Python" in draft.cleaned_text

    def test_to_canonical_draft_includes_repo_metadata(
        self, github_connector, sample_raw_item
    ):
        """to_canonical_draft should include stars and language in cleaned_text."""
        github_item = sample_raw_item
        github_item.source_id = "github_trending"
        github_item.raw_payload = {
            "name": "project",
            "url": "https://github.com/org/project",
            "description": "Test project",
            "stars": 2500,
            "language": "TypeScript",
            "updated_at": "2026-09-27T12:00:00Z",
        }
        github_item.fetch_status = "ok"

        draft = github_connector.to_canonical_draft(github_item)

        assert "2500" in draft.cleaned_text
        assert "TypeScript" in draft.cleaned_text

    def test_to_canonical_draft_handles_missing_language(
        self, github_connector, sample_raw_item
    ):
        """to_canonical_draft should handle repos with no language."""
        github_item = sample_raw_item
        github_item.source_id = "github_trending"
        github_item.raw_payload = {
            "full_name": "org/project",
            "html_url": "https://github.com/org/project",
            "description": "Test project",
            "stargazers_count": 100,
            "language": None,
        }

        draft = github_connector.to_canonical_draft(github_item)

        assert draft.cleaned_text is not None
        assert draft.is_near_empty is False

    def test_to_canonical_draft_sets_canonical_url(
        self, github_connector, sample_raw_item
    ):
        """to_canonical_draft should set canonical_url to repo URL."""
        github_item = sample_raw_item
        github_item.source_id = "github_trending"
        github_item.raw_payload = {
            "name": "awesome-llm",
            "url": "https://github.com/awesome/awesome-llm",
            "description": "Curated list",
            "stars": 1000,
            "language": "Python",
            "updated_at": "2026-09-27T12:00:00Z",
        }
        github_item.fetch_status = "ok"

        draft = github_connector.to_canonical_draft(github_item)

        assert draft.canonical_url == "https://github.com/awesome/awesome-llm"


class TestGitHubTrendingConnectorRegistry:
    """Tests for GitHub connector instantiation."""

    def test_github_trending_source_instantiates(self):
        """github_trending source should instantiate via ConnectorRegistry."""
        from src.connectors import ConnectorRegistry

        connector = ConnectorRegistry.get("github_trending")
        assert isinstance(connector, GitHubTrendingConnector)
        assert connector.source_id == "github_trending"
