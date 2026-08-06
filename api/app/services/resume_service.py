"""Ingest a resume: store it, parse it, extract a verified profile, persist all three.

Runs inline in the request in M1. M2 moves parse-and-extract onto the worker; this
function is written so that split is a matter of calling the second half from a job
rather than restructuring it.

Failures are recorded on the row instead of thrown away. A scanned PDF or an
unreachable model leaves a resume in a state that explains itself and can be
retried, which is what the journey's "no silent failure" requirement asks for.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.base import LLMError, StructuredExtractor
from app.models import Candidate, ExtractedProfileRow, LLMCallLog, Resume, ResumeStatus
from app.pipeline.extract import ExtractionOutcome, extract_profile
from app.pipeline.parse import ParsedDocument, ParseError, parse_document_bytes
from app.pipeline.prompts import EXTRACTION_PROMPT_VERSION
from app.storage import Storage, build_storage_key, content_hash

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
    extractor: StructuredExtractor,
    settings: Settings,
) -> IngestResult:
    """Store and process one upload. Idempotent on the file's content hash."""
    digest = content_hash(data)

    existing = await find_by_content(session, candidate_id=candidate.id, digest=digest)
    if existing is not None:
        # Same bytes, same result. Re-running extraction would spend money to
        # produce what we already have.
        logger.info("resume %s: duplicate upload deduplicated", existing.id)
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
    )
    session.add(resume)
    try:
        await session.flush()

        await process_resume(
            session,
            resume=resume,
            data=data,
            extractor=extractor,
            settings=settings,
        )
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
        return IngestResult(resume=existing, created=False)
    except Exception:
        # The row rolls back with the transaction; remove the blob written above
        # so a failed request cannot strand an object no row points at. The key is
        # exclusively ours — an earlier upload of the same bytes would have been
        # deduplicated before reaching here.
        await session.rollback()
        await storage.delete(key)
        raise

    return IngestResult(resume=resume, created=True)


async def process_resume(
    session: AsyncSession,
    *,
    resume: Resume,
    data: bytes,
    extractor: StructuredExtractor,
    settings: Settings,
) -> None:
    """Parse then extract, recording the outcome on the row.

    Does not commit — the caller owns the transaction boundary. This is the half
    that M2's worker will call.
    """
    try:
        document = parse_document_bytes(data, filename=resume.filename)
    except ParseError as exc:
        resume.status = ResumeStatus.FAILED
        resume.failure_reason = str(exc)
        logger.warning("resume %s: parse failed (%s)", resume.id, type(exc).__name__)
        return

    resume.page_count = document.page_count
    resume.pages_without_text = list(document.pages_without_text)
    # Stored verbatim: evidence offsets index into exactly this string, so
    # re-parsing later could invalidate every citation already shown to a user.
    resume.document_text = document.text
    resume.status = ResumeStatus.PARSED
    resume.failure_reason = None

    try:
        outcome = await extract_profile(
            document, extractor, max_attempts=settings.extraction_max_attempts
        )
    except LLMError as exc:
        # Parsed text is kept, so a retry skips straight to extraction.
        resume.failure_reason = f"Extraction failed: {exc}"
        logger.warning("resume %s: extraction failed (%s)", resume.id, type(exc).__name__)
        return

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


async def reparse_document(resume: Resume, storage: Storage) -> ParsedDocument:
    """Rebuild the parsed document for a resume from stored bytes."""
    data = await storage.get(resume.storage_key)
    return parse_document_bytes(data, filename=resume.filename)
