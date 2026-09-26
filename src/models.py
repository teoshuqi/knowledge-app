"""Single source of truth for data shapes. Every module below imports from here
rather than redefining a field list — one change, one place.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class EntityType(str, Enum):
    MODEL = "model"
    TOOL = "tool"
    COMPANY = "company"
    PAPER = "paper"
    DATASET = "dataset"
    BENCHMARK = "benchmark"
    PERSON = "person"


class KeyEntity(BaseModel):
    name: str
    type: EntityType


class RawItem(BaseModel):
    source_id: str
    source_type: str
    fetched_at: datetime
    external_id: str
    raw_payload: dict


class CanonicalDraft(BaseModel):
    """What a Connector hands the processing pipeline — before enrichment/embedding."""

    source_id: str
    external_id: str
    canonical_url: str
    title: str
    author: str | None
    published_at: datetime
    cleaned_text: str
    item_type: Literal["article", "repo"]
    is_near_empty: bool


class Enrichment(BaseModel):
    """The one structured LLM call's validated output. See LLMClient."""

    summary: str
    key_entities: list[KeyEntity]
    topics: list[str]  # candidate topic names, resolved against the registry downstream


class SilverItem(BaseModel):
    id: UUID
    canonical_url: str
    title: str
    title_simhash: int
    author: str | None
    published_at: datetime
    cleaned_text: str
    summary: str
    key_entities: list[KeyEntity]
    embedding: list[float]
    source_ids: list[str]
    item_type: Literal["article", "repo"]


class TopicRegistryEntry(BaseModel):
    id: UUID
    canonical_name: str
    category: str
    status: Literal["proposed", "active", "rejected", "merged"]
    merged_into_id: UUID | None
    origin: Literal["llm_fast_path", "discovery", "user_created"]


class StoryCluster(BaseModel):
    id: UUID
    status: Literal["open", "closed"]
    first_seen_at: datetime
    last_item_at: datetime
    representative_title: str
    representative_embedding: list[float]
    entity_set: list[str]
