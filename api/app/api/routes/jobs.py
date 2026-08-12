"""Job postings and the requirements they are screened by.

Requirement routes are nested under their job rather than exposed on a bare
requirement id, so ownership is settled in exactly one place (`_owned_job`) and a
requirement can never be reached by guessing its id alone.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CandidateDep, RecruiterDep, SessionDep
from app.models import Candidate, Job, JobRequirement, RequirementKind, Role

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Every requirement travels in one prompt per screening, so an unbounded list is
# both a context problem and a bill. A posting that genuinely needs more than this
# is asking for a shortlist, not a screening.
MAX_REQUIREMENTS_PER_JOB = 30

# Both feed the judging prompt, so both are capped: `detail` per requirement, and
# `description`, which is kept for context and audit rather than judged against.
MAX_DETAIL_CHARS = 2000
MAX_DESCRIPTION_CHARS = 20_000


class RequirementIn(BaseModel):
    kind: RequirementKind = RequirementKind.OTHER
    label: str = Field(min_length=1, max_length=300)
    detail: str | None = Field(default=None, max_length=MAX_DETAIL_CHARS)
    must_have: bool = False
    weight: float = Field(default=1.0, gt=0, le=100)


class RequirementPatch(BaseModel):
    """Every field optional. Unset fields are left alone; `null` clears `detail`."""

    kind: RequirementKind | None = None
    label: str | None = Field(default=None, min_length=1, max_length=300)
    detail: str | None = Field(default=None, max_length=MAX_DETAIL_CHARS)
    must_have: bool | None = None
    weight: float | None = Field(default=None, gt=0, le=100)
    position: int | None = Field(default=None, ge=0)


class JobIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_CHARS)
    requirements: list[RequirementIn] = Field(
        default_factory=list, max_length=MAX_REQUIREMENTS_PER_JOB
    )


class JobPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_CHARS)


class RequirementOut(BaseModel):
    id: str
    position: int
    kind: RequirementKind
    label: str
    detail: str | None
    must_have: bool
    weight: float

    @classmethod
    def of(cls, requirement: JobRequirement) -> RequirementOut:
        return cls(
            id=str(requirement.id),
            position=requirement.position,
            kind=requirement.kind,
            label=requirement.label,
            detail=requirement.detail,
            must_have=requirement.must_have,
            weight=requirement.weight,
        )


class JobOut(BaseModel):
    id: str
    title: str
    description: str | None
    requirements: list[RequirementOut]

    @classmethod
    def of(cls, job: Job) -> JobOut:
        return cls(
            id=str(job.id),
            title=job.title,
            description=job.description,
            requirements=[RequirementOut.of(item) for item in job.requirements],
        )


async def _owned_job(session: SessionDep, *, job_id: uuid.UUID, candidate: Candidate) -> Job:
    """One candidate's job with its requirements loaded, or 404.

    404 rather than 403 for someone else's job, matching `_owned_resume`: the
    response should not confirm that the id exists.
    """
    job = (
        await session.execute(
            select(Job).where(Job.id == job_id).options(selectinload(Job.requirements))
        )
    ).scalar_one_or_none()

    if job is None or job.owner_id != candidate.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


async def _readable_job(session: SessionDep, *, job_id: uuid.UUID) -> Job:
    """Any account's view of a posting, or 404 when there is no such posting.

    A posting is an advertisement, and a candidate who cannot read one cannot decide
    whether to apply to it — which is what M4 slice 2 meant by reads staying open to
    every role. Every *write* still goes through `_owned_job`, so widening the read
    widens nothing else.

    The 404 here answers "no such id" rather than "not yours", so unlike `_owned_job`
    it is not hiding anything: the whole point is that the row is public to read.
    """
    job = (
        await session.execute(
            select(Job).where(Job.id == job_id).options(selectinload(Job.requirements))
        )
    ).scalar_one_or_none()

    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def _find_requirement(job: Job, requirement_id: uuid.UUID) -> JobRequirement:
    for requirement in job.requirements:
        if requirement.id == requirement_id:
            return requirement
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement not found")


def _changes(payload: BaseModel, *, nullable: frozenset[str]) -> dict[str, Any]:
    """The fields a PATCH actually set, refusing a null the column cannot hold.

    `exclude_unset` is what separates "leave this alone" from "clear this" — a
    plain dump cannot tell them apart. Only `description` and `detail` are nullable
    columns, so a null anywhere else is a request to refuse rather than an
    IntegrityError from the database.
    """
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True)
    not_nullable = sorted(
        field for field, value in changes.items() if value is None and field not in nullable
    )
    if not_nullable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"These fields cannot be set to null: {', '.join(not_nullable)}",
        )
    return changes


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobIn, candidate: RecruiterDep, session: SessionDep) -> JobOut:
    """Create a job, with its requirements in the same call.

    One call rather than two because authoring both together is the common case.
    An empty list is still accepted — a posting is often written before it is
    decomposed — and it is the screening endpoint that refuses a job which cannot
    judge anything yet.
    """
    # Passed to the constructor rather than appended afterwards so the collection
    # is populated even when it is empty. Left untouched it is never *loaded*, and
    # rendering the response would lazy-load it after the commit — which on an
    # async session raises MissingGreenlet rather than returning an empty list.
    job = Job(
        owner_id=candidate.id,
        title=payload.title,
        description=payload.description,
        requirements=[
            JobRequirement(
                position=position,
                kind=item.kind,
                label=item.label,
                detail=item.detail,
                must_have=item.must_have,
                weight=item.weight,
            )
            for position, item in enumerate(payload.requirements)
        ],
    )

    session.add(job)
    await session.commit()
    return JobOut.of(job)


@router.get("", response_model=list[JobOut])
async def list_jobs(candidate: CandidateDep, session: SessionDep) -> list[JobOut]:
    """The postings this account works with — which is a different list per role.

    A recruiter's `/jobs` is an authoring surface and answers "the postings I own".
    A candidate's is a discovery surface and answers "the postings I could apply
    to", so it is not filtered by ownership: a candidate owns no postings, and
    filtering by owner returned an empty list to every one of them. That left the
    whole application journey unreachable from a browser — the apply screen builds
    its list from here — while `GET /jobs` still answered 200, which is why the
    RBAC check that asserted the status code never saw it.

    Only the read widens. Authoring, editing and screening all still go through
    `_owned_job`, so a candidate reaching this list gains nothing but the ability
    to read a posting and apply to it.
    """
    query = select(Job).options(selectinload(Job.requirements)).order_by(Job.created_at.desc())
    if candidate.role is not Role.CANDIDATE:
        query = query.where(Job.owner_id == candidate.id)

    result = await session.execute(query)
    return [JobOut.of(job) for job in result.scalars()]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, candidate: CandidateDep, session: SessionDep) -> JobOut:
    """Read one posting. Public to any account, for the reason `_readable_job` gives."""
    return JobOut.of(await _readable_job(session, job_id=job_id))


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(
    job_id: uuid.UUID, payload: JobPatch, candidate: RecruiterDep, session: SessionDep
) -> JobOut:
    job = await _owned_job(session, job_id=job_id, candidate=candidate)
    for field, value in _changes(payload, nullable=frozenset({"description"})).items():
        setattr(job, field, value)

    await session.commit()
    return JobOut.of(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(job_id: uuid.UUID, candidate: RecruiterDep, session: SessionDep) -> None:
    job = await _owned_job(session, job_id=job_id, candidate=candidate)
    await session.delete(job)
    await session.commit()


@router.post(
    "/{job_id}/requirements", response_model=RequirementOut, status_code=status.HTTP_201_CREATED
)
async def add_requirement(
    job_id: uuid.UUID, payload: RequirementIn, candidate: RecruiterDep, session: SessionDep
) -> RequirementOut:
    job = await _owned_job(session, job_id=job_id, candidate=candidate)

    if len(job.requirements) >= MAX_REQUIREMENTS_PER_JOB:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A job may have at most {MAX_REQUIREMENTS_PER_JOB} requirements",
        )

    requirement = JobRequirement(
        job_id=job.id,
        position=max((item.position for item in job.requirements), default=-1) + 1,
        kind=payload.kind,
        label=payload.label,
        detail=payload.detail,
        must_have=payload.must_have,
        weight=payload.weight,
    )
    session.add(requirement)
    await session.commit()
    return RequirementOut.of(requirement)


@router.patch("/{job_id}/requirements/{requirement_id}", response_model=RequirementOut)
async def update_requirement(
    job_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: RequirementPatch,
    candidate: RecruiterDep,
    session: SessionDep,
) -> RequirementOut:
    job = await _owned_job(session, job_id=job_id, candidate=candidate)
    requirement = _find_requirement(job, requirement_id)

    for field, value in _changes(payload, nullable=frozenset({"detail"})).items():
        setattr(requirement, field, value)

    await session.commit()
    return RequirementOut.of(requirement)


@router.delete("/{job_id}/requirements/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_requirement(
    job_id: uuid.UUID, requirement_id: uuid.UUID, candidate: RecruiterDep, session: SessionDep
) -> None:
    job = await _owned_job(session, job_id=job_id, candidate=candidate)
    await session.delete(_find_requirement(job, requirement_id))
    await session.commit()
