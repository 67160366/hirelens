"""The ARQ worker process.

Run it alongside the API:

    arq app.worker.WorkerSettings

This module is only the adapter between arq's calling convention and
`app.jobs.run_resume_job`. The work itself lives there so it can be tested
without Redis, and so the inline queue runs exactly the same code.

Retry with backoff and a dead-letter queue are M2 #2; for now a job that raises
gets arq's default retry and the resume stays `pending` until it succeeds.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, ClassVar

from arq import func
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import build_engine, build_sessionmaker
from app.jobs import JobContext, run_resume_job
from app.llm.registry import build_extractor
from app.logging_config import configure_logging
from app.queue import PROCESS_RESUME_TASK
from app.storage import build_storage

logger = logging.getLogger(__name__)

CONTEXT_KEY = "job_context"


async def process_resume(ctx: dict[str, Any], resume_id: str) -> None:
    """The registered task. Ids cross Redis as strings, so parse it back here."""
    await run_resume_job(ctx[CONTEXT_KEY], uuid.UUID(resume_id))


async def on_startup(ctx: dict[str, Any]) -> None:
    """Build the engine, storage and extractor once per worker process."""
    configure_logging()
    settings = get_settings()
    engine = build_engine(settings)
    ctx["engine"] = engine
    ctx[CONTEXT_KEY] = JobContext(
        sessionmaker=build_sessionmaker(engine),
        storage=build_storage(settings),
        extractor=build_extractor(settings),
        settings=settings,
    )
    logger.info(
        "worker started: provider=%s storage=%s",
        settings.llm_provider,
        settings.storage_backend,
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    context: JobContext = ctx[CONTEXT_KEY]
    await context.extractor.aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    # Registered under the shared constant rather than the function's name, so a
    # rename here cannot silently stop matching what the API enqueues.
    functions: ClassVar[list[Any]] = [func(process_resume, name=PROCESS_RESUME_TASK)]
    on_startup = staticmethod(on_startup)
    on_shutdown = staticmethod(on_shutdown)
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
