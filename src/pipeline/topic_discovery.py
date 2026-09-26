"""BERTopic with zero-shot assignment against the active registry, then
HDBSCAN over the residual — see §2.6/§10.5. A fresh, stateless instance every
run; no persisted model artifact to version between runs.

NOTE: BERTopic's exact constructor/representation-model API below is written
from general knowledge of the library's shape (zeroshot_topic_list,
BaseRepresentation subclassing, get_representative_docs) — verify parameter
names against the installed version's docs before implementing; this is the
one module in this pass I can't fully vouch for at the API-signature level.
"""

from bertopic import BERTopic
from bertopic.representation import BaseRepresentation
from pydantic import BaseModel

from src.ml.llm_client import LLMClient


class _TopicName(BaseModel):
    name: str
    is_duplicate_of_existing: (
        str | None
    )  # an existing name, if this really is that topic


class LLMTopicNamer(BaseRepresentation):
    """Plugs the existing LLMClient into BERTopic's representation-model slot —
    topic naming is provider-flexible the same way enrichment is (§2.4).
    """

    def __init__(self, llm: LLMClient, active_topic_names: list[str]):
        self._llm = llm
        self._active_names = active_topic_names

    def extract_topics(self, topic_model, documents, c_tf_idf, topics):
        updated = {}
        for topic_id in topics:
            if topic_id == -1:  # BERTopic's noise label — never name noise
                continue
            sample = "\n".join(topic_model.get_representative_docs(topic_id)[:5])
            prompt = (
                f"These stories were grouped as one theme:\n{sample}\n\n"
                f"Existing topics: {', '.join(self._active_names) or '(none yet)'}\n"
                "Propose a concise name (2-4 words), or say which existing topic this duplicates."
            )
            result = self._llm.extract(prompt, _TopicName)
            updated[topic_id] = [(result.is_duplicate_of_existing or result.name, 1.0)]
        return updated


def run_discovery(
    llm: LLMClient, active_topics: list[dict], stories: list[dict], config: dict
) -> list[dict]:
    """Returns [{story_id, topic_name, is_new}, ...]. Deciding the grouping is
    this function's only job — tasks.py owns the topic_registry/
    story_topics_discovered upsert.
    """
    min_cluster_size = int(config["topic_discovery_min_cluster_size"])
    if len(stories) < min_cluster_size:
        return []  # not enough recent stories to find anything — not an error

    active_names = [t["canonical_name"] for t in active_topics]
    model = BERTopic(
        zeroshot_topic_list=active_names or None,
        zeroshot_min_similarity=float(config["topic_discovery_zeroshot_similarity"]),
        min_cluster_size=min_cluster_size,
        representation_model=LLMTopicNamer(llm, active_names),
        calculate_probabilities=False,
    )
    titles = [s["representative_title"] for s in stories]
    embeddings = [s["representative_embedding"] for s in stories]
    assigned_topics, _ = model.fit_transform(documents=titles, embeddings=embeddings)

    topic_info = model.get_topic_info()
    results = []
    for story, topic_id in zip(stories, assigned_topics):
        if topic_id == -1:
            continue  # genuinely nothing to propose — not every story needs a topic
        name = topic_info.loc[topic_info["Topic"] == topic_id, "Name"].iloc[0]
        results.append(
            {
                "story_id": story["id"],
                "topic_name": name,
                "is_new": name not in active_names,
            }
        )
    return results
