"""Reddit subreddit connector using RSS feeds.

Sources: r/MachineLearning, r/LocalLLaMA, r/mlops.
Uses feedparser with User-Agent (no OAuth/PRAW).
"""

from datetime import UTC, datetime
from typing import ClassVar

import feedparser

from src.connectors.base import Connector
from src.models import CanonicalDraft, RawItem


class RedditConnector(Connector):
    """Fetches Reddit subreddit posts via RSS."""

    source_type: str = "reddit"
    source_id: str  # set by subclass per subreddit

    SUBREDDITS: ClassVar[dict[str, str]] = {
        "r_MachineLearning": "r/MachineLearning",
        "r_LocalLLaMA": "r/LocalLLaMA",
        "r_mlops": "r/mlops",
    }

    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )

    def __init__(self, source_id: str):
        self.source_id = source_id
        if source_id not in self.SUBREDDITS:
            msg = f"Unknown Reddit source: {source_id}"
            raise ValueError(msg)

    def _feed_url(self) -> str:
        """Construct Reddit RSS feed URL for subreddit."""
        subreddit = self.SUBREDDITS[self.source_id]
        return f"https://www.reddit.com/{subreddit}/.rss"

    def fetch(self, since: datetime | None = None) -> list[RawItem]:
        """Fetch posts from subreddit RSS feed."""
        items = []

        try:
            feed = feedparser.parse(
                self._feed_url(),
                request_headers={"User-Agent": self.USER_AGENT},
            )
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
                    published = datetime(*entry.published_parsed[:6])  # noqa: DTZ001
                    published = published.replace(tzinfo=UTC)
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
        except OSError as e:
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

    def to_canonical_draft(self, raw: RawItem) -> CanonicalDraft:
        """Extract canonical draft from Reddit post."""
        if raw.fetch_status != "ok":
            return CanonicalDraft(
                source_id=raw.source_id,
                external_id=raw.external_id,
                canonical_url=f"https://reddit.com/{self.source_id}",
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

        cleaned_text = (summary or "").strip()[:1000]
        is_near_empty = len(cleaned_text) < 50

        try:
            published = datetime.fromisoformat(payload.get("published", ""))
        except (ValueError, TypeError):
            published = datetime.now(UTC)

        return CanonicalDraft(
            source_id=raw.source_id,
            external_id=raw.external_id,
            canonical_url=url or f"https://reddit.com/{self.source_id}",
            title=title or "[No Title]",
            author=author or None,
            published_at=published,
            cleaned_text=cleaned_text,
            item_type="article",
            is_near_empty=is_near_empty,
        )
