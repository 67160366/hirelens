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


class QueueBackend(StrEnum):
    INLINE = "inline"
    """Run the job before the upload responds. No Redis, so a fresh clone works."""

    ARQ = "arq"
    """Hand the job to an ARQ worker over Redis. The real thing."""


class OCREngineName(StrEnum):
    NONE = "none"
    """No OCR: a page with no text layer stays unreadable, as it was before M2 #4."""

    TESSERACT = "tesseract"
    """Shell out to Tesseract. Needs the binary and its language packs installed."""


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
    gemini_model: str = "gemini-3.6-flash"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"

    database_url: str = "postgresql+asyncpg://hirelens:hirelens@localhost:5432/hirelens"
    redis_url: str = "redis://localhost:6379/0"

    storage_backend: StorageBackend = StorageBackend.LOCAL
    storage_dir: Path = Path("var/uploads")

    # `inline` for the same reason the fake extractor is the default provider: a
    # fresh clone must run with no servers. Either way the client contract is the
    # same — upload returns a `pending` resume and the caller polls until the
    # status is terminal; `inline` simply gets there before the response returns.
    queue_backend: QueueBackend = QueueBackend.INLINE

    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 14

    # OCR for pages with no text layer. Off by default for the same reason the
    # extractor defaults to `fake`: Tesseract is a system binary, CI will never
    # have one, and a fresh clone has to run the whole suite with no servers.
    ocr_engine: OCREngineName = OCREngineName.NONE

    # The binary's name or full path. A portable Tesseract is not on PATH, so this
    # is not as redundant as it looks.
    ocr_command: str = "tesseract"

    # Tesseract's `+`-joined language codes. Thai first because that is what this
    # project is for; a missing pack is refused at startup rather than silently
    # returning noise for half the document.
    ocr_languages: str = "tha+eng"

    # 300 dpi is the usual floor for reliable OCR — below it Thai tone marks start
    # to blur into the characters they sit on.
    ocr_dpi: int = Field(default=300, ge=72, le=600)

    # Rendering and recognizing a page costs roughly a second, so a long scan is
    # capped rather than allowed to hold a worker. Pages past the cap stay reported
    # as having no text.
    ocr_max_pages: int = Field(default=10, ge=1, le=50)
    ocr_timeout_seconds: float = Field(default=60.0, gt=0)

    # How many times to re-ask the model when its evidence fails validation.
    extraction_max_attempts: int = Field(default=2, ge=1, le=5)

    # How many times a job may fail before the resume is dead-lettered. Counts
    # consecutive failures, so a success or a manual retry clears the budget.
    job_max_attempts: int = Field(default=3, ge=1, le=10)

    # Backoff between job attempts: base * 2 ** (failures - 1), so 5s, 10s, 20s.
    # Long enough for a provider blip to pass, short enough that a user waiting on
    # an upload is not abandoned.
    job_retry_base_seconds: float = Field(default=5.0, gt=0)

    # The progress stream: how often it re-reads the resume, how long it may go
    # quiet before sending a keep-alive comment, and how long one connection may
    # stay open at all. Each is a number a deployment behind a proxy may have to
    # change, and the tests set all three low so they finish in milliseconds.
    sse_poll_seconds: float = Field(default=0.5, gt=0)
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0)
    sse_max_stream_seconds: float = Field(default=300.0, gt=0)

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
