"""Application settings, read from the environment (or a local .env file)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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


class RetrievalBackend(StrEnum):
    LEXICAL = "lexical"
    """Term overlap in pure Python over stored text. Needs no server, so it is the
    default and the one the test suite runs on."""

    PGVECTOR = "pgvector"
    """Embedding similarity in Postgres. Opt-in, and currently raises: it lands only
    with a price table and a live verification run, like a paid LLM adapter."""


class CookieSameSite(StrEnum):
    """How far the browser will carry the session cookies.

    This is the CSRF control, not a preference. A cookie is attached by the browser
    whether or not the page asking for it is yours, which a bearer header is not —
    so the moment a cookie can authenticate a write, something has to say where the
    request may have come from.
    """

    LAX = "lax"
    """Sent on same-site requests and on top-level navigations only, so a cross-site
    POST carries nothing. The default, and sufficient here: the browser and the API
    share a host in every setup this project has (ports do not affect same-site)."""

    STRICT = "strict"
    """Also withheld from top-level navigations *into* the app. Safe, and it means a
    link from an email lands on a signed-out page."""

    NONE = "none"
    """Sent cross-site, which is what a browser and an API on genuinely different
    domains need — and which throws away the protection above, so the Origin check in
    `deps.py` becomes the only thing standing between a cookie and a forged write.
    Requires `COOKIE_SECURE=true`; the settings validator refuses the pair without
    it, because a browser silently drops such a cookie and the operator would see
    authentication that simply does not work."""


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

    # Object storage, used only when STORAGE_BACKEND=minio. The defaults match the
    # `minio` service in docker-compose.yml, so turning it on locally is one
    # variable. The endpoint is a URL rather than a host because the scheme decides
    # TLS, and getting that wrong silently is worse than a connection refused.
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "hirelens"
    minio_secret_key: str = "hirelens-dev-secret"
    minio_bucket: str = "hirelens-resumes"
    # S3 requires a region; MinIO ignores it. Named rather than hard-coded so the
    # same adapter can point at a real S3 bucket.
    minio_region: str = "us-east-1"

    # `inline` for the same reason the fake extractor is the default provider: a
    # fresh clone must run with no servers. Either way the client contract is the
    # same — upload returns a `pending` resume and the caller polls until the
    # status is terminal; `inline` simply gets there before the response returns.
    queue_backend: QueueBackend = QueueBackend.INLINE

    # Browser origins allowed to call the API. Settable so a dev server that lands
    # on a different port is one env var away from working, instead of a CORS error
    # that says nothing about the real cause — and it has to be settable before
    # deploying anyway. `NoDecode` keeps pydantic-settings from insisting on JSON,
    # so the natural form works:
    #   CORS_ORIGINS=http://localhost:3000,http://localhost:3002
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 14

    # The same tokens, delivered as httpOnly cookies so a browser never holds one
    # anywhere script can read it. Bearer auth is unchanged and still accepted —
    # every `curl` in docs/RUNBOOK.md uses one, and a header cannot be attached
    # cross-site, which is why only the cookie path needs the Origin check.
    cookie_secure: bool = False
    """`Secure`, so the cookie is only ever sent over HTTPS. False by default because
    dev is plain http — and note that Chrome treats `http://localhost` as a secure
    context, so `true` works there too. Any real deployment sets it."""

    cookie_samesite: CookieSameSite = CookieSameSite.LAX

    cookie_domain: str | None = None
    """Left unset so the cookie is host-only, which is what a single-host deploy
    wants. Setting it shares the cookie with every subdomain, including any that is
    not yours to trust."""

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

    # Least mean per-word confidence (0-100) a recognized page may have before it is
    # refused. `0` turns the check off — and with it the second Tesseract call it
    # costs, since text and confidence cannot come out of one invocation.
    #
    # 75 is measured, not guessed (`tests/tools/ocr_degradation.py`): degrading the
    # scanned fixture sixteen ways, every version that still yielded its content
    # scored 90.2 or better and every version that yielded none scored 47.4 or
    # worse. 75 sits in that gap, and low in it on purpose — the fixtures are clean
    # synthetic renders, so a real photograph will score lower while still being
    # readable, and a wrongly refused scan is a message the user can act on while a
    # wrongly accepted one is a confident, fully cited profile of the wrong text.
    ocr_min_confidence: float = Field(default=75.0, ge=0, le=100)

    # Which resumes are worth paying to judge. Lexical by default because it needs
    # no server and no embedding provider, so the suite and a fresh clone are
    # unchanged — the same reasoning as `fake` and `OCR_ENGINE=none`. It only
    # orders a list; it never decides what evidence a screening sees.
    retrieval_backend: RetrievalBackend = RetrievalBackend.LEXICAL

    # How many times to re-ask the model when its evidence fails validation.
    extraction_max_attempts: int = Field(default=2, ge=1, le=5)

    # The same, for judging a resume against a job's requirements. Separate from
    # the above because the cost profiles differ: extraction runs once per resume,
    # while screening runs once per resume *per job*, so this is the knob that
    # multiplies.
    judgment_max_attempts: int = Field(default=2, ge=1, le=5)

    # How many times a job may fail before the resume is dead-lettered. Counts
    # consecutive failures, so a success or a manual retry clears the budget.
    job_max_attempts: int = Field(default=3, ge=1, le=10)

    # Backoff between job attempts: base * 2 ** (failures - 1), so 5s, 10s, 20s.
    # Long enough for a provider blip to pass, short enough that a user waiting on
    # an upload is not abandoned.
    job_retry_base_seconds: float = Field(default=5.0, gt=0)

    # How long a row may sit at `processing` before a worker is presumed dead and
    # the row is reclaimed (`jobs.reclaim_stalled`). Deliberately far longer than
    # any legitimate job — the live runs in `docs/HANDOFF.md` §1 finish in 4-11 s
    # and OCR adds roughly a second a page — because reaping a worker that is
    # merely slow duplicates its work, while reaping one that is dead costs a
    # requeue. The claim sets `last_attempt_at` once and does not heartbeat, so
    # this has to cover a whole job rather than a step of one.
    # The sweep itself runs once a minute (`app/worker.py`), which is noise next to
    # a timeout this long. Nothing sweeps under `QUEUE_BACKEND=inline`, which has no
    # worker process at all — there, `POST /resumes/{id}/retry` on a stalled row is
    # the way back.
    job_visibility_timeout_seconds: float = Field(default=900.0, gt=0)

    # The progress stream: how often it re-reads the resume, how long it may go
    # quiet before sending a keep-alive comment, and how long one connection may
    # stay open at all. Each is a number a deployment behind a proxy may have to
    # change, and the tests set all three low so they finish in milliseconds.
    sse_poll_seconds: float = Field(default=0.5, gt=0)
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0)
    sse_max_stream_seconds: float = Field(default=300.0, gt=0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept `a,b` from the environment as well as a real list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

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

    @model_validator(mode="after")
    def _refuse_samesite_none_without_secure(self) -> Self:
        # A `SameSite=None` cookie without `Secure` is not weakly held — every
        # browser drops it outright. So the failure this prevents is not a security
        # hole, it is an authentication system that silently does not work at all,
        # on the one configuration somebody reaches for precisely because the
        # ordinary one would not do. Refusing at startup is the same instinct as the
        # placeholder-secret guard above: fail where somebody is looking.
        if self.cookie_samesite is CookieSameSite.NONE and not self.cookie_secure:
            raise ValueError(
                "COOKIE_SAMESITE=none requires COOKIE_SECURE=true — browsers reject "
                "the combination and the session cookie would never be stored."
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
