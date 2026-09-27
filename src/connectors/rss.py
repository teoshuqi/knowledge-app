"""RSS feed connector for blog aggregation.

Sources: Netflix, Jay Alammar, Spotify, SeattleDataGuy, arXiv (3 categories).
Uses feedparser to fetch feeds, trafilatura for text extraction.
"""

from datetime import UTC, datetime
from typing import ClassVar

import feedparser
import trafilatura

from src.connectors.base import Connector
from src.models import CanonicalDraft, RawItem


class RSSConnector(Connector):
    """Fetches and extracts RSS feeds."""

    source_type: str = "rss"
    source_id: str  # set by subclass per feed

    FEEDS: ClassVar[dict[str, str]] = {
        "netflix_blog": "https://netflixtechblog.com/feed",
        "jay_alammar": "https://jalammar.github.io/feed.xml",
        "spotify_eng": "https://engineering.atspotify.com/feed/",
        "seattle_data_guy": "https://www.seattledataguy.com/feed",
        "arxiv_llm": "http://export.arxiv.org/rss/cs.CL",
        "arxiv_ai": "http://export.arxiv.org/rss/cs.AI",
        "arxiv_ml": "http://export.arxiv.org/rss/stat.ML",
    }

    def __init__(self, source_id: str):
        self.source_id = source_id
        if source_id not in self.FEEDS:
            msg = f"Unknown RSS source: {source_id}"
            raise ValueError(msg)

    def fetch(self, since: datetime | None = None) -> list[RawItem]:
        """Fetch items from RSS feed."""
        feed_url = self.FEEDS[self.source_id]
        items = []

        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo:
                ts = int(datetime.now(UTC).timestamp())
                return [
                    RawItem(
                        source_id=self.source_id,
                        source_type=self.source_type,
                        fetched_at=datetime.now(UTC),
                        external_id=f"error_{self.source_id}_{ts}",
                        raw_payload={"error": str(feed.bozo_exception)},
                        fetch_status="error",
                    )
                ]

            for entry in feed.entries:
                try:
                    dt = datetime(*entry.published_parsed[:6])  # noqa: DTZ001
                    published = dt.replace(tzinfo=UTC)
                except (AttributeError, TypeError, ValueError):
                    published = datetime.now(UTC)

                if since and published <= since:
                    continue

                link = entry.get("link", "").split("?")[0]
                external_id = entry.get("id") or link
                if not external_id:
                    continue

                items.append(
                    RawItem(
                        source_id=self.source_id,
                        source_type=self.source_type,
                        fetched_at=datetime.now(UTC),
                        external_id=external_id,
                        raw_payload={
                            "title": entry.get("title", ""),
                            "link": entry.get("link", ""),
                            "summary": entry.get("summary", ""),
                            "published": published.isoformat(),
                            "author": entry.get("author", ""),
                        },
                        fetch_status="ok",
                    )
                )
        except (OSError, ValueError) as e:
            ts = int(datetime.now(UTC).timestamp())
            return [
                RawItem(
                    source_id=self.source_id,
                    source_type=self.source_type,
                    fetched_at=datetime.now(UTC),
                    external_id=f"error_{self.source_id}_{ts}",
                    raw_payload={"error": str(e)},
                    fetch_status="error",
                )
            ]

        return items

    def _extract_text(self, url: str, summary: str) -> str:
        """Extract text via trafilatura, fallback to summary."""
        if not url:
            return ""
        try:
            extracted = trafilatura.extract(
                url, output_format="txt", include_comments=False
            )
            return (extracted or "").strip()
        except OSError:
            return summary.strip()

    def _parse_published(self, published_str: str) -> datetime:
        """Parse published timestamp from payload."""
        try:
            return datetime.fromisoformat(published_str)
        except (ValueError, TypeError):
            return datetime.now(UTC)

    def to_canonical_draft(self, raw: RawItem) -> CanonicalDraft:
        """Extract canonical draft from RSS entry."""
        if raw.fetch_status != "ok":
            return CanonicalDraft(
                source_id=raw.source_id,
                external_id=raw.external_id,
                canonical_url=f"https://{self.source_id}",
                title="[Fetch Error]",
                author=None,
                published_at=raw.fetched_at,
                cleaned_text="",
                item_type="article",
                is_near_empty=True,
            )

        payload = raw.raw_payload
        url = payload.get("link", "")
        title = payload.get("title", "").strip()
        author = payload.get("author", "").strip()
        summary = payload.get("summary", "")

        cleaned_text = self._extract_text(url, summary)
        is_near_empty = len(cleaned_text) < 50
        published = self._parse_published(payload.get("published", ""))

        return CanonicalDraft(
            source_id=raw.source_id,
            external_id=raw.external_id,
            canonical_url=url or f"https://{self.source_id}/{raw.external_id}",
            title=title or "[No Title]",
            author=author or None,
            published_at=published,
            cleaned_text=cleaned_text,
            item_type="article",
            is_near_empty=is_near_empty,
        )
