"""FastAPI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, resumes
from app.config import get_settings
from app.llm.registry import build_extractor
from app.storage import build_storage

logger = logging.getLogger(__name__)

# The dev-time Next.js origin. Tighten this before deploying.
ALLOWED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def configure_logging() -> None:
    """One root handler at INFO. Resumes are PII: log ids and counts, never text."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the storage and extraction backends once, not per request."""
    configure_logging()
    settings = get_settings()
    app.state.settings = settings
    app.state.storage = build_storage(settings)
    app.state.extractor = build_extractor(settings)
    logger.info("started: provider=%s storage=%s", settings.llm_provider, settings.storage_backend)
    try:
        yield
    finally:
        await app.state.extractor.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="HireLens API",
        version="0.1.0",
        summary="Explainable resume screening: every claim cites the source document.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(resumes.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "provider": app.state.extractor.provider_name}

    return app


app = create_app()
