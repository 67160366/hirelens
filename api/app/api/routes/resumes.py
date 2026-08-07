"""Upload a resume and read back the verified profile."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CandidateDep, QueueDep, SessionDep, StorageDep
from app.models import Candidate, Resume, ResumeStatus
from app.services import resume_service

router = APIRouter(prefix="/resumes", tags=["resumes"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf"}
# Slack for multipart boundaries and headers when judging Content-Length.
MULTIPART_OVERHEAD_BYTES = 4 * 1024
# Every real PDF starts with this; the extension check alone accepts any bytes.
PDF_MAGIC = b"%PDF-"

# Where a retry can help. `pending` and `processing` are already in hand;
# `extracted` is done, and redoing it would bill a second extraction to produce
# the profile we already have.
#
# `parsed` is here for rows written before the retry policy existed, where a
# failed extraction left the status behind. Nothing commits it any more — the job
# always resolves to pending, dead_lettered, failed or extracted.
RETRYABLE_STATUSES = frozenset(
    {ResumeStatus.DEAD_LETTERED, ResumeStatus.FAILED, ResumeStatus.PARSED}
)


class ResumeOut(BaseModel):
    id: str
    filename: str
    status: ResumeStatus
    size_bytes: int
    page_count: int | None
    pages_without_text: list[int]
    failure_reason: str | None
    attempts: int
    can_retry: bool
    """Whether `POST /resumes/{id}/retry` would be accepted, so a client does not
    have to reimplement the rule."""

    @classmethod
    def of(cls, resume: Resume) -> ResumeOut:
        return cls(
            id=str(resume.id),
            filename=resume.filename,
            status=resume.status,
            size_bytes=resume.size_bytes,
            page_count=resume.page_count,
            pages_without_text=resume.pages_without_text or [],
            failure_reason=resume.failure_reason,
            attempts=resume.attempts,
            can_retry=resume.status in RETRYABLE_STATUSES,
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
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File(description="A PDF resume.")],
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
    # The suffix is caller-chosen; the magic bytes are not. Anything that is not
    # a PDF fails parsing anyway, so reject it before storing and billing.
    if not data.startswith(PDF_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File is not a valid PDF",
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
    return ResumeOut.of(result.resume)


@router.get("", response_model=list[ResumeOut])
async def list_resumes(candidate: CandidateDep, session: SessionDep) -> list[ResumeOut]:
    result = await session.execute(
        select(Resume).where(Resume.candidate_id == candidate.id).order_by(Resume.created_at.desc())
    )
    return [ResumeOut.of(resume) for resume in result.scalars()]


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
) -> ResumeOut:
    """Put a stopped resume back on the queue.

    The replay half of the dead-letter queue: a resume that exhausted its retries
    is kept with the reason it gave up, and this is how that work is picked up
    again once whatever broke has been fixed.
    """
    resume = await _owned_resume(session, resume_id=resume_id, candidate=candidate)

    if resume.status not in RETRYABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A resume with status '{resume.status}' cannot be retried. "
                "It is either already in progress or already finished."
            ),
        )

    await resume_service.requeue(session, resume=resume, queue=queue)
    return ResumeOut.of(resume)


@router.get("/{resume_id}", response_model=ProfileOut)
async def get_resume_profile(
    resume_id: uuid.UUID, candidate: CandidateDep, session: SessionDep
) -> ProfileOut:
    resume = await _owned_resume(
        session, resume_id=resume_id, candidate=candidate, with_profile=True
    )
    return ProfileOut(
        resume=ResumeOut.of(resume),
        profile=resume.profile.profile if resume.profile else None,
        document_text=resume.document_text,
    )
