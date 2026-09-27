"""Connector registry — instantiate connectors by ID."""

from typing import ClassVar

from src.connectors.base import Connector
from src.connectors.github_trending import GitHubTrendingConnector
from src.connectors.reddit import RedditConnector
from src.connectors.rss import RSSConnector


class ConnectorRegistry:
    """Factory for instantiating connectors by source ID."""

    SOURCES: ClassVar[dict[str, type[Connector]]] = {
        # RSS pool sources
        "netflix_blog": RSSConnector,
        "jay_alammar": RSSConnector,
        "spotify_eng": RSSConnector,
        "seattle_data_guy": RSSConnector,
        "arxiv_llm": RSSConnector,
        "arxiv_ai": RSSConnector,
        "arxiv_ml": RSSConnector,
        # Reddit sources
        "r_MachineLearning": RedditConnector,
        "r_LocalLLaMA": RedditConnector,
        "r_mlops": RedditConnector,
        # GitHub
        "github_trending": GitHubTrendingConnector,
    }

    @classmethod
    def get(cls, source_id: str) -> Connector:
        """Get a connector instance by source ID."""
        connector_class = cls.SOURCES.get(source_id)
        if not connector_class:
            msg = f"Unknown connector source: {source_id}"
            raise ValueError(msg)
        return connector_class(source_id)


__all__ = ["Connector", "ConnectorRegistry", "RSSConnector", "RedditConnector"]
