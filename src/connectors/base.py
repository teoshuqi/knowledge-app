"""Connector seam: real, many-adapter seam (7 sources today, more later).
Interface stays exactly two methods — adding a source is a new subclass,
never a change here or in the pipeline that calls it.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from src.models import CanonicalDraft, RawItem


class Connector(ABC):
    source_id: str
    source_type: str

    @abstractmethod
    def fetch(self, since: datetime | None = None) -> list[RawItem]:
        """Fetch items newer than `since` (datetime object). None = use watermark
        from pipeline_watermarks table (read by caller); explicit since is a
        replay window and never advances the watermark. Must be idempotent:
        re-fetching the same external_id is safe (bronze.raw_items enforces
        UNIQUE(source_id, external_id) regardless).
        """

    @abstractmethod
    def to_canonical_draft(self, raw: RawItem) -> CanonicalDraft:
        """Convert this source's raw item to canonical form. Each connector
        implements its own extraction (e.g. GitHub Trending builds a repo-shaped
        draft; RSS sources run trafilatura). Pipeline calls this polymorphically
        per source_type — no source-type branching in the pipeline itself.
        """
