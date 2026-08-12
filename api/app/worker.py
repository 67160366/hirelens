"""The ARQ worker process.

Run it alongside the API:

    arq app.worker.WorkerSettings

This module is only the adapter between arq's calling convention and
`app.jobs.run_resume_job`. The work itself lives there so it can be tested
without Redis, and so the inline queue runs exactly the same code.

That includes the retry policy: the job decides whether and when to try again,
and all this does is turn that decision into arq's `Retry`. Which failures are
worth retrying, and when to give up, is in `app/jobs.py`.

The sweep for rows a dead worker left behind is registered here too, as a cron
job, for the same reason: `jobs.reclaim_stalled` is ordinary async code that the
tests drive directly, and arq's scheduler is the only part of it that needs Redis.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, ClassVar

from arq import Retry, cron, func
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import build_engine, build_sessionmaker
from app.jobs import JobContext, reclaim_stalled, run_resume_job, run_screening_job
from app.llm.registry import build_extractor
from app.logging_config import configure_logging
from app.pipeline.ocr import build_ocr_engine
from app.queue import PROCESS_RESUME_TASK, RUN_SCREENING_TASK, build_queue
from app.storage import build_storage

logger = logging.getLogger(__name__)

CONTEXT_KEY = "job_context"


async def process_resume(ctx: dict[str, Any], resume_id: str) -> None:
    """The registered task. Ids cross Redis as strings, so parse it back here."""
    outcome = await run_resume_job(ctx[CONTEXT_KEY], uuid.UUID(resume_id))
    if outcome.retry_after_seconds is not None:
        # The resume row already records the failure and is back at `pending`;
        # this only asks arq to redeliver the job after the backoff.
        raise Retry(defer=outcome.retry_after_seconds)


async def run_screening(ctx: dict[str, Any], screening_id: str) -> None:
    """The judging task. Same adapter shape as `process_resume` above."""
    outcome = await run_screening_job(ctx[CONTEXT_KEY], uuid.UUID(screening_id))
    if outcome.retry_after_seconds is not None:
        raise Retry(defer=outcome.retry_after_seconds)


async def reclaim(ctx: dict[str, Any]) -> None:
    """The sweep for rows whose worker died holding them.

    Cron rather than a task anyone enqueues: there is no event to hang it off,
    because the thing that would have raised the failure is the process that went
    away. arq's `unique=True` (its default) keeps one sweep running across a
    cluster, so replicas do not each reclaim the same row.
    """
    await reclaim_stalled(ctx[CONTEXT_KEY])


async def on_startup(ctx: dict[str, Any]) -> None:
    """Build the engine, storage, extractor and OCR once per worker process."""
    configure_logging()
    settings = get_settings()
    engine = build_engine(settings)
    ctx["engine"] = engine
    context = JobContext(
        sessionmaker=build_sessionmaker(engine),
        storage=build_storage(settings),
        extractor=build_extractor(settings),
        settings=settings,
        # Probed here too: the worker is a separate process, and it is the one
        # that actually runs OCR.
        ocr=build_ocr_engine(settings),
    )
    # After the context, because the inline backend takes one — and the reaper is
    # the only job here that puts work *back* on the queue rather than taking it off.
    context.queue = await build_queue(settings, context)
    ctx[CONTEXT_KEY] = context
    logger.info(
        "worker started: provider=%s storage=%s ocr=%s",
        settings.llm_provider,
        settings.storage_backend,
        settings.ocr_engine,
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    context: JobContext = ctx[CONTEXT_KEY]
    if context.queue is not None:
        await context.queue.aclose()
    await context.extractor.aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    # Registered under the shared constant rather than the function's name, so a
    # rename here cannot silently stop matching what the API enqueues.
    #
    # `max_tries` is deliberately above the job's own budget: giving up is the
    # job's decision, recorded on the resume as a dead letter, and arq's counter
    # cutting in first would end the retries with nothing written down.
    functions: ClassVar[list[Any]] = [
        func(
            process_resume,
            name=PROCESS_RESUME_TASK,
            max_tries=get_settings().job_max_attempts + 2,
        ),
        func(
            run_screening,
            name=RUN_SCREENING_TASK,
            max_tries=get_settings().job_max_attempts + 2,
        ),
    ]

    # Once a minute, on the minute. An interval knob would be false precision next
    # to a 900 s visibility timeout — a sweep a minute adds at most 60 s to how long
    # a dead worker's row waits, and the timeout is what decides that.
    cron_jobs: ClassVar[list[Any]] = [cron(reclaim, second=0, run_at_startup=True)]

    on_startup = staticmethod(on_startup)
    on_shutdown = staticmethod(on_shutdown)
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
