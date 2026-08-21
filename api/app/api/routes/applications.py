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
from app.models import Candidate, Job, Resume, ResumeStatus, Role, Screening
from app.models.application import Application, ApplicationEvent, ApplicationState
from app.schemas.judgment import Verdict
from app.schemas.profile import DroppedClaim, EvidenceRef
from app.services import application_service, screening_service
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


class ReceiptRequirement(BaseModel):
    """One requirement as the applicant is shown it.

    **Every field is read off the stored judgment, never off the posting.** The
    posting's requirement rows can be edited after a screening ran, and joining to
    them would silently relabel a verdict somebody has already been shown — the
    receipt would then be a claim about a person made from words nobody judged them
    against.

    No `weight`. It is ranking's input, it never reached the judge, and it is a
    number that only means anything next to other candidates — which is the one
    comparison a receipt must not invite.
    """

    label: str
    must_have: bool
    verdict: Verdict
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ReceiptOut(BaseModel):
    """What the employer read about you, on your own document.

    Deliberately **not** `ScreeningDetail`, which the recruiter's screen gets.
    That carries `attempts`, `cost_usd`, `failure_reason` and `requirements_hash` —
    facts about running a screening, which belong to whoever paid for it. This
    carries the verdict and the evidence, which belong to whoever the verdict is
    about (`services/privacy_service.py`, which already exports exactly this on the
    grounds that a verdict about you is yours). The narrower shape is the boundary,
    not a copy of one.
    """

    application_id: str
    job_title: str
    state: ApplicationState
    reason: str | None
    """Why the application is where it is, when the move recorded one.

    Read off the most recent event, which is the move that produced the current
    state — `Application.state` being a projection of the log is what makes those
    the same thing. A rejection always has one; M4 refuses the transition without.
    """

    screened_at: str
    requirements: list[ReceiptRequirement]
    dropped: list[DroppedClaim] = Field(default_factory=list)
    """The guardrail, shown rather than described. A claim the model made that could
    not be located in this document was refused, and the applicant is entitled to
    see that it happened to *their* document."""

    document_text: str | None
    """The text every offset above indexes into, so a citation can be highlighted
    rather than searched for."""

    posting_changed_since: bool
    """Whether the posting's requirements have been edited since this was judged.

    Said out loud rather than hidden or quietly corrected. The verdicts above are
    still exactly what was read; what changed is what the posting now asks for, and
    an applicant comparing the two deserves to know which is which.
    """


@router.get("/applications/{application_id}/screening", response_model=ReceiptOut)
async def get_application_receipt(
    application_id: uuid.UUID, candidate: CandidateDep, session: SessionDep
) -> ReceiptOut:
    """The screening behind one application, for the person it is about.

    **This is the route the whole project was founded on.** `README.md` names the
    pain point as candidates rejected by automated screening with no explanation;
    every screen before this one served the side doing the rejecting.

    Reached through `_visible_application`, so both parties to an application get
    it and nobody else does — **404, not 403**, for a stranger and for an
    application that has not been screened yet. A 403 on either would confirm the id
    exists, which is what `_owned_job` and `_owned_resume` answer 404 to avoid, and
    "screened but you may not see it" is not a state this system has.

    The screening is found through `application_service.completed_screening_id`,
    the same lookup a shortlist rests on. That alignment is worth keeping rather
    than coincidental: a receipt exists exactly when the employer had something
    complete enough to act on.
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No screening yet")

    application, job, resume, _ = await _visible_application(
        session, application_id=application_id, candidate=candidate
    )

    screening_id = await application_service.completed_screening_id(
        session, application=application
    )
    if screening_id is None:
        raise not_found
    screening = await session.get(Screening, screening_id)
    if screening is None:
        raise not_found

    judgment = screening_service.stored_judgment(screening)
    if judgment is None:
        # A completed screening whose stored result will not validate. `ranking`
        # reports this as `malformed` and carries on; here there is nothing to show,
        # and inventing an empty receipt would read as "nothing was found in your
        # document" — a claim about the applicant rather than about a broken row.
        raise not_found

    # `_visible_application` fetches the posting by primary key, so its requirements
    # are unloaded — and a lazy load under `AsyncSession` is not a slow path, it is a
    # `MissingGreenlet`. Asked for explicitly here rather than widened there: this is
    # the only caller that needs them, and every other route through that helper
    # would pay for a join it never reads.
    await session.refresh(job, attribute_names=["requirements"])

    latest = (
        await session.execute(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application.id)
            .order_by(ApplicationEvent.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return ReceiptOut(
        application_id=str(application.id),
        job_title=job.title,
        state=application.state,
        reason=latest.reason if latest else None,
        screened_at=(screening.updated_at or screening.created_at).isoformat(),
        requirements=[
            ReceiptRequirement(
                label=item.label,
                must_have=item.must_have,
                verdict=item.verdict,
                evidence=item.evidence,
            )
            for item in judgment.requirements
        ],
        dropped=judgment.dropped,
        document_text=resume.document_text,
        posting_changed_since=(
            screening.requirements_hash is not None
            and screening.requirements_hash != screening_service.fingerprint_of(job)
        ),
    )


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
