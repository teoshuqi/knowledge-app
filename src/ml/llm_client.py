"""One concrete class, not a provider-per-adapter hierarchy: litellm.completion
already IS the multi-provider seam (Anthropic vs. a local llama-server are both
just a `model` string to it). Building our own adapter-per-provider on top
would duplicate a seam that already exists — see ponytail rung 5.

What this module actually earns its keep on: turning a Pydantic schema into a
tool spec, validating the response against it, and retrying once on a
malformed reply before flagging — every call site (enrichment, BERTopic's
topic-naming step) would otherwise duplicate that loop.
"""

from __future__ import annotations

import logging
from typing import TypeVar

import litellm
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ExtractionFailed(Exception):
    """Raised after the retry is exhausted. Caller flags the item the same
    way a near-empty trafilatura extraction is flagged — never silently
    stored as partial data.
    """


class LLMClient:
    def __init__(self, model: str, max_retries: int = 1):
        # `model` is a litellm model string: "claude-haiku-4-5-20251001" for
        # the API, or "openai/<name>" with api_base pointed at a local
        # llama-server for the self-hosted path. That's the whole provider
        # switch — a config value, not a code path.
        self.model = model
        self.max_retries = max_retries

    def extract(self, prompt: str, schema: type[T]) -> T:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            response = litellm.completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                tools=[_schema_to_tool(schema)],
                tool_choice="required",
            )
            try:
                raw = response.choices[0].message.tool_calls[0].function.arguments
                return schema.model_validate_json(raw)
            except (ValidationError, IndexError, AttributeError) as e:
                last_error = e
                logger.warning(
                    "LLM structured output invalid (attempt %d): %s", attempt, e
                )
        raise ExtractionFailed(
            f"{schema.__name__} extraction failed after retry: {last_error}"
        )


def _schema_to_tool(schema: type[BaseModel]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": f"emit_{schema.__name__.lower()}",
            "parameters": schema.model_json_schema(),
        },
    }
