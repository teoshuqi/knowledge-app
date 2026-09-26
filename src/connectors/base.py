"""Connector seam: real, many-adapter seam (7 sources today, more later).
Interface stays exactly two methods — adding a source is a new subclass,
never a change here or in the pipeline that calls it.
"""
from abc import ABC, abstractmethod

from src.models import CanonicalDraft, RawItem


class Connector(ABC):
    source_id: str
    source_type: str

    @abstractmethod
    def fetch(self, since: str | None = None) -> list[RawItem]:
        """Fetch items newer than `since` (ISO timestamp). None = since this
        connector's own last successful fetch, tracked by the caller via
        pipeline_watermarks — this method never needs a human to pass a date.
        Must be idempotent: re-fetching an already-seen external_id is safe
        (bronze.raw_items enforces this with a UNIQUE constraint regardless).
        """

    @abstractmethod
    def to_canonical_draft(self, raw: RawItem) -> CanonicalDraft:
        """This source's own raw→canonical conversion (e.g. github_trending
        builds a repo-shaped draft with no trafilatura step; everything else
        runs trafilatura). The processing pipeline calls this polymorphically
        and never branches on source_type itself — that branching would be
        the one thing that breaks §4.1's "adding a source touches nothing
        else" requirement.
        """
