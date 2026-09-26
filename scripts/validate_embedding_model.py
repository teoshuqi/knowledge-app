"""F-05 gate — embedding model domain-validation (tech design §10.2).

A general-purpose sentence-transformer benchmark doesn't guarantee transfer
to AI/ML technical text. Before EmbeddingClient (P-02) picks a default model,
confirm a candidate actually separates "same story" from "different story"
pairs drawn from this project's own domain, with a real margin — not by
picking one off a leaderboard.

This is a one-time pre-implementation check, not an ongoing test — run it
once per candidate model to decide EMBEDDING_MODEL, then move on.

Run: python scripts/validate_embedding_model.py
"""
from dataclasses import dataclass

from fastembed import TextEmbedding

from src.pipeline.story_matching import cosine_similarity


@dataclass
class Pair:
    text_a: str
    text_b: str
    should_match: bool  # True = same underlying story/topic, False = unrelated


# Titles + one-line summaries in the shape enrichment actually embeds (§10.2:
# "embed title + summary, not full text"), drawn from the seed sources' domain.
PAIRS: list[Pair] = [
    # --- same story, different source/wording (should embed close together) ---
    Pair(
        "GLM-5.2 sets new state of the art on SWE-bench Verified",
        "GLM 5.2 tops the SWE-bench Verified leaderboard, beating prior open models",
        True,
    ),
    Pair(
        "OpenAI confirms unauthorized access to internal HuggingFace repos",
        "HuggingFace incident: OpenAI staff credentials used in unauthorized repo access",
        True,
    ),
    Pair(
        "Anthropic releases Claude Opus 5.5 with improved agentic tool use",
        "Claude Opus 5.5 launches, Anthropic highlights gains in tool-calling reliability",
        True,
    ),
    Pair(
        "New arXiv paper proposes a cheaper alternative to RLHF for alignment",
        "Researchers publish a lower-cost RLHF alternative on arXiv, sparking discussion on r/MachineLearning",
        True,
    ),
    Pair(
        "vLLM adds native support for speculative decoding",
        "Speculative decoding lands in vLLM, cutting inference latency in benchmarks",
        True,
    ),
    Pair(
        "r/LocalLLaMA thread: Gemma 4 runs surprisingly well quantized on consumer GPUs",
        "Gemma 4 quantized inference on consumer hardware — community benchmarks in r/LocalLLaMA",
        True,
    ),
    Pair(
        "DeepSeek publishes a new mixture-of-experts routing technique",
        "DeepSeek's new MoE routing method described in their latest technical report",
        True,
    ),
    Pair(
        "Model Context Protocol adoption grows across agent frameworks",
        "MCP gains traction as more agent tooling projects add support",
        True,
    ),
    Pair(
        "Prefect 3.0 released with a reworked task-caching layer",
        "Prefect ships version 3.0, headline feature is the new task-cache design",
        True,
    ),
    Pair(
        "BERTopic adds zero-shot topic assignment in its latest release",
        "Zero-shot topic matching lands in BERTopic's newest version",
        True,
    ),
    Pair(
        "New benchmark shows retrieval-augmented generation still struggles with multi-hop questions",
        "RAG systems underperform on multi-hop QA, a new benchmark finds",
        True,
    ),
    Pair(
        "Spotify engineering blog details their move to a lakehouse architecture",
        "Spotify's engineering team describes migrating their data platform to a lakehouse",
        True,
    ),
    # --- different, unrelated stories (should embed far apart) ---
    Pair(
        "GLM-5.2 sets new state of the art on SWE-bench Verified",
        "Spotify engineering blog details their move to a lakehouse architecture",
        False,
    ),
    Pair(
        "OpenAI confirms unauthorized access to internal HuggingFace repos",
        "BERTopic adds zero-shot topic assignment in its latest release",
        False,
    ),
    Pair(
        "Anthropic releases Claude Opus 5.5 with improved agentic tool use",
        "New benchmark shows retrieval-augmented generation still struggles with multi-hop questions",
        False,
    ),
    Pair(
        "vLLM adds native support for speculative decoding",
        "Model Context Protocol adoption grows across agent frameworks",
        False,
    ),
    Pair(
        "DeepSeek publishes a new mixture-of-experts routing technique",
        "Prefect 3.0 released with a reworked task-caching layer",
        False,
    ),
    Pair(
        "r/LocalLLaMA thread: Gemma 4 runs surprisingly well quantized on consumer GPUs",
        "New arXiv paper proposes a cheaper alternative to RLHF for alignment",
        False,
    ),
    # --- hard negatives: same general area, genuinely different story (the case that matters most) ---
    Pair(
        "GLM-5.2 sets new state of the art on SWE-bench Verified",
        "Claude Opus 5.5 launches, Anthropic highlights gains in tool-calling reliability",
        False,
    ),
    Pair(
        "DeepSeek publishes a new mixture-of-experts routing technique",
        "GLM 5.2 tops the SWE-bench Verified leaderboard, beating prior open models",
        False,
    ),
    Pair(
        "vLLM adds native support for speculative decoding",
        "BERTopic adds zero-shot topic assignment in its latest release",
        False,
    ),
    Pair(
        "Model Context Protocol adoption grows across agent frameworks",
        "r/LocalLLaMA thread: Gemma 4 runs surprisingly well quantized on consumer GPUs",
        False,
    ),
]

CANDIDATES = ["BAAI/bge-small-en-v1.5", "sentence-transformers/all-MiniLM-L6-v2"]


def evaluate(model_name: str) -> dict:
    model = TextEmbedding(model_name=model_name)
    match_sims: list[float] = []
    non_match_sims: list[float] = []
    for pair in PAIRS:
        emb_a, emb_b = (list(v) for v in model.embed([pair.text_a, pair.text_b]))
        sim = cosine_similarity(emb_a, emb_b)
        (match_sims if pair.should_match else non_match_sims).append(sim)

    return {
        "model": model_name,
        "match_min": min(match_sims),
        "match_mean": sum(match_sims) / len(match_sims),
        "non_match_max": max(non_match_sims),
        "non_match_mean": sum(non_match_sims) / len(non_match_sims),
        "margin": min(match_sims) - max(non_match_sims),
    }


def main() -> None:
    assert len(PAIRS) >= 20, "need at least 20 hand-labeled pairs per tech design §10.2"

    results = [evaluate(name) for name in CANDIDATES]
    for r in results:
        print(
            f"{r['model']}: margin={r['margin']:+.3f}  "
            f"match[{r['match_min']:.3f}-{r['match_mean']:.3f}]  "
            f"non-match[{r['non_match_mean']:.3f}-{r['non_match_max']:.3f}]"
        )

    best = max(results, key=lambda r: r["margin"])
    print(f"\nBest separation: {best['model']} (margin={best['margin']:+.3f})")
    if best["margin"] <= 0:
        print("VERDICT: no candidate cleanly separates matches from non-matches on this "
              "sample — do not default to either yet; expand PAIRS or reconsider the model list.")
    else:
        print(f"VERDICT: set EMBEDDING_MODEL={best['model']} as the default.")


if __name__ == "__main__":
    main()
