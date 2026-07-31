"""Application settings, read from the environment (or a local .env file)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Safe to import: app.llm.fake depends only on the LLM base types and schemas,
# never on settings, so there is no cycle.
from app.llm.fake import FakeMode

# Repo root: api/app/config.py -> api/app -> api -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]


class LLMProvider(StrEnum):
    FAKE = "fake"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"


class StorageBackend(StrEnum):
    LOCAL = "local"
    MINIO = "minio"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # A fixture-backed provider is the default on purpose: a fresh clone runs the
    # full test suite with no API key and no spend.
    llm_provider: LLMProvider = LLMProvider.FAKE

    # How the fake backend behaves. `hallucinating` makes it cite text that is not
    # in the document — the only way to exercise the dropped-claims path in the UI
    # without waiting for a real model to misbehave. Ignored for other providers.
    fake_mode: FakeMode = FakeMode.FAITHFUL

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"

    database_url: str = "postgresql+asyncpg://hirelens:hirelens@localhost:5432/hirelens"
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: StorageBackend = StorageBackend.LOCAL
    storage_dir: Path = Path("var/uploads")

    jwt_secret: str = "change-me-before-deploying"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 14

    # How many times to re-ask the model when its evidence fails validation.
    extraction_max_attempts: int = Field(default=2, ge=1, le=5)

    @property
    def storage_path(self) -> Path:
        """Absolute upload directory, resolved against the repo root."""
        if self.storage_dir.is_absolute():
            return self.storage_dir
        return REPO_ROOT / self.storage_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
