"""Application settings, read from the environment (or a local .env file)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Safe to import: app.llm.fake depends only on the LLM base types and schemas,
# never on settings, so there is no cycle.
from app.llm.fake import FakeMode

# Repo root: api/app/config.py -> api/app -> api -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]


class AppEnv(StrEnum):
    DEV = "dev"
    PROD = "prod"


class LLMProvider(StrEnum):
    FAKE = "fake"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"


class StorageBackend(StrEnum):
    LOCAL = "local"
    MINIO = "minio"


DEFAULT_JWT_SECRET = "change-me-before-deploying"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # `dev` is the default so a fresh clone just runs; anything else refuses to
    # start on the placeholder JWT secret (see the validator below).
    app_env: AppEnv = AppEnv.DEV

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

    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 14

    # How many times to re-ask the model when its evidence fails validation.
    extraction_max_attempts: int = Field(default=2, ge=1, le=5)

    @model_validator(mode="after")
    def _refuse_placeholder_secret_outside_dev(self) -> Self:
        # A deploy that forgets JWT_SECRET must fail at startup, not silently
        # sign every token with a secret that is committed to the repository.
        if self.app_env is not AppEnv.DEV and self.jwt_secret == DEFAULT_JWT_SECRET:
            raise ValueError(
                f"JWT_SECRET is still the placeholder while APP_ENV={self.app_env}. "
                'Generate one: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return self

    @property
    def storage_path(self) -> Path:
        """Absolute upload directory, resolved against the repo root."""
        if self.storage_dir.is_absolute():
            return self.storage_dir
        return REPO_ROOT / self.storage_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
