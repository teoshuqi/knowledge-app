"""The one query layer bot and dashboard both call — this is what makes
"one query layer, two thin clients" true in code, not just in the design doc.
Protocol, not ABC: a test fake just needs to match this shape, no inheritance
ceremony. Two real implementers (Postgres in production, an in-memory fake in
tests) is what justifies the seam existing at all.
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID


class DigestCard(Protocol):
    id: UUID
    title: str
    link: str
    badge: str
    section: str  # "trending" | "for_you" | "new"


class GoldRepository(Protocol):
    def trending_candidates(self) -> list[DigestCard]:
        """From fct_digest_trending — open stories, >=2 distinct sources, not yet sent."""

    def new_candidates(self) -> list[DigestCard]:
        """From fct_digest_new — the catch-all so nothing silently disappears."""

    def for_you_candidates(self) -> list[DigestCard]:
        """From fct_topic_affinity (Phase 2). Empty list until that model exists —
        callers must not special-case "not built yet", an empty result is the
        correct, permanent shape of "no affinity signal for this item".
        """

    def cluster_coverage(self, story_id: UUID) -> list[DigestCard]:
        """Every item in one story, for the dashboard coverage view."""

    def record_events(self, subject_ids: list[UUID], event_type: str) -> None:
        """Idempotent: gold.engagement_events has a UNIQUE(subject_type, subject_id,
        event_type) constraint, so re-sending the same digest twice never
        double-logs a 'sent' event.
        """

    def save_item(self, item_id: UUID) -> None: ...
    def mute_source(self, source_id: str) -> None: ...
    def pending_topic_proposals(self) -> list[dict]: ...
    def confirm_topic(self, topic_id: UUID) -> None: ...
    def reject_topic(self, topic_id: UUID) -> None: ...
    def merge_topic(self, topic_id: UUID, into: UUID) -> None: ...


class DigestBuilder:
    """Pure assembly over an already-resolved gold view — see technical
    design §3.7. No scoring logic belongs here; if a card ever needs a new
    ranking rule, that rule is a dbt model change, not an edit to this class.
    """
    def __init__(self, repo: GoldRepository):
        self._repo = repo

    def build(self) -> list[DigestCard]:
        cards = (
            self._repo.trending_candidates()
            + self._repo.for_you_candidates()
            + self._repo.new_candidates()
        )
        self._repo.record_events([c.id for c in cards], event_type="sent")
        return cards
