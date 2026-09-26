"""Entity overlap (primary) + embedding cosine (secondary) — the dual-branch
matching rule from §10.4. Tuned for precision over recall: a missed merge is
a quiet under-count, a false merge actively misinforms the trending signal.

# ponytail: entity_threshold below is a Phase 1 default asserted, not derived.
# Retune against the labeled story-pair eval set (§10.4/§2.11 of the LLD scope)
# once ~30-50 labeled pairs exist — don't hand-tune further before that data does.
"""
import math

_ENTITY_TYPE_WEIGHT = {
    "model": 3.0, "paper": 3.0, "dataset": 2.5, "benchmark": 2.5,
    "tool": 1.5, "company": 1.0, "person": 1.0,
}
_SPECIFIC_TYPES = {"model", "paper", "dataset", "benchmark"}


def _normalize(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def weighted_entity_overlap(a: list[dict], b: list[dict]) -> float:
    a_norm = {_normalize(e["name"]): e["type"] for e in a}
    b_norm = {_normalize(e["name"]): e["type"] for e in b}
    shared = a_norm.keys() & b_norm.keys()
    if not shared:
        return 0.0
    weight = sum(_ENTITY_TYPE_WEIGHT.get(a_norm[k], 1.0) for k in shared)
    total = sum(_ENTITY_TYPE_WEIGHT.get(t, 1.0) for t in [*a_norm.values(), *b_norm.values()])
    return weight / total if total else 0.0


def has_exact_specific_entity_match(a: list[dict], b: list[dict]) -> bool:
    a_specific = {_normalize(e["name"]) for e in a if e["type"] in _SPECIFIC_TYPES}
    b_specific = {_normalize(e["name"]) for e in b if e["type"] in _SPECIFIC_TYPES}
    return bool(a_specific & b_specific)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def find_matching_story(item: dict, open_stories: list[dict], config: dict) -> dict | None:
    entity_threshold = 0.3
    embed_threshold = float(config["story_match_embedding_threshold"])
    relaxed_threshold = float(config["story_match_embedding_threshold_relaxed"])

    best_match, best_score = None, 0.0
    for story in open_stories:
        overlap = weighted_entity_overlap(item["key_entities"], story["entity_set"])
        embed_sim = cosine_similarity(item["embedding"], story["representative_embedding"])

        matches = (overlap >= entity_threshold and embed_sim >= embed_threshold) or (
            has_exact_specific_entity_match(item["key_entities"], story["entity_set"])
            and embed_sim >= relaxed_threshold
        )
        if matches and overlap + embed_sim > best_score:
            best_match, best_score = story, overlap + embed_sim
    return best_match


def update_centroid(old_centroid: list[float], member_count: int, new_embedding: list[float]) -> list[float]:
    """Running mean — O(1) per attach, no need to re-average all members."""
    n = member_count
    return [(c * (n / (n + 1))) + (e * (1 / (n + 1))) for c, e in zip(old_centroid, new_embedding)]


def merge_entity_sets(existing: list[dict], new: list[dict]) -> list[dict]:
    seen = {_normalize(e["name"]): e for e in existing}
    for e in new:
        seen.setdefault(_normalize(e["name"]), e)
    return list(seen.values())
