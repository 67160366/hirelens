"""Dispatching work, behind a narrow interface.

The same seam as `app/storage.py` and the LLM registry: callers say "process this
resume later" and never learn whether that meant Redis or a direct call.

Two implementations, and the choice does not change what a client sees. Upload
always answers with a `pending` resume and the caller polls until the status is
terminal — `InlineQueue` simply reaches that state before the response is written.
That keeps one client contract instead of one per deployment shape.
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import QueueBackend, Settings
from app.jobs import JobContext, run_resume_job

logger = logging.getLogger(__name__)

PROCESS_RESUME_TASK = "process_resume"
"""The name the worker registers the job under. Shared so a rename cannot leave
the enqueuer and the worker silently disagreeing."""


class QueueError(Exception):
    pass


class JobQueue(ABC):
    @abstractmethod
    async def enqueue_resume(self, resume_id: uuid.UUID, *, attempt: int = 0) -> None:
        """Arrange for `resume_id` to be parsed and extracted.

        `attempt` is the resume's attempt counter, used to tell one dispatch from
        the next. Passing the same one twice is how a duplicate upload is
        recognised; passing a higher one is how a manual retry gets through.
        """

    async def aclose(self) -> None:  # noqa: B027 — nothing to close by default
        """Release any connection held. Safe to call more than once."""


class InlineQueue(JobQueue):
    """Run the job here and now.

    Not a stub: this is the supported no-Redis configuration, and it is what lets
    a fresh clone and the whole test suite run without a server.

    One thing it cannot do is retry. There is nowhere to defer work to, and
    sleeping through a backoff would hold the upload request open for the length
    of it. A retryable failure therefore leaves the resume `pending` with the
    reason recorded, and re-uploading the file picks it up again. Deployments that
    need the retry policy run the ARQ worker, which is the point of it.
    """

    def __init__(self, context: JobContext) -> None:
        self._context = context

    async def enqueue_resume(self, resume_id: uuid.UUID, *, attempt: int = 0) -> None:
        outcome = await run_resume_job(self._context, resume_id)
        if outcome.should_retry:
            logger.warning(
                "resume %s: needs a retry, but the inline queue cannot defer work. "
                "It stays pending; re-upload it, or run the ARQ worker.",
                resume_id,
            )


class ArqQueue(JobQueue):
    """Hand the job to an ARQ worker over Redis."""

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, settings: Settings) -> ArqQueue:
        return cls(await create_pool(RedisSettings.from_dsn(settings.redis_url)))

    async def enqueue_resume(self, resume_id: uuid.UUID, *, attempt: int = 0) -> None:
        # `_job_id` makes the enqueue idempotent: ARQ refuses a second job with an
        # id already queued, running or recently finished, so a duplicate upload
        # cannot put the same resume on the queue twice. The attempt counter is in
        # the id because that refusal outlives the job — without it a manual retry
        # would be rejected as a duplicate of the run it is meant to replace.
        job = await self._pool.enqueue_job(
            PROCESS_RESUME_TASK, str(resume_id), _job_id=f"resume:{resume_id}:{attempt}"
        )
        if job is None:
            logger.info("resume %s: already queued, not enqueued again", resume_id)
            return
        logger.info("resume %s: queued as job %s", resume_id, job.job_id)

    async def aclose(self) -> None:
        await self._pool.aclose()


async def build_queue(settings: Settings, context: JobContext) -> JobQueue:
    match settings.queue_backend:
        case QueueBackend.INLINE:
            return InlineQueue(context)
        case QueueBackend.ARQ:
            return await ArqQueue.connect(settings)
