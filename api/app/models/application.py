"""M4: a candidate applying to a job, and every move that application has made.

Two tables, and the relationship between them is the point of the milestone.

`Application.state` is **not** the source of truth. `ApplicationEvent` is: an
append-only log of transitions, each recording who made it, what it moved from and
to, and — where the move rests on evidence — which screening it rested on. The
column is a projection of the last event, written in the same transaction, and
replaying the log has to reproduce it (`tests/test_applications.py`).

That is `docs/HANDOFF.md` §9 applied: a state transition is a *claim about a
person*, so it gets the same treatment as a verdict — derived from something
checkable, or not asserted. "Shortlisted" with nobody able to say who decided it,
when, or on what evidence is exactly the unaccountable assertion this project
exists to refuse.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.core import Candidate, Resume, Role
from app.models.matching import Job


class ApplicationState(StrEnum):
    """Where an application has got to.

    Deliberately small. Every state here is one a person could be told about
    without the system having to explain itself.
    """

    APPLIED = "applied"
    """The candidate put themselves forward. The only state an application starts in."""

    SCREENING = "screening"
    """A screening is queued or running. Set by the worker, not by a person."""

    SCREENED = "screened"
    """A screening completed, so there are cited verdicts to look at. Also set by
    the worker — the system claims this only because a `Screening` row says so."""

    SHORTLISTED = "shortlisted"
    """The job's owner wants to take this further. Reachable **only** from
    `screened`, because it is a claim about a person and has to rest on evidence
    that exists."""

    REJECTED = "rejected"
    """The job's owner decided against it, with a reason. Terminal."""

    WITHDRAWN = "withdrawn"
    """The candidate took themselves out. Terminal, and theirs alone to choose."""


TERMINAL_STATES = frozenset({ApplicationState.REJECTED, ApplicationState.WITHDRAWN})


class Application(UUIDPrimaryKey, Timestamps, Base):
    """One candidate, one job, one resume — and where it has got to."""

    __tablename__ = "applications"
    __table_args__ = (
        # One application per person per posting. The natural idempotency key, the
        # same move `uq_resumes_candidate_content` and `uq_screenings_job_resume`
        # make: applying twice is the same act, so it answers 200 rather than
        # creating a second row or needing an `Idempotency-Key` table.
        UniqueConstraint("job_id", "candidate_id", name="uq_applications_job_candidate"),
        Index("ix_applications_state", "state"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    """Which resume was put forward. Named explicitly rather than "their latest",
    because a verdict has to be about the document that was actually judged."""

    state: Mapped[ApplicationState] = mapped_column(
        Enum(ApplicationState, native_enum=False, length=20),
        default=ApplicationState.APPLIED,
        nullable=False,
    )
    """**A projection, not a source of truth.** Only `application_service` writes
    it, and only in the same transaction as the event that caused it. Anything that
    sets this without appending an event has produced a state nobody can account
    for, which is the one thing this table exists to prevent."""

    job: Mapped[Job] = relationship()
    candidate: Mapped[Candidate] = relationship()
    resume: Mapped[Resume] = relationship()
    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.position",
    )
    """Ordered by `position`, not by time.

    Timestamps looked sufficient and were not: SQLite's `CURRENT_TIMESTAMP` has
    **one-second** granularity, so a journey that takes a few milliseconds writes
    every event with an identical `created_at`, and the tiebreak falls through to a
    random UUID. The log came back shuffled. A sequence that is *usually* right is
    the wrong shape for an audit record, so the order is stored rather than
    inferred."""


class ApplicationEvent(UUIDPrimaryKey, Base):
    """One transition. Append-only — there is no code path that updates one.

    No `updated_at`, deliberately, where every other table here has one: a column
    called "when this was last changed" on an immutable record is an invitation.
    """

    __tablename__ = "application_events"
    __table_args__ = (
        # One event per place in a history. Also the index the log is read by.
        UniqueConstraint(
            "application_id", "position", name="uq_application_events_application_position"
        ),
        Index("ix_application_events_application_id", "application_id"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """0-based, per application, and the only thing the log is ordered by.

    Assigned by `application_service`, which is the single writer, from the highest
    position already stored. Unique per application, so two events cannot occupy the
    same place in a history."""

    from_state: Mapped[ApplicationState | None] = mapped_column(
        Enum(ApplicationState, native_enum=False, length=20)
    )
    """Null on the first event, which records the application being made rather
    than moved."""

    to_state: Mapped[ApplicationState] = mapped_column(
        Enum(ApplicationState, native_enum=False, length=20), nullable=False
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL")
    )
    """Who did it. **Null means the system** — a worker following a screening is not
    a person, and recording one would be a small lie in an audit log. `SET NULL`
    rather than `CASCADE` because deleting an account must not delete the history of
    what happened to other people's applications; PDPA's erasure is slice 4's
    problem and it should face this explicitly rather than inherit it."""

    actor_role: Mapped[Role | None] = mapped_column(Enum(Role, native_enum=False, length=20))
    """The role the actor held *at the time*. Stored rather than joined because a
    role can change, and an audit entry should say what was true when it happened."""

    reason: Mapped[str | None] = mapped_column(Text)
    """Required for a rejection, optional elsewhere. Nothing about a person
    disappears silently — the same instinct as `dropped` and `excluded`."""

    screening_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("screenings.id", ondelete="SET NULL")
    )
    """What the move rested on, where it rested on anything. Set for the transitions
    the system derives from a screening, and for a shortlist — which is refused
    outright without one."""

    note: Mapped[str | None] = mapped_column(String(200))
    """A short machine-written description of *why the system* moved it, for the
    transitions no person made."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application: Mapped[Application] = relationship(back_populates="events")
