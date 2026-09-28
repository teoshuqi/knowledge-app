"""Central settings — the one place every storage/LLM/embedding endpoint is
read from (F-04, LLD §2.1). Fields nothing reads yet stay Optional rather than
forcing a value now; the consuming module raises its own clear error once it
actually needs one.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    postgres_dsn: str | None = Field(None, alias="POSTGRES_DSN")
    telegram_bot_token: str | None = Field(None, alias="TELEGRAM_BOT_TOKEN")

    # LLMClient is one concrete, LiteLLM-routed class (tech design §2.4) —
    # llm_model is either an Anthropic model name or an OpenAI-compatible
    # URL pointed at llama-server; only the matching credential below
    # needs a value.
    llm_model: str = Field("claude-sonnet-5", alias="LLM_MODEL")
    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    llama_server_url: str | None = Field(None, alias="LLAMA_SERVER_URL")

    # Default set by the F-05 gate (scripts/validate_embedding_model.py):
    # on a 22-pair hand-labeled sample from this project's own domain,
    # MiniLM-L6-v2 separated same-story/different-story pairs with a
    # positive margin; bge-small-en-v1.5 did not. Re-run the gate before
    # changing this.
    embedding_backend: str = Field("fastembed", alias="EMBEDDING_BACKEND")
    embedding_model: str = Field(
        "sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def create_llm_client() -> "LLMClient":  # noqa: F821
    """Factory for LLMClient routed via config: Anthropic API or local llama-server.
    Caller imports this, never instantiates LLMClient directly.
    """
    from src.ml.llm_client import LLMClient

    settings = get_settings()

    # If llama_server_url is set, route to local; otherwise use Anthropic API
    if settings.llama_server_url:
        return LLMClient(model=settings.llm_model, api_base=settings.llama_server_url)
    else:
        return LLMClient(model=settings.llm_model)
