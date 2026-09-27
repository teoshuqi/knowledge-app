"""Pytest fixtures for Phase 1 testing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.models import CanonicalDraft, Enrichment, KeyEntity, RawItem


@pytest.fixture
def mock_llm():
    """Mock LLMClient for testing enrichment extraction."""
    llm = MagicMock()

    def extract_mock(prompt: str, model: type) -> Enrichment:
        """Return mock Enrichment with predictable output."""
        return Enrichment(
            summary="Test enrichment summary",
            key_entities=[
                KeyEntity(name="Entity1", type="person"),
                KeyEntity(name="Entity2", type="company"),
            ],
            topics=["AI", "ML"],
        )

    llm.extract = extract_mock
    return llm


@pytest.fixture
def mock_embedder():
    """Mock EmbeddingClient for testing embedding generation."""
    embedder = MagicMock()

    def embed_mock(texts: list[str]) -> list[list[float]]:
        """Return mock embeddings (384-dim vectors)."""
        return [[0.1] * 384 for _ in texts]

    embedder.embed = embed_mock
    return embedder


@pytest.fixture
def mock_db():
    """Mock database connection for testing without real DB."""
    db = MagicMock()
    db.fetch_one = MagicMock(return_value=None)
    db.fetch_all = MagicMock(return_value=[])
    db.execute = MagicMock(return_value=None)
    return db


@pytest.fixture
def sample_raw_item() -> RawItem:
    """Sample RawItem for testing."""
    return RawItem(
        source_id="netflix_blog",
        source_type="rss",
        fetched_at=datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC),
        external_id="netflix-001",
        raw_payload={
            "link": "https://netflixtechblog.com/ml-at-scale-2026",
            "title": "Machine Learning at Scale",
            "published": "2026-09-27T10:00:00Z",
            "summary": (
                "How Netflix scales machine learning for recommendations"
            ),
        },
        fetch_status="ok",
    )


@pytest.fixture
def sample_canonical_draft() -> CanonicalDraft:
    """Sample CanonicalDraft for testing."""
    return CanonicalDraft(
        source_id="netflix_blog",
        source_type="rss",
        item_type="article",
        canonical_url="https://netflixtechblog.com/ml-at-scale-2026",
        title="Machine Learning at Scale",
        author="Netflix Engineering",
        published_at=datetime(2026, 9, 27, 10, 0, 0, tzinfo=UTC),
        cleaned_text="How Netflix scales machine learning for recommendations",
        is_near_empty=False,
    )


@pytest.fixture
def sample_enrichment() -> Enrichment:
    """Sample Enrichment for testing."""
    return Enrichment(
        summary="Machine learning techniques for personalization at scale",
        key_entities=[
            KeyEntity(name="Netflix", type="company"),
            KeyEntity(name="ML", type="tool"),
        ],
        topics=["AI", "Machine Learning"],
    )


@pytest.fixture
def rss_sample_payload() -> dict[str, Any]:
    """RSS feed payload fixture (parsed feedparser output)."""
    return {
        "entries": [
            {
                "title": "Machine Learning at Scale",
                "link": "https://netflixtechblog.com/ml-at-scale-2026",
                "published": "Mon, 27 Sep 2026 10:00:00 GMT",
                "published_parsed": (2026, 9, 27, 10, 0, 0, 0, 271, 0),
                "summary": "How Netflix scales machine learning",
                "id": "netflix-001",
            },
            {
                "title": "Building Resilient Systems",
                "link": "https://netflixtechblog.com/resilience-2026",
                "published": "Sun, 26 Sep 2026 15:30:00 GMT",
                "published_parsed": (2026, 9, 26, 15, 30, 0, 0, 270, 0),
                "summary": "Resilience patterns",
                "id": "netflix-002",
            },
        ]
    }


@pytest.fixture
def github_api_sample() -> dict[str, Any]:
    """GitHub API response fixture."""
    return {
        "items": [
            {
                "id": 1,
                "name": "awesome-llm",
                "full_name": "awesome/awesome-llm",
                "html_url": "https://github.com/awesome/awesome-llm",
                "description": "Curated list of awesome LLM projects",
                "stargazers_count": 5000,
                "language": "Python",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-09-27T00:00:00Z",
            },
            {
                "id": 2,
                "name": "raft",
                "full_name": "org/raft",
                "html_url": "https://github.com/org/raft",
                "description": "Retrieval Augmented Fine-Tuning",
                "stargazers_count": 3200,
                "language": "TypeScript",
                "created_at": "2026-02-15T00:00:00Z",
                "updated_at": "2026-09-26T00:00:00Z",
            },
        ],
        "total_count": 2,
    }
