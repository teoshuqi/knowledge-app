"""Smoke test for Settings (F-04, LLD §2.1)."""

from src.config import get_settings


def test_settings_reads_env_and_caches(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://u:p@host/db")
    monkeypatch.setenv("LLAMA_SERVER_URL", "http://localhost:8080")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.postgres_dsn == "postgresql://u:p@host/db"
    assert settings.llama_server_url == "http://localhost:8080"
    assert get_settings() is settings  # lru_cache: same instance, not re-read


def test_settings_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    # .env carries TELEGRAM_BOT_TOKEN= (empty), so "unset" surfaces as ''
    # here, not None — pydantic-settings reads .env before this check ever
    # sees a true absence. No caller does an `is None` check today.
    assert not settings.telegram_bot_token
    assert settings.embedding_backend == "fastembed"
