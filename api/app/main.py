"""FastAPI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import applications, auth, jobs, metrics, resumes, screenings
from app.config import get_settings
from app.db import get_sessionmaker
from app.jobs import JobContext
from app.llm.registry import build_extractor
from app.logging_config import configure_logging
from app.pipeline.ocr import build_ocr_engine
from app.pipeline.retrieval import build_retriever
from app.queue import build_queue
from app.storage import build_storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the storage, extraction and queue backends once, not per request."""
    configure_logging()
    settings = get_settings()
    app.state.settings = settings
    app.state.storage = build_storage(settings)
    app.state.extractor = build_extractor(settings)
    # Probes the binary and its language packs, so a misconfigured OCR setup fails
    # here rather than once per uploaded scan.
    app.state.ocr = build_ocr_engine(settings)
    # Same reasoning: an unimplemented retrieval backend is refused at startup
    # rather than on the first request that happens to need it.
    app.state.retriever = build_retriever(settings)
    # Held on state because the progress stream needs to open its own sessions:
    # its generator runs after FastAPI has closed the request's session.
    app.state.sessionmaker = get_sessionmaker()
    # The context is only used by the inline queue; the ARQ worker builds its own
    # in its own process.
    app.state.queue = await build_queue(
        settings,
        JobContext(
            sessionmaker=app.state.sessionmaker,
            storage=app.state.storage,
            extractor=app.state.extractor,
            settings=settings,
            ocr=app.state.ocr,
        ),
    )
    logger.info(
        "started: provider=%s storage=%s queue=%s ocr=%s retrieval=%s",
        settings.llm_provider,
        settings.storage_backend,
        settings.queue_backend,
        settings.ocr_engine,
        settings.retrieval_backend,
    )
    try:
        yield
    finally:
        await app.state.queue.aclose()
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
        # Read here rather than from `app.state`: middleware is added at
        # construction, which happens before the lifespan runs.
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(resumes.router)
    app.include_router(jobs.router)
    # No prefix of its own: creation is nested under /jobs and reads are flat under
    # /screenings, so the paths are spelled out on the routes themselves.
    app.include_router(screenings.router)
    app.include_router(applications.router)
    app.include_router(metrics.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "provider": app.state.extractor.provider_name}

    return app


app = create_app()
