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

That policy covers a job that *fails*. A job whose worker simply stops — power
loss, OOM, a killed container — never gets to fail, and leaves its row at
`processing` where nothing will touch it again. `reclaim_stalled` at the bottom of
this module is the sweep for those, and it deliberately routes them through the
same `decide_retry` rather than a policy of its own.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.llm.base import LLMConfigError, LLMError, StructuredExtractor
from app.models import Job, Resume, ResumeStatus, Screening, ScreeningStatus
from app.models.base import utcnow
from app.pipeline.ocr import OCREngine, OCRError, OCRUnavailableError
from app.pipeline.parse import ParseError
from app.services import resume_service, screening_service
from app.services.screening_service import NotScreenable
from app.storage import ObjectNotFoundError, Storage

if TYPE_CHECKING:
    # Import-time only: `app.queue` imports this module, so the runtime dependency
    # runs one way — the queue calls a job. The reaper is the one job that has to
    # put work *back* on the queue, and it does it through this seam rather than by
    # reversing that direction. Same trick the two services already use.
    from app.queue import JobQueue

logger = logging.getLogger(__name__)

# Statuses a job will not touch. `processing` is here so a second delivery of the
# same resume cannot run alongside the first.
_NOT_OURS_TO_RUN = frozenset({ResumeStatus.EXTRACTED, ResumeStatus.PROCESSING})


class WorkerVanished(Exception):
    """A row was left at `processing` by a worker that never came back.

    Not a fact about the document, so `is_retryable` treats it as transient by
    simply not being on the permanent whitelist — and its message is written right
    here, which is why it is safe to quote (`_SAFE_TO_QUOTE`).
    """


@dataclass(slots=True)
class JobContext:
    """Everything a job needs, built once per process rather than per job."""

    sessionmaker: async_sessionmaker[AsyncSession]
    storage: Storage
    extractor: StructuredExtractor
    settings: Settings
    ocr: OCREngine | None = None
    """None means OCR is off, which is the default everywhere without a Tesseract."""

    queue: JobQueue | None = None
    """Only the reaper needs it: reclaiming a row means putting work back on the
    queue, where every other job here only takes work off it. `None` means a
    reclaimed row is recorded but not re-dispatched, which is what the tests and
    the inline queue get."""


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
    # The document cannot be parsed, the file is gone, or the provider or OCR
    # engine is misconfigured. None of those change on their own — a missing
    # Tesseract will still be missing in five seconds, and `POST /retry` is the
    # path once the configuration is fixed.
    return not isinstance(
        error,
        ParseError | ObjectNotFoundError | LLMConfigError | OCRUnavailableError | NotScreenable,
    )


def backoff_seconds(settings: Settings, *, failures: int) -> float:
    """Exponential backoff on the number of consecutive failures: 5s, 10s, 20s."""
    return float(settings.job_retry_base_seconds * 2 ** max(failures - 1, 0))


# Errors whose messages this codebase writes, so they are safe to store and log.
# Anything else may quote arbitrary data — a DBAPIError embeds the failing
# statement's parameters, `document_text` included — so only its type name is
# kept. `ObjectNotFoundError` is deliberately not here: its message carries the
# storage key (candidate id + content hash), and the job already records a
# friendly reason before raising it. `OCRUnavailableError` is: it names a binary
# and a setting, never document text, and quoting it is what makes the failure
# actionable instead of a bare type name. `NotScreenable` is too — its message is
# an instruction to the user ("process the resume first"), written right here.
_SAFE_TO_QUOTE = (LLMError, ParseError, OCRUnavailableError, NotScreenable, WorkerVanished)


def _describe(error: Exception) -> str:
    """A failure description that can never contain resume text."""
    if isinstance(error, _SAFE_TO_QUOTE):
        return f"{type(error).__name__}: {error}"
    return type(error).__name__


class RetryVerdict(StrEnum):
    """What the policy decided, in terms no particular row understands.

    Deliberately not a status. `Resume` and `Screening` keep their own status enums
    — a screening is never `parsed` or `extracted` — so the shared policy answers in
    intents and each job maps the intent onto its own vocabulary. Sharing the enum
    instead would have meant one table's states leaking into the other's.
    """

    PERMANENT = "permanent"
    """Stop. Failing again would fail the same way."""

    RETRY = "retry"
    """Go back to pending and try again after the delay."""

    EXHAUSTED = "exhausted"
    """The budget is spent. Dead-letter it so a human can replay it."""


@dataclass(frozen=True, slots=True)
class RetryDecision:
    verdict: RetryVerdict
    reason: str
    """PII-safe, and already worded for the row's `failure_reason`. For
    `PERMANENT` it is the bare description, because the caller may already hold a
    better one written by the code that knew what went wrong."""

    outcome: JobOutcome


def decide_retry(error: Exception, *, failed_attempts: int, settings: Settings) -> RetryDecision:
    """The whole retry policy, as a pure function.

    Extracted so screening jobs share it rather than copy it. It touches no session
    and no row: give it an error and the count of consecutive failures *including*
    this one, and it answers what should happen. That is what lets the policy be
    tested exhaustively without a database, and what makes a second job type
    inherit it without a second chance to get backoff or dead-lettering subtly
    wrong.
    """
    reason = _describe(error)

    if not is_retryable(error):
        return RetryDecision(verdict=RetryVerdict.PERMANENT, reason=reason, outcome=DONE)

    if failed_attempts >= settings.job_max_attempts:
        return RetryDecision(
            verdict=RetryVerdict.EXHAUSTED,
            reason=f"Gave up after {failed_attempts} attempts. Last error — {reason}",
            outcome=DONE,
        )

    delay = backoff_seconds(settings, failures=failed_attempts)
    return RetryDecision(
        verdict=RetryVerdict.RETRY,
        reason=f"Attempt {failed_attempts} failed, retrying — {reason}",
        outcome=JobOutcome(retry_after_seconds=delay),
    )


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
                ocr=context.ocr,
            )

            resume.failed_attempts = 0
            # Inside the try on purpose: a commit can fail too (the incident that
            # proved it was Postgres refusing a NUL in `document_text`), and a
            # persistence failure must go through the retry policy like any other
            # unexpected error — not escape and strand the row at `processing`.
            await session.commit()
        except (LLMError, ParseError, ObjectNotFoundError, OCRError) as exc:
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
    """Apply `decide_retry` to a resume row and commit the decision."""
    resume.failed_attempts += 1
    decision = decide_retry(error, failed_attempts=resume.failed_attempts, settings=settings)

    match decision.verdict:
        case RetryVerdict.PERMANENT:
            # `process_resume` already wrote a reason for the failures it knows how
            # to describe; only fill one in when it did not.
            resume.status = ResumeStatus.FAILED
            resume.failure_reason = resume.failure_reason or decision.reason
            await session.commit()
            logger.warning("resume %s: failed permanently (%s)", resume.id, type(error).__name__)

        case RetryVerdict.EXHAUSTED:
            resume.status = ResumeStatus.DEAD_LETTERED
            resume.failure_reason = decision.reason
            await session.commit()
            logger.error(
                "resume %s: dead-lettered after %d attempts (%s)",
                resume.id,
                resume.failed_attempts,
                type(error).__name__,
            )

        case RetryVerdict.RETRY:
            resume.status = ResumeStatus.PENDING
            resume.failure_reason = decision.reason
            await session.commit()
            logger.warning(
                "resume %s: attempt %d failed (%s), retrying in %.0fs",
                resume.id,
                resume.failed_attempts,
                type(error).__name__,
                decision.outcome.retry_after_seconds or 0.0,
            )

    return decision.outcome


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


# --------------------------------------------------------------------------- #
# Screening: the second job type. Same policy, different row.
# --------------------------------------------------------------------------- #

_SCREENING_NOT_OURS_TO_RUN = frozenset({ScreeningStatus.PROCESSING})
"""Only `processing`, unlike a resume's set.

`completed` is missing on purpose. A resume that is `extracted` refuses to run
again because redoing it would bill a second call for a profile we already have; a
screening's requirements can *change*, and re-running it against the new ones is
the whole point. `screening_service.request_screening` is what decides whether
there is anything new to ask — by then the work has been queued deliberately.
"""


async def run_screening_job(context: JobContext, screening_id: uuid.UUID) -> JobOutcome:
    """Judge one resume against one job, committing the outcome and the job state."""
    async with context.sessionmaker() as session:
        claimed = await _claim_screening(session, screening_id)
        if claimed is None:
            return DONE
        screening, job, resume = claimed

        try:
            await screening_service.process_screening(
                session,
                screening=screening,
                job=job,
                resume=resume,
                extractor=context.extractor,
                settings=context.settings,
            )

            screening.failed_attempts = 0
            # Inside the try for the same reason `run_resume_job` does it: a commit
            # can fail, and a persistence failure must go through the policy rather
            # than escape and strand the row at `processing`.
            await session.commit()
        except (LLMError, NotScreenable) as exc:
            # Raised by pipeline code, never by the database, so the session is
            # still usable and the failure commits on it.
            return await _record_screening_failure(session, screening, exc, context.settings)
        except Exception as exc:
            await session.rollback()
            return await _record_screening_failure_on_a_fresh_session(context, screening_id, exc)

        return DONE


async def _claim_screening(
    session: AsyncSession, screening_id: uuid.UUID
) -> tuple[Screening, Job, Resume] | None:
    """Mark the screening as ours and load what judging needs, or explain the skip.

    The job comes back with its requirements eagerly loaded: rendering them happens
    after the claim commits, and a lazy load on an async session at that point is an
    error rather than a query — the shape that produced slice 1's `MissingGreenlet`.
    """
    screening = await session.get(Screening, screening_id, with_for_update=True)
    if screening is None:
        logger.warning("screening %s: queued but no longer exists", screening_id)
        return None

    if screening.status in _SCREENING_NOT_OURS_TO_RUN:
        logger.info("screening %s: already %s, skipping", screening_id, screening.status)
        await session.rollback()
        return None

    job = (
        await session.execute(
            select(Job).where(Job.id == screening.job_id).options(selectinload(Job.requirements))
        )
    ).scalar_one_or_none()
    resume = await session.get(Resume, screening.resume_id)

    if job is None or resume is None:
        # Deleted between request and pickup. Nothing to do, and nothing wrong.
        logger.warning("screening %s: its job or resume is gone", screening_id)
        await session.rollback()
        return None

    screening.status = ScreeningStatus.PROCESSING
    screening.attempts += 1
    screening.last_attempt_at = utcnow()
    await session.commit()
    return screening, job, resume


async def _record_screening_failure(
    session: AsyncSession, screening: Screening, error: Exception, settings: Settings
) -> JobOutcome:
    """Apply `decide_retry` to a screening row and commit the decision."""
    screening.failed_attempts += 1
    decision = decide_retry(error, failed_attempts=screening.failed_attempts, settings=settings)

    match decision.verdict:
        case RetryVerdict.PERMANENT:
            screening.status = ScreeningStatus.FAILED
        case RetryVerdict.EXHAUSTED:
            screening.status = ScreeningStatus.DEAD_LETTERED
        case RetryVerdict.RETRY:
            screening.status = ScreeningStatus.PENDING

    screening.failure_reason = decision.reason
    await session.commit()
    logger.warning(
        "screening %s: attempt %d %s (%s)",
        screening.id,
        screening.failed_attempts,
        decision.verdict,
        type(error).__name__,
    )
    return decision.outcome


async def _record_screening_failure_on_a_fresh_session(
    context: JobContext, screening_id: uuid.UUID, error: Exception
) -> JobOutcome:
    logger.error("screening %s: unexpected job failure (%s)", screening_id, type(error).__name__)
    async with context.sessionmaker() as session:
        screening = await session.get(Screening, screening_id)
        if screening is None:
            return DONE
        return await _record_screening_failure(session, screening, error, context.settings)


# --------------------------------------------------------------------------- #
# The reaper: rows a worker claimed and never came back to.
# --------------------------------------------------------------------------- #

_VANISHED = "the worker stopped before it finished"


def _as_utc(moment: datetime) -> datetime:
    """Read a stored timestamp as the UTC it was written as.

    SQLite's `DATETIME` storage format has no timezone field, so `last_attempt_at`
    comes back **naive** there while `utcnow()` is aware, and comparing the two
    raises rather than answering wrongly. Everything this codebase writes is UTC, so
    attaching UTC to a naive value is decoding it, not guessing at it. Postgres
    returns an aware value and this is a no-op.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def is_stalled(
    claimed_at: datetime | None, *, timeout_seconds: float, now: datetime | None = None
) -> bool:
    """Whether a row has been held at `processing` longer than a live worker would.

    `None` counts as stalled. The claim writes `last_attempt_at` in the same commit
    that writes `processing`, so a row in that state without one cannot be held by
    anything currently running — and leaving it there is the exact failure this
    function exists to end.
    """
    if claimed_at is None:
        return True
    return _as_utc(claimed_at) <= (now or utcnow()) - timedelta(seconds=timeout_seconds)


@dataclass(frozen=True, slots=True)
class StalledRows:
    """What one candidate query found. Ids only — the rows are re-read under a lock."""

    resumes: tuple[uuid.UUID, ...] = ()
    screenings: tuple[uuid.UUID, ...] = ()

    def __len__(self) -> int:
        return len(self.resumes) + len(self.screenings)


async def find_stalled(context: JobContext, *, now: datetime | None = None) -> StalledRows:
    """Which rows look abandoned. Deliberately only *looks*.

    Split from the reclaim because the two cannot share a transaction: reclaiming
    commits, which drops whatever locks this query took, so by the second row the
    rest of the list is unguarded anyway. Naming the split is better than pretending
    it is not there — every id here is a candidate whose claim may already have moved
    on, which is why `reclaim_resume` and `reclaim_screening` re-test it under a lock
    rather than trusting this list.
    """
    cutoff = (now or utcnow()) - timedelta(seconds=context.settings.job_visibility_timeout_seconds)
    async with context.sessionmaker() as session:
        resumes = (
            await session.execute(
                select(Resume.id).where(
                    Resume.status == ResumeStatus.PROCESSING,
                    or_(Resume.last_attempt_at.is_(None), Resume.last_attempt_at <= cutoff),
                )
            )
        ).scalars()
        screenings = (
            await session.execute(
                select(Screening.id).where(
                    Screening.status == ScreeningStatus.PROCESSING,
                    or_(Screening.last_attempt_at.is_(None), Screening.last_attempt_at <= cutoff),
                )
            )
        ).scalars()
        return StalledRows(resumes=tuple(resumes), screenings=tuple(screenings))


async def reclaim_resume(
    context: JobContext, resume_id: uuid.UUID, *, now: datetime | None = None
) -> bool:
    """Reclaim one listed resume, or answer False because it no longer qualifies.

    The re-test under the lock is the whole point of this function existing on its
    own. Between `find_stalled` listing an id and this running, the row can stop
    being abandoned — a `POST /retry` moves it to `pending`, and a worker picking
    that up writes a *fresh* claim. Reclaiming then would spend the retry budget on
    a run that is alive and healthy, and enqueue a duplicate of it.
    """
    moment = now or utcnow()
    async with context.sessionmaker() as session:
        resume = await session.get(Resume, resume_id, with_for_update=True)
        if resume is None or resume.status is not ResumeStatus.PROCESSING:
            await session.rollback()
            return False
        if not is_stalled(
            resume.last_attempt_at,
            timeout_seconds=context.settings.job_visibility_timeout_seconds,
            now=moment,
        ):
            await session.rollback()
            return False

        logger.warning("resume %s: stalled at processing, reclaiming", resume_id)
        outcome = await _record_failure(
            session, resume, WorkerVanished(_VANISHED), context.settings
        )
        attempts = resume.attempts

    # After the commit, never before — the same rule the upload path follows.
    if outcome.should_retry and context.queue is not None:
        await context.queue.enqueue_resume(resume_id, attempt=attempts)
    return True


async def reclaim_screening(
    context: JobContext, screening_id: uuid.UUID, *, now: datetime | None = None
) -> bool:
    """The screening twin. Same policy, same lock-and-re-test, different row."""
    moment = now or utcnow()
    async with context.sessionmaker() as session:
        screening = await session.get(Screening, screening_id, with_for_update=True)
        if screening is None or screening.status is not ScreeningStatus.PROCESSING:
            await session.rollback()
            return False
        if not is_stalled(
            screening.last_attempt_at,
            timeout_seconds=context.settings.job_visibility_timeout_seconds,
            now=moment,
        ):
            await session.rollback()
            return False

        logger.warning("screening %s: stalled at processing, reclaiming", screening_id)
        outcome = await _record_screening_failure(
            session, screening, WorkerVanished(_VANISHED), context.settings
        )
        attempts = screening.attempts

    if outcome.should_retry and context.queue is not None:
        await context.queue.enqueue_screening(screening_id, attempt=attempts)
    return True


async def reclaim_stalled(context: JobContext, *, now: datetime | None = None) -> int:
    """Put rows a dead worker was holding back on the queue. Returns how many moved.

    A worker that dies mid-job — power loss, OOM, `docker kill` — leaves its row at
    `processing`, and every road out is closed: redelivery skips it (`processing` is
    in `_NOT_OURS_TO_RUN`), `POST /retry` used to answer 409, and re-uploading the
    same bytes dedupes to it. This is the sweep that reopens one.

    **It goes through the existing retry policy rather than a second one**, which is
    the load-bearing part. Reclaiming counts against `failed_attempts` like any other
    failure, so a row that keeps killing its worker — a scan large enough to exhaust
    memory, say — dead-letters after the budget instead of looping reap → requeue →
    die forever. That loop is the failure mode a reaper introduces, and inheriting
    `decide_retry` is what forecloses it.

    Reaping a worker that is merely slow is not a correctness problem, only wasted
    work: if the original finishes afterwards it commits `extracted`, and the fresh
    dispatch's `_claim` sees that in `_NOT_OURS_TO_RUN` and skips. The generous
    default timeout is there to make it rare rather than to make it safe.
    """
    moment = now or utcnow()
    stalled = await find_stalled(context, now=moment)

    resumes = 0
    for resume_id in stalled.resumes:
        resumes += await reclaim_resume(context, resume_id, now=moment)
    screenings = 0
    for screening_id in stalled.screenings:
        screenings += await reclaim_screening(context, screening_id, now=moment)

    total = resumes + screenings
    if total:
        logger.warning(
            "reclaimed %d row(s) stalled beyond %.0fs: %d resume(s), %d screening(s)",
            total,
            context.settings.job_visibility_timeout_seconds,
            resumes,
            screenings,
        )
    return total
