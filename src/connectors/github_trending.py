"""GitHub Trending repositories connector.

Fetches trending repos via GitHub API. Returns repo-shaped drafts.
"""

from datetime import UTC, datetime
from typing import Any

import httpx

from src.connectors.base import Connector
from src.models import CanonicalDraft, RawItem

QueryParams = dict[str, str | int | float | bool | None]


class GitHubTrendingConnector(Connector):
    """Fetches trending repositories from GitHub."""

    source_type: str = "github_trending"
    source_id: str = "github_trending"

    GITHUB_API = "https://api.github.com"
    SEARCH_ENDPOINT = f"{GITHUB_API}/search/repositories"

    def _build_params(self, since: datetime | None) -> QueryParams:
        """Build query parameters for GitHub API search."""
        now = datetime.now(UTC)
        since_date = since or datetime(
            now.year, now.month, max(1, now.day - 7), tzinfo=UTC
        )
        date_str = since_date.strftime("%Y-%m-%d")
        return {
            "q": f"created:>{date_str} stars:>100",
            "sort": "stars",
            "order": "desc",
            "per_page": 30,
        }

    def _parse_repo(
        self, repo: dict[str, Any], since: datetime | None
    ) -> RawItem | None:
        """Extract repo data, skip if updated before watermark."""
        try:
            external_id = str(repo["id"])
            updated_at = repo.get("updated_at", "")

            if updated_at:
                try:
                    repo_updated = datetime.fromisoformat(updated_at)
                    if since and repo_updated <= since:
                        return None
                except ValueError:
                    pass

            return RawItem(
                source_id=self.source_id,
                source_type=self.source_type,
                fetched_at=datetime.now(UTC),
                external_id=external_id,
                raw_payload={
                    "name": repo.get("name", ""),
                    "url": repo.get("html_url", ""),
                    "description": repo.get("description", ""),
                    "stars": repo.get("stargazers_count", 0),
                    "language": repo.get("language", ""),
                    "updated_at": updated_at,
                },
                fetch_status="ok",
            )
        except (KeyError, TypeError):
            return None

    def fetch(self, since: datetime | None = None) -> list[RawItem]:
        """Fetch trending repos (created/updated recently, by stars)."""
        items = []

        try:
            params: QueryParams = self._build_params(since)
            headers = {"Accept": "application/vnd.github.v3+json"}

            response = httpx.get(
                self.SEARCH_ENDPOINT,
                params=params,
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            for repo in data.get("items", []):
                item = self._parse_repo(repo, since)
                if item:
                    items.append(item)

        except httpx.HTTPError as e:
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
        """Extract canonical draft from GitHub repo."""
        if raw.fetch_status != "ok":
            return CanonicalDraft(
                source_id=raw.source_id,
                external_id=raw.external_id,
                canonical_url="https://github.com",
                title="[Fetch Error]",
                author=None,
                published_at=raw.fetched_at,
                cleaned_text="",
                item_type="repo",
                is_near_empty=True,
            )

        payload: Any = raw.raw_payload
        url = payload.get("url", "")
        name = payload.get("name", "").strip()
        description = payload.get("description", "").strip()
        language = payload.get("language") or "unknown"
        stars = payload.get("stars", 0)

        cleaned_text = f"{description}\nLanguage: {language}, Stars: {stars}".strip()
        is_near_empty = len(cleaned_text) < 30

        try:
            updated = payload.get("updated_at", "")
            published = datetime.fromisoformat(updated)
        except (ValueError, TypeError, AttributeError):
            published = datetime.now(UTC)

        return CanonicalDraft(
            source_id=raw.source_id,
            external_id=raw.external_id,
            canonical_url=url or "https://github.com",
            title=name or "[No Name]",
            author=None,
            published_at=published,
            cleaned_text=cleaned_text,
            item_type="repo",
            is_near_empty=is_near_empty,
        )
