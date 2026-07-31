"""Upload a resume and read back the verified profile."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CandidateDep, ExtractorDep, SessionDep, SettingsDep, StorageDep
from app.models import Resume, ResumeStatus
from app.services import resume_service

router = APIRouter(prefix="/resumes", tags=["resumes"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf"}


class ResumeOut(BaseModel):
    id: str
    filename: str
    status: ResumeStatus
    size_bytes: int
    page_count: int | None
    pages_without_text: list[int]
    failure_reason: str | None

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
    settings: SettingsDep,
    storage: StorageDep,
    extractor: ExtractorDep,
    response: Response,
    file: Annotated[UploadFile, File(description="A PDF resume.")],
) -> ResumeOut:
    """Store and process a resume.

    Idempotent on file content: re-uploading the same bytes returns the existing
    resource with 200 rather than creating a duplicate or re-billing extraction.
    """
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
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    result = await resume_service.ingest_resume(
        session,
        candidate=candidate,
        filename=filename,
        data=data,
        storage=storage,
        extractor=extractor,
        settings=settings,
    )

    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return ResumeOut.of(result.resume)


@router.get("", response_model=list[ResumeOut])
async def list_resumes(candidate: CandidateDep, session: SessionDep) -> list[ResumeOut]:
    result = await session.execute(
        select(Resume).where(Resume.candidate_id == candidate.id).order_by(Resume.created_at.desc())
    )
    return [ResumeOut.of(resume) for resume in result.scalars()]


@router.get("/{resume_id}", response_model=ProfileOut)
async def get_resume_profile(
    resume_id: uuid.UUID, candidate: CandidateDep, session: SessionDep
) -> ProfileOut:
    result = await session.execute(
        select(Resume).where(Resume.id == resume_id).options(selectinload(Resume.profile))
    )
    resume = result.scalar_one_or_none()

    # 404 rather than 403 for another candidate's resume: the response should not
    # confirm that the id exists.
    if resume is None or resume.candidate_id != candidate.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    return ProfileOut(
        resume=ResumeOut.of(resume),
        profile=resume.profile.profile if resume.profile else None,
        document_text=resume.document_text,
    )
