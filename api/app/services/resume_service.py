"""Ingest a resume: store it, record it, and hand the slow half to the queue.

The request does the fast, cheap part — hash, store, insert — and returns a
`pending` resume. Parsing and extraction happen in `process_resume`, which the
queue calls from a worker process (`app/jobs.py`); it takes no HTTP types and does
not commit, so the caller owns the transaction boundary either way.

Failures are recorded on the row instead of thrown away. A scanned PDF or an
unreachable model leaves a resume in a state that explains itself and can be
retried, which is what the journey's "no silent failure" requirement asks for.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.base import LLMError, StructuredExtractor
from app.models import Candidate, ExtractedProfileRow, LLMCallLog, Resume, ResumeStatus
from app.models.base import utcnow
from app.pipeline.extract import ExtractionOutcome, extract_profile
from app.pipeline.ocr import OCREngine
from app.pipeline.parse import ParsedDocument, ParseError, parse_document_bytes
from app.pipeline.prompts import EXTRACTION_PROMPT_VERSION
from app.storage import Storage, build_storage_key, content_hash

if TYPE_CHECKING:
    # Import-time only: `app.queue` reaches back here through `app.jobs`, and the
    # dependency that matters runs one way — the queue calls the service.
    from app.queue import JobQueue

# Resumes are PII: log ids, sizes and counts, never document text or filenames.
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestResult:
    resume: Resume
    created: bool
    """False when the same bytes were already uploaded — the request was a no-op."""


async def find_by_content(
    session: AsyncSession, *, candidate_id: uuid.UUID, digest: str
) -> Resume | None:
    result = await session.execute(
        select(Resume).where(Resume.candidate_id == candidate_id, Resume.content_hash == digest)
    )
    return result.scalar_one_or_none()


async def ingest_resume(
    session: AsyncSession,
    *,
    candidate: Candidate,
    filename: str,
    data: bytes,
    storage: Storage,
    queue: JobQueue,
    consent_version: str,
) -> IngestResult:
    """Store one upload and queue it for processing. Idempotent on content hash.

    `consent_version` is stamped on the row. A duplicate upload keeps the *original*
    consent rather than refreshing it: the agreement that matters is the one made
    when the document first arrived, and re-stamping it would quietly rewrite when
    somebody agreed to what.
    """
    digest = content_hash(data)

    existing = await find_by_content(session, candidate_id=candidate.id, digest=digest)
    if existing is not None:
        # Same bytes, same result. Re-running extraction would spend money to
        # produce what we already have.
        logger.info("resume %s: duplicate upload deduplicated", existing.id)
        await _requeue_if_stalled(existing, queue)
        return IngestResult(resume=existing, created=False)

    key = build_storage_key(candidate_id=str(candidate.id), digest=digest, filename=filename)
    await storage.put(key, data)

    resume = Resume(
        candidate_id=candidate.id,
        filename=filename,
        content_hash=digest,
        size_bytes=len(data),
        storage_key=key,
        status=ResumeStatus.PENDING,
        consented_at=utcnow(),
        consent_version=consent_version,
    )
    session.add(resume)
    try:
        await session.commit()
    except IntegrityError:
        # Two identical uploads racing: both passed the lookup above, the loser's
        # INSERT hit uq_resumes_candidate_content. Hand back the winner's row —
        # same bytes, same storage key, so nothing needs cleaning up.
        await session.rollback()
        existing = await find_by_content(session, candidate_id=candidate.id, digest=digest)
        if existing is None:
            raise
        logger.info("resume %s: lost a duplicate-upload race, returning the winner", existing.id)
        await _requeue_if_stalled(existing, queue)
        return IngestResult(resume=existing, created=False)
    except Exception:
        # The row rolls back with the transaction; remove the blob written above
        # so a failed request cannot strand an object no row points at. The key is
        # exclusively ours — an earlier upload of the same bytes would have been
        # deduplicated before reaching here.
        await session.rollback()
        await storage.delete(key)
        raise

    # After the commit, never before: the worker looks the row up by id, and a
    # fast worker would otherwise find nothing there.
    await queue.enqueue_resume(resume.id, attempt=resume.attempts)
    return IngestResult(resume=resume, created=True)


async def _requeue_if_stalled(resume: Resume, queue: JobQueue) -> None:
    """Re-queue a duplicate upload whose original never got processed.

    A resume sits at `pending` while it is queued, between retries, or because
    nothing was listening when it was enqueued. Re-uploading the file is what a
    user does when nothing seems to happen, and it must not dedupe to that row and
    leave it stuck. The queue refuses a dispatch it already holds, so this cannot
    queue the same attempt twice.

    Deliberately not extended to dead letters: replaying those is what
    `POST /resumes/{id}/retry` is for, and it should be a decision rather than a
    side effect of uploading the same file again.
    """
    if resume.status is ResumeStatus.PENDING:
        logger.info("resume %s: duplicate of a pending resume, re-queueing", resume.id)
        await queue.enqueue_resume(resume.id, attempt=resume.attempts)


async def requeue(session: AsyncSession, *, resume: Resume, queue: JobQueue) -> None:
    """Put a stopped resume back on the queue — the dead-letter replay path.

    Clears the retry budget but not `attempts`: the budget is what "three strikes"
    counts, while `attempts` keeps the total honest and gives this dispatch a queue
    job id distinct from the one that failed.
    """
    resume.status = ResumeStatus.PENDING
    resume.failed_attempts = 0
    resume.failure_reason = None
    await session.commit()

    await queue.enqueue_resume(resume.id, attempt=resume.attempts)
    logger.info("resume %s: requeued by request after %d attempt(s)", resume.id, resume.attempts)


async def process_resume(
    session: AsyncSession,
    *,
    resume: Resume,
    data: bytes,
    extractor: StructuredExtractor,
    settings: Settings,
    ocr: OCREngine | None = None,
) -> None:
    """Parse then extract, recording the outcome on the row.

    Does not commit — the caller owns the transaction boundary. This is the half
    the worker calls (`app/jobs.py`).

    Two kinds of failure, handled differently on purpose. A document that cannot
    be parsed is a fact about the document: the row is marked failed and the
    function returns, because no amount of retrying changes it. Extraction
    failures are raised instead, so the job can decide whether they are worth
    retrying — but only after the parsed text has been written to the row, which
    is still in the caller's transaction, so a retry skips straight to extraction.

    An OCR fault is neither, so it is left to propagate: it says the engine is
    misconfigured, not that this document is broken, and marking the row
    permanently failed would be a lie a `POST /retry` could not undo.
    """
    try:
        # Off the event loop: parsing is synchronous CPU work, and with OCR it is
        # roughly a second per page — long enough to stall the worker, and with it
        # every progress stream the API is serving.
        document = await asyncio.to_thread(
            parse_document_bytes, data, filename=resume.filename, ocr=ocr
        )
    except ParseError as exc:
        resume.status = ResumeStatus.FAILED
        resume.failure_reason = str(exc)
        logger.warning("resume %s: parse failed (%s)", resume.id, type(exc).__name__)
        return

    resume.page_count = document.page_count
    resume.pages_without_text = list(document.pages_without_text)
    resume.pages_from_ocr = list(document.pages_from_ocr)
    if document.used_ocr:
        logger.info(
            "resume %s: %d page(s) recovered by OCR", resume.id, len(document.pages_from_ocr)
        )
    # Stored verbatim: evidence offsets index into exactly this string, so
    # re-parsing later could invalidate every citation already shown to a user.
    resume.document_text = document.text
    # ...and the page boundaries measured over that same string, so a quote located
    # in it later can still name a page without anything being re-parsed.
    resume.page_spans = document.stored_page_spans
    resume.status = ResumeStatus.PARSED
    resume.failure_reason = None

    try:
        outcome = await extract_profile(
            document, extractor, max_attempts=settings.extraction_max_attempts
        )
    except LLMError as exc:
        logger.warning("resume %s: extraction failed (%s)", resume.id, type(exc).__name__)
        raise

    _record_usage(session, resume=resume, outcome=outcome)
    _record_profile(session, resume=resume, outcome=outcome)
    resume.status = ResumeStatus.EXTRACTED

    stats = outcome.profile.stats
    cost = outcome.total_cost_usd
    logger.info(
        "resume %s: extracted — %d verified, %d dropped (%.1f%% unverifiable), "
        "%d attempt(s), %d ms, cost %s",
        resume.id,
        stats.verified,
        stats.dropped,
        stats.hallucination_rate * 100,
        stats.attempts,
        outcome.total_latency_ms,
        f"${cost:.6f}" if cost is not None else "unknown",
    )


def _record_usage(session: AsyncSession, *, resume: Resume, outcome: ExtractionOutcome) -> None:
    for attempt, usage in enumerate(outcome.usages, start=1):
        session.add(
            LLMCallLog(
                resume_id=resume.id,
                provider=usage.provider,
                model=usage.model,
                prompt_version=EXTRACTION_PROMPT_VERSION,
                attempt=attempt,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                latency_ms=usage.latency_ms,
                cost_usd=usage.cost_usd,
            )
        )


def _record_profile(session: AsyncSession, *, resume: Resume, outcome: ExtractionOutcome) -> None:
    stats = outcome.profile.stats
    session.add(
        ExtractedProfileRow(
            resume_id=resume.id,
            profile=outcome.profile.model_dump(mode="json"),
            claims_verified=stats.verified,
            claims_dropped=stats.dropped,
            hallucination_rate=stats.hallucination_rate,
            attempts=stats.attempts,
        )
    )


async def reparse_document(
    resume: Resume, storage: Storage, *, ocr: OCREngine | None = None
) -> ParsedDocument:
    """Rebuild the parsed document for a resume from stored bytes.

    The result is **not** interchangeable with the stored `document_text`: pass the
    same OCR engine the original parse used, or a page recovered then and not now
    comes back empty and every evidence offset after it points somewhere else.
    Read `resume.document_text` if that is what you actually want.
    """
    data = await storage.get(resume.storage_key)
    return await asyncio.to_thread(parse_document_bytes, data, filename=resume.filename, ocr=ocr)
