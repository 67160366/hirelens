"""Applying to a job, and moving an application through its states.

Creation is nested under the job (`POST /jobs/{job_id}/applications`) for the same
reason screenings and requirements are: ownership is settled in one place. Reading
and moving one is flat, because a client holding the id should not have to remember
which job it came from.

The two refusals stay apart here as everywhere else: **403** when a role may not
reach a route, **404** when the row is not yours. A transition the state machine
will not allow is neither — it is **409**, with the reason, because the caller is
entitled to both the row and the route and the answer is about the move itself.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import publication
from app.api.deps import CandidateDep, SessionDep
from app.applications import Actor
from app.models import Candidate, Job, Resume, ResumeStatus, Role
from app.models.application import Application, ApplicationEvent, ApplicationState
from app.services import application_service
from app.services.application_service import TransitionRefused

router = APIRouter(tags=["applications"])

MAX_REASON_CHARS = 2000


class ApplyIn(BaseModel):
    resume_id: uuid.UUID


class TransitionIn(BaseModel):
    to_state: ApplicationState
    reason: str | None = Field(default=None, max_length=MAX_REASON_CHARS)


class EventOut(BaseModel):
    id: str
    position: int
    """Where this sits in the history, 0-based. Served because the order is a
    stored fact rather than something a client should re-derive from timestamps —
    which is exactly what went wrong when the server tried it."""

    from_state: ApplicationState | None
    to_state: ApplicationState
    actor_id: str | None
    """Null means the system moved it — a worker following a screening is not a
    person, and naming one would be a small lie in an audit log."""

    actor_role: Role | None
    reason: str | None
    screening_id: str | None
    """What the move rested on, where it rested on anything."""

    note: str | None
    created_at: str

    @classmethod
    def of(cls, event: ApplicationEvent) -> EventOut:
        return cls(
            id=str(event.id),
            position=event.position,
            from_state=event.from_state,
            to_state=event.to_state,
            actor_id=str(event.actor_id) if event.actor_id else None,
            actor_role=event.actor_role,
            reason=event.reason,
            screening_id=str(event.screening_id) if event.screening_id else None,
            note=event.note,
            created_at=event.created_at.isoformat(),
        )


class ApplicationOut(BaseModel):
    id: str
    job_id: str
    job_title: str
    candidate_id: str
    resume_id: str
    resume_filename: str
    resume_status: ResumeStatus
    state: ApplicationState
    created_at: str

    @classmethod
    def of(cls, application: Application, *, job: Job, resume: Resume) -> ApplicationOut:
        return cls(
            id=str(application.id),
            job_id=str(application.job_id),
            job_title=job.title,
            candidate_id=str(application.candidate_id),
            resume_id=str(application.resume_id),
            # Served rather than joined client-side. `GET /jobs/{id}/candidates`
            # used to leave this to the caller on the assumption that every resume
            # in the list belonged to them — the assumption an application breaks.
            resume_filename=resume.filename,
            # Same reasoning, and the same mistake caught one screen later: a
            # recruiter can screen an applicant's resume but `GET /resumes` returns
            # only their own, so the applicants panel had no way to tell a resume it
            # can screen from one that would raise `NotScreenable` on the worker.
            # Applying does not require an extracted resume, so this is a real
            # question rather than a constant.
            resume_status=resume.status,
            state=application.state,
            created_at=application.created_at.isoformat(),
        )


async def _visible_application(
    session: SessionDep, *, application_id: uuid.UUID, candidate: Candidate
) -> tuple[Application, Job, Resume, Actor]:
    """One application the caller is a party to, plus who they are to it.

    404 rather than 403 for one they are not party to, matching `_owned_job` and
    `_owned_resume`: the response must not confirm the id exists. The `Actor` comes
    back with it because every caller needs it next, and resolving it twice is how
    the two halves drift apart.
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    application = (
        await session.execute(select(Application).where(Application.id == application_id))
    ).scalar_one_or_none()
    if application is None:
        raise not_found

    job = await session.get(Job, application.job_id)
    resume = await session.get(Resume, application.resume_id)
    if job is None or resume is None:
        raise not_found

    actor = Actor.of(
        candidate.role,
        account_id=candidate.id,
        is_applicant=application.candidate_id == candidate.id,
        is_job_owner=job.owner_id == candidate.id,
    )
    if actor is None:
        raise not_found
    return application, job, resume, actor


@router.post("/jobs/{job_id}/applications", response_model=ApplicationOut)
async def apply_to_job(
    job_id: uuid.UUID,
    payload: ApplyIn,
    candidate: CandidateDep,
    session: SessionDep,
    response: Response,
) -> ApplicationOut:
    """Put one of your resumes forward for a job.

    **201** when the application was created, **200** when you had already applied —
    the natural key `(job_id, candidate_id)` carrying the idempotency, the same way
    a duplicate upload answers 200 and a current screening answers 200 rather than
    202. There is no `Idempotency-Key` header because the schema already guarantees
    what one would.

    Open to any role: a recruiter may apply for a job as easily as anyone, and
    refusing that would be a rule about people rather than about permissions.

    **Only a published posting accepts applications**, and the two refusals below
    are deliberately different. A draft somebody else is still writing answers
    **404**, because it is invisible and a 403 would confirm the id exists — the
    same line `_owned_job` holds. A posting you can legitimately see but which is
    not open — a closed one, or your own draft — answers **409** with a reason,
    because hiding a row the caller already knows about would be pretending rather
    than refusing.
    """
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if not publication.is_public(job.status):
        if job.owner_id != candidate.id and candidate.role is not Role.ADMIN:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This posting is not accepting applications: it is "
                f"{job.status.value} rather than published."
            ),
        )

    resume = await session.get(Resume, payload.resume_id)
    if resume is None or resume.candidate_id != candidate.id:
        # Your own resume only. 404 rather than 403 — the id must not be confirmed.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    application, created = await application_service.apply(
        session, job=job, resume=resume, applicant=candidate
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return ApplicationOut.of(application, job=job, resume=resume)


@router.get("/jobs/{job_id}/applications", response_model=list[ApplicationOut])
async def list_job_applications(
    job_id: uuid.UUID, candidate: CandidateDep, session: SessionDep
) -> list[ApplicationOut]:
    """Everyone who applied to one of your postings, newest first."""
    job = await session.get(Job, job_id)
    if job is None or (job.owner_id != candidate.id and candidate.role is not Role.ADMIN):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    rows = (
        await session.execute(
            select(Application, Resume)
            .join(Resume, Resume.id == Application.resume_id)
            .where(Application.job_id == job.id)
            .order_by(Application.created_at.desc())
        )
    ).all()
    return [ApplicationOut.of(a, job=job, resume=r) for a, r in rows]


@router.get("/me/applications", response_model=list[ApplicationOut])
async def list_my_applications(
    candidate: CandidateDep, session: SessionDep
) -> list[ApplicationOut]:
    """Everything you have applied for, newest first."""
    rows = (
        await session.execute(
            select(Application, Job, Resume)
            .join(Job, Job.id == Application.job_id)
            .join(Resume, Resume.id == Application.resume_id)
            .where(Application.candidate_id == candidate.id)
            .order_by(Application.created_at.desc())
        )
    ).all()
    return [ApplicationOut.of(a, job=j, resume=r) for a, j, r in rows]


@router.get("/applications/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: uuid.UUID, candidate: CandidateDep, session: SessionDep
) -> ApplicationOut:
    application, job, resume, _ = await _visible_application(
        session, application_id=application_id, candidate=candidate
    )
    return ApplicationOut.of(application, job=job, resume=resume)


@router.post("/applications/{application_id}/transitions", response_model=ApplicationOut)
async def move_application(
    application_id: uuid.UUID,
    payload: TransitionIn,
    candidate: CandidateDep,
    session: SessionDep,
) -> ApplicationOut:
    """Move an application, or be told in words why it cannot move.

    **409, with the reason.** Not 400 — the request is well formed — and not a
    silent no-op, which would leave a caller unable to tell a refused decision from
    a bug. `app/applications.py` writes the reason; this only relays it.

    A shortlist needs the completed screening it rests on, and this is where it is
    found: by `(job_id, resume_id)`, which `uq_screenings_job_resume` already makes
    unique. Without one the move is refused, which is the state machine keeping the
    milestone's promise — no claim about a person without evidence behind it.
    """
    application, job, resume, actor = await _visible_application(
        session, application_id=application_id, candidate=candidate
    )
    screening_id = await application_service.completed_screening_id(
        session, application=application
    )

    try:
        await application_service.transition(
            session,
            application=application,
            to_state=payload.to_state,
            actor=actor,
            reason=payload.reason,
            screening_id=screening_id,
        )
    except TransitionRefused as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.why) from exc

    return ApplicationOut.of(application, job=job, resume=resume)


@router.get("/applications/{application_id}/events", response_model=list[EventOut])
async def list_application_events(
    application_id: uuid.UUID, candidate: CandidateDep, session: SessionDep
) -> list[EventOut]:
    """The whole log, oldest first — every move, who made it, and what it rested on.

    This is the record; `Application.state` is a projection of it. Replaying these
    in order has to reproduce the state, and `tests/test_applications.py` holds that
    line.
    """
    application, _, _, _ = await _visible_application(
        session, application_id=application_id, candidate=candidate
    )
    loaded = (
        await session.execute(
            select(Application)
            .where(Application.id == application.id)
            .options(selectinload(Application.events))
        )
    ).scalar_one()
    return [EventOut.of(event) for event in loaded.events]
