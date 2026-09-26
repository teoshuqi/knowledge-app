"""The one structured LLM call per item — summary, typed entities, fast-path
topic tags. See §2.4/§10.1 for the rationale; this module is the prompt and
the call, kept separate from tasks.py's orchestration.
"""

from src.ml.llm_client import LLMClient
from src.models import CanonicalDraft, Enrichment

_PROMPT = """Extract a summary, key entities, and topic tags from this content.

TITLE: {title}
TEXT: {text}

Return:
- summary: 2-4 sentences, factual, no editorializing.
- key_entities: named models, tools, companies, papers, datasets, benchmarks,
  or people explicitly present in the text. Type each one. Never invent an
  entity that isn't named.
- topics: 1-3 tags, at "recurring theme" granularity (e.g. "agent tooling"),
  not "one-off event" granularity (a specific release is a story, not a
  topic). Prefer reusing one of these if it genuinely applies: {existing_topics}
  Only propose a new name if none fit.

Examples, so extraction stays consistent across content types:
- A GitHub repo README: summary states what the tool does and its main use
  case; key_entities includes the tool itself (type=tool) and any
  underlying model/library it wraps.
- A benchmark results post: summary states what was compared and the
  headline result; key_entities includes every named model/dataset in the
  comparison, not only the winner.
- An opinion/analysis piece: summary states the author's core claim, not a
  neutral restatement; key_entities includes whatever the argument turns on.
"""


def build_prompt(draft: CanonicalDraft, existing_topics: list[str]) -> str:
    # ponytail: full active-topic list passed every call. Fine under ~100
    # topics; switch to top-K-by-embedding-similarity retrieval (§10.6) once
    # the registry grows past that — don't build the retrieval path before
    # the list is actually big enough to need it.
    return _PROMPT.format(
        title=draft.title,
        text=draft.cleaned_text[
            :4000
        ],  # bound input; full text rarely adds signal past this
        existing_topics=", ".join(existing_topics) or "(none yet)",
    )


def enrich(
    llm: LLMClient, draft: CanonicalDraft, existing_topics: list[str]
) -> Enrichment:
    return llm.extract(build_prompt(draft, existing_topics), Enrichment)
