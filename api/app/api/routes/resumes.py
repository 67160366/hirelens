"""Upload a resume, follow its progress, and read back the verified profile."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from time import monotonic
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.api.deps import (
    CandidateDep,
    QueueDep,
    SessionDep,
    SessionFactoryDep,
    SettingsDep,
    StorageDep,
)
from app.config import Settings
from app.jobs import is_stalled
from app.models import Candidate, Resume, ResumeStatus
from app.services import resume_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resumes", tags=["resumes"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Slack for multipart boundaries and headers when judging Content-Length.
MULTIPART_OVERHEAD_BYTES = 4 * 1024

# The leading bytes each accepted type really starts with. The extension is
# caller-chosen and proves nothing, so the magic bytes are what the gate trusts —
# a mislabelled file fails parsing anyway, and rejecting it here is before it is
# stored and before extraction is billed. A .docx is a zip, hence the PK header.
MAGIC_BY_SUFFIX = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",
}
ALLOWED_SUFFIXES = frozenset(MAGIC_BY_SUFFIX)

# Where a retry can help. `pending` is already in hand; `extracted` is done, and
# redoing it would bill a second extraction to produce the profile we already have.
#
# `parsed` is here for rows written before the retry policy existed, where a
# failed extraction left the status behind. Nothing commits it any more — the job
# always resolves to pending, dead_lettered, failed or extracted.
RETRYABLE_STATUSES = frozenset(
    {ResumeStatus.DEAD_LETTERED, ResumeStatus.FAILED, ResumeStatus.PARSED}
)

# Statuses a worker will still move on its own. Everything else is a resting
# state, which is what ends a progress stream — the server-side twin of
# `isSettled` in `web/lib/api.ts`.
IN_FLIGHT_STATUSES = frozenset({ResumeStatus.PENDING, ResumeStatus.PROCESSING})


def can_retry(resume: Resume, settings: Settings) -> bool:
    """Whether `POST /resumes/{id}/retry` would be accepted for this row.

    `processing` is normally in hand and answering 409 is right. Once it has been
    held past the visibility timeout it is not in hand at all — the worker died,
    redelivery skips the row and re-upload dedupes to it — so the honest answer
    flips. This is the manual half of `jobs.reclaim_stalled`, and it is the only
    half that exists under `QUEUE_BACKEND=inline`, where nothing sweeps.
    """
    if resume.status in RETRYABLE_STATUSES:
        return True
    return resume.status is ResumeStatus.PROCESSING and is_stalled(
        resume.last_attempt_at, timeout_seconds=settings.job_visibility_timeout_seconds
    )


class ResumeOut(BaseModel):
    id: str
    filename: str
    status: ResumeStatus
    size_bytes: int
    page_count: int | None
    pages_without_text: list[int]
    pages_from_ocr: list[int]
    """Pages read by OCR. A citation into one of these is faithful to what was
    recognized, which is not always what was printed — so the UI says so."""

    failure_reason: str | None
    attempts: int
    can_retry: bool
    """Whether `POST /resumes/{id}/retry` would be accepted, so a client does not
    have to reimplement the rule."""

    @classmethod
    def of(cls, resume: Resume, settings: Settings) -> ResumeOut:
        return cls(
            id=str(resume.id),
            filename=resume.filename,
            status=resume.status,
            size_bytes=resume.size_bytes,
            page_count=resume.page_count,
            pages_without_text=resume.pages_without_text or [],
            pages_from_ocr=resume.pages_from_ocr or [],
            failure_reason=resume.failure_reason,
            attempts=resume.attempts,
            # Takes settings because the answer is time-dependent now: a stalled
            # `processing` row becomes retryable, and the timeout says when.
            can_retry=can_retry(resume, settings),
        )


class ProfileOut(BaseModel):
    resume: ResumeOut
    profile: dict[str, Any] | None
    document_text: str | None
    """The exact text every evidence offset indexes into, so the UI can highlight
    spans without re-parsing and risking a shifted offset."""


@router.post("", response_model=ResumeOut)
async def upload_resume(
    candidate: CandidateDep,
    session: SessionDep,
    storage: StorageDep,
    queue: QueueDep,
    settings: SettingsDep,
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File(description="A PDF or DOCX resume.")],
) -> ResumeOut:
    """Store a resume and queue it for parsing and extraction.

    Returns as soon as the file is stored, so the response carries a `pending`
    resume rather than a finished profile — poll `GET /resumes/{id}` until the
    status is `extracted` or `failed`.

    Idempotent on file content: re-uploading the same bytes returns the existing
    resource with 200 rather than creating a duplicate or re-billing extraction.
    """
    too_large = HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
    )
    # Judge the declared size before buffering the body into memory. The
    # post-read length check below stays as the authoritative backstop.
    declared_size = request.headers.get("content-length")
    if (
        declared_size is not None
        and declared_size.isdigit()
        and int(declared_size) > MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES
    ):
        raise too_large

    filename = file.filename or "resume.pdf"
    suffix = filename[filename.rfind(".") :].lower() if "." in filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only {', '.join(sorted(ALLOWED_SUFFIXES))} uploads are supported",
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty"
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise too_large
    if not data.startswith(MAGIC_BY_SUFFIX[suffix]):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File does not look like a valid {suffix.lstrip('.').upper()}",
        )

    result = await resume_service.ingest_resume(
        session,
        candidate=candidate,
        filename=filename,
        data=data,
        storage=storage,
        queue=queue,
    )

    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return ResumeOut.of(result.resume, settings)


@router.get("", response_model=list[ResumeOut])
async def list_resumes(
    candidate: CandidateDep, session: SessionDep, settings: SettingsDep
) -> list[ResumeOut]:
    result = await session.execute(
        select(Resume).where(Resume.candidate_id == candidate.id).order_by(Resume.created_at.desc())
    )
    return [ResumeOut.of(resume, settings) for resume in result.scalars()]


async def _owned_resume(
    session: SessionDep,
    *,
    resume_id: uuid.UUID,
    candidate: Candidate,
    with_profile: bool = False,
) -> Resume:
    """One candidate's resume, or 404.

    404 rather than 403 for someone else's resume: the response should not confirm
    that the id exists.
    """
    query = select(Resume).where(Resume.id == resume_id)
    if with_profile:
        query = query.options(selectinload(Resume.profile))

    resume = (await session.execute(query)).scalar_one_or_none()
    if resume is None or resume.candidate_id != candidate.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    return resume


@router.post("/{resume_id}/retry", response_model=ResumeOut)
async def retry_resume(
    resume_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> ResumeOut:
    """Put a stopped resume back on the queue.

    The replay half of the dead-letter queue: a resume that exhausted its retries
    is kept with the reason it gave up, and this is how that work is picked up
    again once whatever broke has been fixed.

    Also accepts a resume stranded at `processing` past the visibility timeout —
    a worker that died holding it. `jobs.reclaim_stalled` does that automatically
    where a worker is running; this is the same door, opened by hand, and it is the
    only one under `QUEUE_BACKEND=inline`.
    """
    resume = await _owned_resume(session, resume_id=resume_id, candidate=candidate)

    if not can_retry(resume, settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A resume with status '{resume.status}' cannot be retried. "
                "It is either already in progress or already finished."
            ),
        )

    await resume_service.requeue(session, resume=resume, queue=queue)
    return ResumeOut.of(resume, settings)


@router.get("/{resume_id}", response_model=ProfileOut)
async def get_resume_profile(
    resume_id: uuid.UUID, candidate: CandidateDep, session: SessionDep, settings: SettingsDep
) -> ProfileOut:
    resume = await _owned_resume(
        session, resume_id=resume_id, candidate=candidate, with_profile=True
    )
    return ProfileOut(
        resume=ResumeOut.of(resume, settings),
        profile=resume.profile.profile if resume.profile else None,
        document_text=resume.document_text,
    )


def _frame(event: str, data: str) -> str:
    """One server-sent event. The blank line terminates the frame.

    `data` has to be a single line, which is why every payload here is compact
    JSON — `model_dump_json` never emits a newline.
    """
    return f"event: {event}\ndata: {data}\n\n"


async def _resume_events(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    request: Request,
    resume_id: uuid.UUID,
) -> AsyncIterator[str]:
    """The resume's state now, then again on every change, until it settles.

    Reading the row on an interval is deliberately the mechanism rather than the
    contract. The worker could publish to Redis instead and this endpoint could
    subscribe, but that would put Redis on the API's critical path and break the
    no-server default the inline queue and the whole test suite depend on. The
    stream a client sees would not change either way, so the cheap version is the
    one worth having now.

    A short session per read, not one held open for the stream's lifetime: an idle
    stream has no business holding a pooled connection, and the request's own
    session is closed before this generator ever runs.
    """
    deadline = monotonic() + settings.sse_max_stream_seconds
    last_payload: str | None = None
    last_write = monotonic()
    frames = 0

    while True:
        async with sessionmaker() as session:
            resume = await session.get(Resume, resume_id)

        if resume is None:
            # Deleted while the client was watching. Saying so beats leaving the
            # stream open until the cap for a row that will never change again.
            yield _frame("gone", "{}")
            frames += 1
            break

        payload = ResumeOut.of(resume, settings).model_dump_json()
        if payload != last_payload:
            yield _frame("status", payload)
            last_payload = payload
            last_write = monotonic()
            frames += 1

        if resume.status not in IN_FLIGHT_STATUSES:
            yield _frame("done", payload)
            frames += 1
            break

        now = monotonic()
        if now >= deadline:
            # A resume stranded at `processing` by a worker that died waits out the
            # visibility timeout before anything moves it, and that is far longer
            # than a connection should be held. The client falls back to polling,
            # and sees `can_retry` turn true once the timeout passes.
            yield _frame("timeout", "{}")
            frames += 1
            break

        if now - last_write >= settings.sse_heartbeat_seconds:
            # A comment rather than an event: proxies drop a connection that goes
            # quiet, and a client is required to ignore this line.
            yield ": ping\n\n"
            last_write = now

        if await request.is_disconnected():
            break

        await asyncio.sleep(settings.sse_poll_seconds)

    # Ids and counts only. The payload above carries the candidate's own filename.
    logger.info("resume %s: progress stream closed after %d frames", resume_id, frames)


@router.get("/{resume_id}/events")
async def stream_resume_progress(
    resume_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    sessionmaker: SessionFactoryDep,
    settings: SettingsDep,
    request: Request,
) -> StreamingResponse:
    """Follow a resume until it settles, over server-sent events.

    What the client used to do by re-fetching `GET /resumes/{id}` in a loop, minus
    a round trip and an authentication per tick — and with the intermediate states
    it could never see: `processing` starting, and a failed attempt going back to
    `pending` with the reason attached.

    Frames are `status` (on connect and on every change), then one of `done` when
    the resume reaches a resting state, `timeout` when the connection cap is hit,
    or `gone` if the row is deleted. Each carries a `ResumeOut` and nothing else:
    the profile and `document_text` stay behind `GET /resumes/{id}`, which the
    client calls once, when `done` arrives.

    Ownership is settled here rather than inside the stream, so an unknown resume
    is a 404 instead of an error event inside a 200 response.
    """
    await _owned_resume(session, resume_id=resume_id, candidate=candidate)
    return StreamingResponse(
        _resume_events(sessionmaker, settings, request, resume_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx buffers proxied responses by default, which would hold every
            # frame back until the stream closed and defeat the whole endpoint.
            "X-Accel-Buffering": "no",
        },
    )
