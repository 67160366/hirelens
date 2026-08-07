"""The unit of background work: parse and extract one stored resume.

`resume_service.process_resume` was written to be called from a job — it takes no
HTTP types and does not commit. This module is the shell that gives it a session,
the stored bytes, a transaction boundary, and the retry policy.

Nothing here imports arq. The job decides *whether* to retry and *when*; the
worker entrypoint (`app/worker.py`) is what turns that decision into arq's
`Retry`. Keeping the two apart is what lets the tests exercise the whole policy
without Redis, and what lets the inline queue run the same code.

The policy in one paragraph: a worker claims the resume (`processing`, attempt
counters bumped), runs the pipeline, and on failure asks whether the error is
worth retrying. Transient ones — the model unreachable, a reply that did not
parse, anything unexpected — go back to `pending` with exponential backoff until
the budget runs out, at which point the resume is dead-lettered so a human can
replay it. Permanent ones — a scanned PDF, a missing key, a file that is gone —
fail immediately, because retrying them only fails the same way three times.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.llm.base import LLMConfigError, LLMError, StructuredExtractor
from app.models import Resume, ResumeStatus
from app.models.base import utcnow
from app.pipeline.parse import ParseError
from app.services import resume_service
from app.storage import ObjectNotFoundError, Storage

logger = logging.getLogger(__name__)

# Statuses a job will not touch. `processing` is here so a second delivery of the
# same resume cannot run alongside the first.
_NOT_OURS_TO_RUN = frozenset({ResumeStatus.EXTRACTED, ResumeStatus.PROCESSING})


@dataclass(slots=True)
class JobContext:
    """Everything a job needs, built once per process rather than per job."""

    sessionmaker: async_sessionmaker[AsyncSession]
    storage: Storage
    extractor: StructuredExtractor
    settings: Settings


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """What the caller should do next.

    A value rather than an exception so the decision is testable on its own and
    `app/worker.py` stays the only place that knows arq exists.
    """

    retry_after_seconds: float | None = None

    @property
    def should_retry(self) -> bool:
        return self.retry_after_seconds is not None


DONE = JobOutcome()


def is_retryable(error: BaseException) -> bool:
    """Whether failing again in a few seconds might produce a different result.

    Deliberately a whitelist of *permanent* errors rather than of transient ones:
    an unrecognised failure is more likely to be a blip than a fact about the
    document, and a wrong retry costs seconds while a wrong give-up loses work.
    """
    # The document cannot be parsed, the file is gone, or the provider is
    # misconfigured. None of those change on their own.
    return not isinstance(error, ParseError | ObjectNotFoundError | LLMConfigError)


def backoff_seconds(settings: Settings, *, failures: int) -> float:
    """Exponential backoff on the number of consecutive failures: 5s, 10s, 20s."""
    return float(settings.job_retry_base_seconds * 2 ** max(failures - 1, 0))


# Errors whose messages this codebase writes, so they are safe to store and log.
# Anything else may quote arbitrary data — a DBAPIError embeds the failing
# statement's parameters, `document_text` included — so only its type name is
# kept. `ObjectNotFoundError` is deliberately not here: its message carries the
# storage key (candidate id + content hash), and the job already records a
# friendly reason before raising it.
_SAFE_TO_QUOTE = (LLMError, ParseError)


def _describe(error: Exception) -> str:
    """A failure description that can never contain resume text."""
    if isinstance(error, _SAFE_TO_QUOTE):
        return f"{type(error).__name__}: {error}"
    return type(error).__name__


async def run_resume_job(context: JobContext, resume_id: uuid.UUID) -> JobOutcome:
    """Parse and extract one resume, committing the outcome and the job state."""
    async with context.sessionmaker() as session:
        resume = await _claim(session, resume_id)
        if resume is None:
            return DONE

        try:
            try:
                data = await context.storage.get(resume.storage_key)
            except ObjectNotFoundError:
                # Said in the user's terms. The raw error carries the storage key,
                # which embeds the candidate id and the file's content hash.
                resume.failure_reason = "The stored file is missing."
                raise

            await resume_service.process_resume(
                session,
                resume=resume,
                data=data,
                extractor=context.extractor,
                settings=context.settings,
            )

            resume.failed_attempts = 0
            # Inside the try on purpose: a commit can fail too (the incident that
            # proved it was Postgres refusing a NUL in `document_text`), and a
            # persistence failure must go through the retry policy like any other
            # unexpected error — not escape and strand the row at `processing`.
            await session.commit()
        except (LLMError, ParseError, ObjectNotFoundError) as exc:
            # Raised by pipeline and storage code, never by the database, so the
            # session is still usable and whatever `process_resume` recorded
            # before failing — the parsed text above all — commits with the
            # failure bookkeeping. A retry then skips straight to extraction.
            return await _record_failure(session, resume, exc, context.settings)
        except Exception as exc:
            # Anything else may have come from the database, which leaves the
            # session unusable. Start clean and record the failure alone.
            await session.rollback()
            return await _record_failure_on_a_fresh_session(context, resume_id, exc)

        return DONE


async def _claim(session: AsyncSession, resume_id: uuid.UUID) -> Resume | None:
    """Mark the resume as ours and count the attempt, or explain why we skipped.

    The row lock closes the window in which two deliveries of the same resume both
    read `pending` and both start work. SQLite has no row locks and the tests run
    single-threaded, so this matters on Postgres, which is where it will run.
    """
    resume = await session.get(Resume, resume_id, with_for_update=True)
    if resume is None:
        # Deleted between enqueue and pickup. Nothing to do, and nothing wrong —
        # failing the job would only queue work that can never succeed.
        logger.warning("resume %s: queued but no longer exists", resume_id)
        return None

    if resume.status in _NOT_OURS_TO_RUN:
        logger.info("resume %s: already %s, skipping", resume_id, resume.status)
        await session.rollback()
        return None

    resume.status = ResumeStatus.PROCESSING
    resume.attempts += 1
    resume.last_attempt_at = utcnow()
    await session.commit()
    return resume


async def _record_failure(
    session: AsyncSession, resume: Resume, error: Exception, settings: Settings
) -> JobOutcome:
    """Decide retry, dead-letter or permanent failure, and commit the decision."""
    resume.failed_attempts += 1
    reason = _describe(error)

    if not is_retryable(error):
        # `process_resume` already wrote a reason for the failures it knows how to
        # describe; only fill one in when it did not.
        resume.status = ResumeStatus.FAILED
        resume.failure_reason = resume.failure_reason or reason
        await session.commit()
        logger.warning("resume %s: failed permanently (%s)", resume.id, type(error).__name__)
        return DONE

    if resume.failed_attempts >= settings.job_max_attempts:
        resume.status = ResumeStatus.DEAD_LETTERED
        resume.failure_reason = (
            f"Gave up after {resume.failed_attempts} attempts. Last error — {reason}"
        )
        await session.commit()
        logger.error(
            "resume %s: dead-lettered after %d attempts (%s)",
            resume.id,
            resume.failed_attempts,
            type(error).__name__,
        )
        return DONE

    delay = backoff_seconds(settings, failures=resume.failed_attempts)
    resume.status = ResumeStatus.PENDING
    resume.failure_reason = f"Attempt {resume.failed_attempts} failed, retrying — {reason}"
    await session.commit()
    logger.warning(
        "resume %s: attempt %d failed (%s), retrying in %.0fs",
        resume.id,
        resume.failed_attempts,
        type(error).__name__,
        delay,
    )
    return JobOutcome(retry_after_seconds=delay)


async def _record_failure_on_a_fresh_session(
    context: JobContext, resume_id: uuid.UUID, error: Exception
) -> JobOutcome:
    """Record a failure after a rollback, where the resume has to be re-read."""
    # Type name only, no traceback: the exception message can quote statement
    # parameters — resume text included — and resumes are PII.
    logger.error("resume %s: unexpected job failure (%s)", resume_id, type(error).__name__)
    async with context.sessionmaker() as session:
        resume = await session.get(Resume, resume_id)
        if resume is None:
            return DONE
        return await _record_failure(session, resume, error, context.settings)
