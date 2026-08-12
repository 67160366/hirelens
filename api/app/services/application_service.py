"""Applying to a job, and moving an application through its states.

Shaped like the two services beside it: no HTTP types, and the caller owns the
transaction boundary except where a natural key forces a commit to resolve a race
(`apply`, which copies `resume_service.ingest_resume`'s handling exactly).

**This module is the only place `Application.state` is written**, and it never
writes it without appending the `ApplicationEvent` that caused it, in the same
transaction. That pairing is the whole design — the column is a projection and the
log is the record — so a second writer would quietly reintroduce states nobody can
account for. `app/applications.py` decides *whether* a move is allowed; this decides
nothing and only persists what it was told.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications import SYSTEM, Actor, Refused, Transition, plan_transition
from app.models import Candidate, Job, Resume, Screening, ScreeningStatus
from app.models.application import Application, ApplicationEvent, ApplicationState

logger = logging.getLogger(__name__)


class TransitionRefused(Exception):
    """A move the state machine would not allow. Carries the user-facing reason."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


async def find_application(
    session: AsyncSession, *, job_id: uuid.UUID, candidate_id: uuid.UUID
) -> Application | None:
    result = await session.execute(
        select(Application).where(
            Application.job_id == job_id, Application.candidate_id == candidate_id
        )
    )
    return result.scalar_one_or_none()


async def apply(
    session: AsyncSession, *, job: Job, resume: Resume, applicant: Candidate
) -> tuple[Application, bool]:
    """Put a resume forward for a job. Returns the row and whether it was created.

    Idempotent on `(job_id, candidate_id)`, which is a natural key rather than an
    `Idempotency-Key` header: applying twice is the same act, so the second answers
    **200** with the existing row the way a duplicate upload does. Re-applying does
    **not** swap the resume — a screening already produced would then be about a
    document nobody put forward. Withdraw and apply again if that is what you mean.
    """
    existing = await find_application(session, job_id=job.id, candidate_id=applicant.id)
    if existing is not None:
        return existing, False

    application = Application(
        job_id=job.id,
        candidate_id=applicant.id,
        resume_id=resume.id,
        state=ApplicationState.APPLIED,
    )
    session.add(application)
    session.add(
        ApplicationEvent(
            application=application,
            position=0,
            from_state=None,
            to_state=ApplicationState.APPLIED,
            actor_id=applicant.id,
            # The role held when it happened, like every other event. Left null
            # once, which made the first entry the only one that could not say
            # what its author was.
            actor_role=applicant.role,
            note="applied",
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # Two requests raced past the lookup; the loser's INSERT hit
        # uq_applications_job_candidate. Hand back the winner's row — the same move
        # `resume_service.ingest_resume` makes, and the reason this needs no
        # idempotency-key table.
        await session.rollback()
        winner = await find_application(session, job_id=job.id, candidate_id=applicant.id)
        if winner is None:
            raise
        logger.info("application %s: lost an apply race, returning the winner", winner.id)
        return winner, False

    logger.info("application %s: created for job %s", application.id, job.id)
    return application, True


async def transition(
    session: AsyncSession,
    *,
    application: Application,
    to_state: ApplicationState,
    actor: Actor,
    reason: str | None = None,
    screening_id: uuid.UUID | None = None,
    note: str | None = None,
    commit: bool = True,
) -> ApplicationEvent:
    """Move an application, recording the event that moved it. Raises if refused.

    `commit=False` is for the worker path, where this runs inside a job's own
    transaction — the event and the screening's own outcome must land together or
    not at all, or the log would claim a screening completed that did not.
    """
    planned = plan_transition(
        application.state,
        to_state,
        actor=actor,
        reason=reason,
        screening_id=str(screening_id) if screening_id else None,
        note=note,
    )
    if isinstance(planned, Refused):
        raise TransitionRefused(planned.why)

    return await _record(session, application, planned, actor, screening_id, commit=commit)


async def _record(
    session: AsyncSession,
    application: Application,
    planned: Transition,
    actor: Actor,
    screening_id: uuid.UUID | None,
    *,
    commit: bool,
) -> ApplicationEvent:
    """Write the event and the projection together. The one place both happen."""
    event = ApplicationEvent(
        application_id=application.id,
        position=await _next_position(session, application.id),
        from_state=application.state,
        to_state=planned.to_state,
        # Null only for the system: a worker following a screening is not a
        # person, and naming one would be a small lie in an audit log. Everyone
        # else is named from `Actor.account_id`, which is carried rather than
        # derived — deriving it silently logged every recruiter decision as the
        # system's.
        actor_id=actor.account_id,
        actor_role=actor.role,
        reason=planned.reason,
        screening_id=screening_id,
        note=planned.note,
    )
    session.add(event)
    application.state = planned.to_state

    if commit:
        await session.commit()

    logger.info(
        "application %s: %s -> %s by %s",
        application.id,
        event.from_state,
        event.to_state,
        actor.mover,
    )
    return event


async def _next_position(session: AsyncSession, application_id: uuid.UUID) -> int:
    """Where this event goes in the history.

    Read rather than counted in memory: the events are not loaded, and a lazy load
    on an async session is an error rather than a query. Safe against a concurrent
    writer because `uq_application_events_application_position` refuses a collision
    outright — better a failed transition than two events claiming one place.
    """
    highest = (
        await session.execute(
            select(func.max(ApplicationEvent.position)).where(
                ApplicationEvent.application_id == application_id
            )
        )
    ).scalar_one_or_none()
    return 0 if highest is None else highest + 1


async def follow_screening(
    session: AsyncSession, *, screening: Screening, commit: bool = False
) -> ApplicationEvent | None:
    """Move the application, if any, to match what its screening just did.

    This is the "derived from something checkable" clause with a body: the system
    claims `screened` only because a `Screening` row reached `completed`, and the
    event records which one. Every other transition is somebody's decision.

    A no-op when no application matches, which is the normal M3 case — a recruiter
    may screen a resume nobody applied with, and that must keep working. Also a
    no-op when the move is not allowed from where the application currently is: a
    candidate who withdrew mid-screening has said something the worker does not get
    to overrule.
    """
    application = await find_application(
        session, job_id=screening.job_id, candidate_id=await _resume_owner(session, screening)
    )
    if application is None:
        return None

    to_state, note = _state_for(screening)
    if to_state is None:
        return None

    planned = plan_transition(
        application.state,
        to_state,
        actor=SYSTEM,
        screening_id=str(screening.id),
        note=note,
    )
    if isinstance(planned, Refused):
        # Not an error. The applicant may have withdrawn while the worker was
        # running, and their decision outranks the screening's bookkeeping.
        logger.info(
            "application %s: not following screening %s (%s)",
            application.id,
            screening.id,
            planned.why,
        )
        return None

    return await _record(session, application, planned, SYSTEM, screening.id, commit=commit)


def _state_for(screening: Screening) -> tuple[ApplicationState | None, str | None]:
    """What a screening's status means for the application behind it."""
    match screening.status:
        case ScreeningStatus.PENDING | ScreeningStatus.PROCESSING:
            return ApplicationState.SCREENING, "a screening was queued"
        case ScreeningStatus.COMPLETED:
            return ApplicationState.SCREENED, "the screening completed"
        case ScreeningStatus.FAILED | ScreeningStatus.DEAD_LETTERED:
            # Back where it started rather than into a state implying somebody
            # looked. The evidence never arrived; that is not the applicant's doing.
            return ApplicationState.APPLIED, "the screening could not be produced"
    return None, None


async def _resume_owner(session: AsyncSession, screening: Screening) -> uuid.UUID:
    resume = await session.get(Resume, screening.resume_id)
    return resume.candidate_id if resume else uuid.UUID(int=0)


async def completed_screening_id(
    session: AsyncSession, *, application: Application
) -> uuid.UUID | None:
    """The completed screening a shortlist would rest on, or `None`.

    Found by `(job_id, resume_id)`, which `uq_screenings_job_resume` already makes
    unique — no foreign key on `Application`, and so no second source of truth about
    which screening belongs to which application. The same instinct as ranking
    joining requirements by position rather than storing ids twice.
    """
    result = await session.execute(
        select(Screening.id).where(
            Screening.job_id == application.job_id,
            Screening.resume_id == application.resume_id,
            Screening.status == ScreeningStatus.COMPLETED,
        )
    )
    return result.scalar_one_or_none()
