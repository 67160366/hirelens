"""A durable queue using the pending rows already committed by API services.

One consumer runs inside the API process on the free hosting profile. No job is
held only in memory: a process restart discovers pending rows again, and the
existing visibility timeout recovers interrupted jobs. Render suspension pauses
processing until an incoming request wakes the service.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import suppress
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.jobs import (
    JobContext,
    backoff_seconds,
    purge_revoked_tokens,
    reclaim_stalled,
    run_resume_job,
    run_screening_job,
)
from app.models import Resume, ResumeStatus, Screening, ScreeningStatus
from app.models.base import utcnow
from app.queue import JobQueue

logger = logging.getLogger(__name__)


class DatabaseQueue(JobQueue):
    def __init__(self, context: JobContext, *, poll_seconds: float = 5) -> None:
        self._context = context
        self._poll_seconds = poll_seconds
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Database queue is already running")
        self._task = asyncio.create_task(self._run(), name="database-queue")

    async def enqueue_resume(self, resume_id: uuid.UUID, *, attempt: int = 0) -> None:
        # The service commits the pending row before this call; waking is just an
        # optimization. Polling also handles a crash between commit and enqueue.
        self._wake.set()

    async def enqueue_screening(self, screening_id: uuid.UUID, *, attempt: int = 0) -> None:
        self._wake.set()

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def _due(self, model: type[Resume] | type[Screening], now: datetime) -> ColumnElement[bool]:
        conditions = [model.failed_attempts == 0, model.last_attempt_at.is_(None)]
        for failures in range(1, self._context.settings.job_max_attempts):
            cutoff = now - timedelta(
                seconds=backoff_seconds(self._context.settings, failures=failures)
            )
            conditions.append(
                and_(model.failed_attempts == failures, model.last_attempt_at <= cutoff)
            )
        return or_(*conditions)

    async def run_once(self, *, now: datetime | None = None) -> bool:
        moment = now or utcnow()
        async with self._context.sessionmaker() as session:
            resume_id = await session.scalar(
                select(Resume.id)
                .where(Resume.status == ResumeStatus.PENDING, self._due(Resume, moment))
                .order_by(Resume.created_at, Resume.id)
                .limit(1)
            )
            screening_id = await session.scalar(
                select(Screening.id)
                .where(Screening.status == ScreeningStatus.PENDING, self._due(Screening, moment))
                .order_by(Screening.created_at, Screening.id)
                .limit(1)
            )
        # A batch includes both kinds so resume uploads cannot starve screenings.
        # Each job uses the original row lock, retry policy and evidence pipeline.
        if resume_id is not None:
            await run_resume_job(self._context, resume_id)
        if screening_id is not None:
            await run_screening_job(self._context, screening_id)
        return resume_id is not None or screening_id is not None

    async def _run(self) -> None:
        next_sweep = 0.0
        while True:
            self._wake.clear()
            try:
                if time.monotonic() >= next_sweep:
                    await reclaim_stalled(self._context)
                    await purge_revoked_tokens(self._context)
                    next_sweep = time.monotonic() + 60
                if await self.run_once():
                    continue
            except Exception as exc:
                # Driver errors may contain SQL parameters. Log only the type.
                logger.error("database queue iteration failed: %s", type(exc).__name__)
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_seconds)
