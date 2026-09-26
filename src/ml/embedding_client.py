"""Two real adapters here, unlike llm_client — fastembed and sentence-transformers
are genuinely different libraries with different model-loading mechanics, so
this seam is earning its keep (ponytail: "two adapters means a real one").

Default: fastembed (no torch, small image). Escape hatch: sentence-transformers,
used only when a specific fine-tuned HF model isn't in fastembed's curated list
and isn't worth an ONNX export. Selected once via config, not branched at
every call site.
"""

from __future__ import annotations

from typing import Protocol


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedClient:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]


class SentenceTransformerClient:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts).tolist()


def build_embedding_client(config: dict[str, str]) -> EmbeddingClient:
    """Reads gold.pipeline_config; not a factory for its own sake — this is the
    one place a new model-loading concern (e.g. a third backend) would ever
    need to be added, per codebase-design's seam-placement principle.
    """
    backend = config.get("embedding_backend", "fastembed")
    if backend == "fastembed":
        return FastEmbedClient(config.get("embedding_model", "BAAI/bge-small-en-v1.5"))
    if backend == "sentence_transformers":
        return SentenceTransformerClient(config["embedding_model"])
    raise ValueError(f"unknown embedding backend: {backend}")
