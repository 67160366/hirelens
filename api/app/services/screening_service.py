"""Screen one resume against one job: request it, then do the work.

Shaped like `resume_service`, and split the same way. The request does the cheap
part — find or create the row, commit, queue — and `process_screening` does the
slow half from a worker. It takes no HTTP types and does not commit, so the caller
owns the transaction boundary either way.

The one thing worth reading twice is how the document is rebuilt. Judging resolves
a *new* quote against text that was parsed long ago, so it uses
`ParsedDocument.from_stored(resume.document_text, resume.page_spans)` — never
`reparse_document`, which goes back to the file and, under a different OCR
configuration, can shift every offset after a rescued page. Nothing here reads the
stored file at all.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.base import LLMError, StructuredExtractor
from app.models import Job, LLMCallLog, Resume, Screening, ScreeningStatus
from app.pipeline.judge import JudgmentOutcome, judge_requirements, requirements_fingerprint
from app.pipeline.parse import ParsedDocument
from app.pipeline.prompts import JUDGMENT_PROMPT_VERSION
from app.pipeline.ranking import ScreeningView
from app.schemas.judgment import Judgment, RequirementSpec

if TYPE_CHECKING:
    # Import-time only, for the same reason `resume_service` does it: `app.queue`
    # reaches back here through `app.jobs`, and the dependency that matters runs
    # one way — the queue calls the service.
    from app.queue import JobQueue

# Resumes are PII: log ids, counts and durations, never document text.
logger = logging.getLogger(__name__)


class NotScreenable(Exception):
    """The resume cannot be judged, and no retry will change that.

    Distinct from an `LLMError` so `jobs.is_retryable` treats it as permanent: a
    resume with no extracted text has nothing to quote, and asking a model about it
    would spend a call to be told nothing.
    """


def requirement_specs(job: Job) -> list[RequirementSpec]:
    """The job's requirements as the pipeline sees them, in prompt order.

    This is the seam that keeps `pipeline/judge.py` free of the ORM: rows go in,
    plain value objects come out, and the pipeline never learns a database exists.
    """
    return [
        RequirementSpec(
            id=str(item.id),
            label=item.label,
            kind=str(item.kind),
            detail=item.detail,
            must_have=item.must_have,
            weight=item.weight,
        )
        for item in sorted(job.requirements, key=lambda item: (item.position, item.created_at))
    ]


def screening_view(screening: Screening) -> ScreeningView:
    """A screening as `pipeline/ranking.py` sees it.

    The second seam of the same kind as `requirement_specs`: rows go in, plain value
    objects come out, and ranking never learns a database exists.
    """
    return ScreeningView(
        id=str(screening.id),
        resume_id=str(screening.resume_id),
        status=str(screening.status),
        completed=screening.status is ScreeningStatus.COMPLETED,
        requirements_hash=screening.requirements_hash,
        prompt_version=screening.prompt_version,
        judgment=_stored_judgment(screening),
    )


def _stored_judgment(screening: Screening) -> Judgment | None:
    """The stored result rebuilt, or `None` when there is no usable one.

    Anything `_record_result` wrote validates. Answering `None` instead of raising
    keeps one unreadable row from failing a whole ranking request — `rank_screenings`
    reports it as `malformed`, which is the honest outcome for a row nobody can
    interpret.
    """
    if screening.result is None:
        return None
    try:
        return Judgment.model_validate(screening.result)
    except ValidationError:
        # No document text in a validation error for this shape, but log the id
        # only regardless — the rule is the same everywhere in this package.
        logger.warning("screening %s: stored result did not validate", screening.id)
        return None


async def find_screening(
    session: AsyncSession, *, job_id: uuid.UUID, resume_id: uuid.UUID
) -> Screening | None:
    result = await session.execute(
        select(Screening).where(Screening.job_id == job_id, Screening.resume_id == resume_id)
    )
    return result.scalar_one_or_none()


async def request_screening(
    session: AsyncSession,
    *,
    job: Job,
    resume: Resume,
    queue: JobQueue,
    force: bool = False,
) -> tuple[Screening, bool]:
    """Find or create the screening for this pair and queue it if it needs running.

    Returns the row and whether work was queued. Idempotent in the way an upload is:
    asking twice for a screening that is already current does not spend a second
    model call. It *is* re-queued when the result is stale — the requirements or the
    prompt changed since it ran — or when the last attempt failed.
    """
    fingerprint = requirements_fingerprint(requirement_specs(job))

    screening = await find_screening(session, job_id=job.id, resume_id=resume.id)
    if screening is None:
        screening = Screening(job_id=job.id, resume_id=resume.id, status=ScreeningStatus.PENDING)
        session.add(screening)
        try:
            await session.commit()
        except IntegrityError:
            # Two requests raced past the lookup; the loser's INSERT hit
            # uq_screenings_job_resume. Hand back the winner's row.
            await session.rollback()
            existing = await find_screening(session, job_id=job.id, resume_id=resume.id)
            if existing is None:
                raise
            screening = existing
        else:
            # After the commit, never before: the worker looks the row up by id.
            await queue.enqueue_screening(screening.id, attempt=screening.attempts)
            return screening, True

    if not force and not _needs_running(screening, fingerprint):
        logger.info("screening %s: already current, not re-queued", screening.id)
        return screening, False

    screening.status = ScreeningStatus.PENDING
    screening.failed_attempts = 0
    screening.failure_reason = None
    await session.commit()

    await queue.enqueue_screening(screening.id, attempt=screening.attempts)
    return screening, True


def _needs_running(screening: Screening, fingerprint: str) -> bool:
    if screening.status is ScreeningStatus.PROCESSING:
        # A worker holds it. Re-queueing would be asking for the same work twice.
        return False
    if screening.status is ScreeningStatus.COMPLETED:
        return screening.is_stale(
            requirements_hash=fingerprint, prompt_version=JUDGMENT_PROMPT_VERSION
        )
    # pending, failed or dead-lettered: there is no current answer.
    return True


async def process_screening(
    session: AsyncSession,
    *,
    screening: Screening,
    job: Job,
    resume: Resume,
    extractor: StructuredExtractor,
    settings: Settings,
) -> None:
    """Judge the resume against the job, recording the outcome on the row.

    Does not commit — the caller owns the transaction boundary. This is the half the
    worker calls (`app/jobs.py`).
    """
    if not resume.document_text:
        # Nothing to quote. A model asked about an empty document can only answer
        # "nothing", and it would be billed for saying so.
        raise NotScreenable(
            "This resume has no extracted text yet. Process the resume first, then screen it."
        )

    requirements = requirement_specs(job)
    document = ParsedDocument.from_stored(
        resume.document_text,
        resume.page_spans,
        pages_without_text=resume.pages_without_text or (),
        pages_from_ocr=resume.pages_from_ocr or (),
    )

    try:
        outcome = await judge_requirements(
            document, requirements, extractor, max_attempts=settings.judgment_max_attempts
        )
    except LLMError as exc:
        logger.warning("screening %s: judging failed (%s)", screening.id, type(exc).__name__)
        raise

    _record_usage(session, screening=screening, outcome=outcome)
    _record_result(session, screening=screening, outcome=outcome, requirements=requirements)

    judgment = outcome.judgment
    logger.info(
        "screening %s: %d/%d met — %d verified, %d dropped (%.1f%% unverifiable), "
        "%d attempt(s), %d ms",
        screening.id,
        judgment.met_count,
        len(judgment.requirements),
        judgment.stats.verified,
        judgment.stats.dropped,
        judgment.stats.hallucination_rate * 100,
        judgment.stats.attempts,
        outcome.total_latency_ms,
    )


def _record_usage(session: AsyncSession, *, screening: Screening, outcome: JudgmentOutcome) -> None:
    for attempt, usage in enumerate(outcome.usages, start=1):
        session.add(
            LLMCallLog(
                screening_id=screening.id,
                provider=usage.provider,
                model=usage.model,
                # The judging prompt, not the extraction one: with a single version
                # column for both, comparing prompt revisions would be meaningless.
                prompt_version=JUDGMENT_PROMPT_VERSION,
                attempt=attempt,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                latency_ms=usage.latency_ms,
                cost_usd=usage.cost_usd,
            )
        )


def _record_result(
    session: AsyncSession,
    *,
    screening: Screening,
    outcome: JudgmentOutcome,
    requirements: list[RequirementSpec],
) -> None:
    judgment = outcome.judgment
    screening.result = judgment.model_dump(mode="json")
    screening.requirements_hash = requirements_fingerprint(requirements)
    screening.prompt_version = JUDGMENT_PROMPT_VERSION
    screening.requirements_met = judgment.met_count
    screening.requirements_total = len(judgment.requirements)
    screening.claims_verified = judgment.stats.verified
    screening.claims_dropped = judgment.stats.dropped
    screening.hallucination_rate = judgment.stats.hallucination_rate
    screening.status = ScreeningStatus.COMPLETED
    screening.failure_reason = None
