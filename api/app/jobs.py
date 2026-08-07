"""The unit of background work: parse and extract one stored resume.

`resume_service.process_resume` was written to be called from a job — it takes no
HTTP types and does not commit. This module is the thin shell that gives it a
session, the stored bytes, and a transaction boundary, so the same work runs
whether it was dispatched to an ARQ worker or executed inline.

Nothing here imports arq. The worker entrypoint (`app/worker.py`) adapts this to
arq's calling convention; keeping the two apart is what lets the tests exercise
the job without Redis.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.llm.base import StructuredExtractor
from app.models import Resume, ResumeStatus
from app.services import resume_service
from app.storage import ObjectNotFoundError, Storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class JobContext:
    """Everything a job needs, built once per process rather than per job."""

    sessionmaker: async_sessionmaker[AsyncSession]
    storage: Storage
    extractor: StructuredExtractor
    settings: Settings


async def run_resume_job(context: JobContext, resume_id: uuid.UUID) -> None:
    """Parse and extract one resume, committing the outcome.

    Safe to run more than once for the same id: a resume that already has a
    verified profile is left alone. That matters because a retry (M2 #2) and a
    re-uploaded duplicate can both put the same id on the queue again, and
    re-running extraction would spend money to produce what we already have.
    """
    async with context.sessionmaker() as session:
        resume = await session.get(Resume, resume_id)
        if resume is None:
            # The row was deleted between enqueue and pickup. Nothing to do, and
            # nothing wrong — failing the job would only fill the queue with work
            # that can never succeed.
            logger.warning("resume %s: queued but no longer exists", resume_id)
            return

        if resume.status is ResumeStatus.EXTRACTED:
            logger.info("resume %s: already extracted, skipping", resume_id)
            return

        try:
            data = await context.storage.get(resume.storage_key)
        except ObjectNotFoundError:
            # Recorded on the row rather than raised: an object that is not there
            # will not appear on a retry either, and a resume stuck at `pending`
            # with no explanation is exactly the silent failure to avoid.
            resume.status = ResumeStatus.FAILED
            resume.failure_reason = "The stored file is missing."
            await session.commit()
            logger.error("resume %s: stored object is missing", resume_id)
            return

        await resume_service.process_resume(
            session,
            resume=resume,
            data=data,
            extractor=context.extractor,
            settings=context.settings,
        )
        await session.commit()
