"""Tables for M3: a job posting, the requirements it is judged by, and a screening.

A requirement is an **input** to the system, not a claim about a person. Nothing
here is model-generated, so nothing here needs evidence — the guardrail applies to
the judgments these produce (`app/pipeline/judge.py`), not to the requirements
themselves. That is why they are typed in through CRUD rather than decomposed out
of a pasted job description: a model in front of this step would add a failure mode
without adding a guarantee.

Ownership is a `Candidate` row because that is the only actor the system has.
Recruiter and admin roles are M4's RBAC work, which widens *who* may own a job
without changing the shape of these tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import JSON_VARIANT, Base, Timestamps, UUIDPrimaryKey
from app.models.core import Candidate, Resume


class RequirementKind(StrEnum):
    """What sort of thing a requirement asks for.

    Carried because the judge is prompted differently per kind — a skill is looked
    for as a mention, a duration has to be shown by a date range — and because M3's
    retrieval slice ranks claims differently depending on it.
    """

    SKILL = "skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    LANGUAGE = "language"
    OTHER = "other"


class JobStatus(StrEnum):
    """Where a posting is in its editorial life.

    Stored as the enum **name** (`DRAFT`), serialized as the value (`draft`) —
    the same split `Role`, `ResumeStatus` and `RequirementKind` already have.

    Reversible on purpose, and `app/publication.py` says why at length: a
    posting's status is an editorial fact about a document the employer wrote,
    not a claim about a person, so it needs no append-only log and taking one
    down is an ordinary thing to do.
    """

    DRAFT = "draft"
    """Written, editable, and visible to nobody but its owner. The default, and
    the only status a posting can be created in."""

    PUBLISHED = "published"
    """On the public careers site. **Only an admin may set this** — anyone can
    register as a recruiter, so publishing cannot be a power an account grants
    itself."""

    CLOSED = "closed"
    """No longer accepting applications. Distinct from `draft`: a closed posting
    was public and the applications against it are still real, so it is not the
    same thing as one that never appeared."""


class Job(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "jobs"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    description: Mapped[str | None] = mapped_column(Text)
    """The posting as it was written, kept for context and audit.

    Deliberately *not* what a candidate is judged against — the requirements below
    are. Judging free text would make it impossible to say which part of a posting a
    verdict answered.
    """

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=20),
        default=JobStatus.DRAFT,
        nullable=False,
        index=True,
    )
    """Draft until an admin publishes it. Indexed because the public board's
    only filter is this column."""

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When it first became public, or null while it never has.

    A separate column rather than reading `updated_at`, because a board orders by
    *when a posting appeared* and an edit to a live posting must not send it back
    to the top. Set once and left alone: republishing something that was taken
    down does not make it new.
    """

    location: Mapped[str | None] = mapped_column(String(120))
    """Where the work is, as free text. Null while nobody has said.

    Free text rather than a taxonomy: "Bangkok", "Remote (Thailand)" and
    "Hybrid — Chiang Mai" are all answers a real posting gives, and nothing in
    this system reasons about it. A verdict is never derived from it.
    """

    owner: Mapped[Candidate] = relationship()
    requirements: Mapped[list[JobRequirement]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobRequirement.position",
    )


class JobRequirement(UUIDPrimaryKey, Timestamps, Base):
    """One thing a candidate is judged against, judged on its own."""

    __tablename__ = "job_requirements"
    __table_args__ = (
        CheckConstraint("weight > 0", name="weight_positive"),
        Index("ix_job_requirements_job_id_position", "job_id", "position"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )

    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Display and prompt order. Not unique per job: reordering a list under a
    unique constraint needs a two-phase update to dodge a collision mid-swap, and
    nothing here is harmed by two requirements briefly sharing a position."""

    kind: Mapped[RequirementKind] = mapped_column(
        Enum(RequirementKind, native_enum=False, length=20),
        default=RequirementKind.OTHER,
        nullable=False,
    )

    label: Mapped[str] = mapped_column(String(300), nullable=False)
    """The requirement in one line — "Python", "3+ years backend", "ปริญญาตรี".
    Short because it is what the UI shows beside a verdict."""

    detail: Mapped[str | None] = mapped_column(Text)
    """Optional elaboration the judge also sees, for a requirement a label cannot
    hold on its own."""

    must_have: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    """A hard gate in ranking rather than a heavy weight: a candidate missing one
    ranks below every candidate that has them all, however well they score
    elsewhere."""

    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    """Relative importance when ranking, over *all* requirements including gates.

    Counting a must-have's weight changes no order inside the tier that passed the
    gate — everyone there met it — but it is what separates "missing one gate" from
    "missing every gate" among those that failed, and it keeps the denominator
    non-zero for a job made entirely of must-haves (`app/pipeline/ranking.py`)."""

    job: Mapped[Job] = relationship(back_populates="requirements")


class ScreeningStatus(StrEnum):
    """Deliberately *not* `ResumeStatus`, though they rhyme.

    A screening is never `parsed` or `extracted` — those describe a document, and
    this describes a comparison. The shared part is the retry policy, and that is
    shared as a function (`jobs.decide_retry`) rather than by making two tables wear
    one vocabulary.
    """

    PENDING = "pending"
    """Queued, or waiting out a retry backoff."""

    PROCESSING = "processing"
    """A worker has claimed it."""

    COMPLETED = "completed"
    """A judgment exists. Terminal — see `is_stale` for when it stops being current."""

    FAILED = "failed"
    """This screening cannot be produced: the resume has no text to judge, or the
    provider is misconfigured. Retrying changes nothing unless something else does."""

    DEAD_LETTERED = "dead_lettered"
    """Transient failures used up the budget. Worth replaying."""


class Screening(UUIDPrimaryKey, Timestamps, Base):
    """One resume judged against one job's requirements.

    A first-class row rather than a computed view, because producing it costs a
    model call: it has to be resumable, retryable and inspectable for the same
    reasons `Resume` does, and it carries the same four job-state columns so
    `jobs.decide_retry` can drive both.
    """

    __tablename__ = "screenings"
    __table_args__ = (
        # One screening per pair. Re-screening after the requirements change
        # rewrites this row rather than growing a history nobody reads yet — the
        # same call `Resume` makes for a re-uploaded file.
        UniqueConstraint("job_id", "resume_id", name="uq_screenings_job_resume"),
        Index("ix_screenings_status", "status"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[ScreeningStatus] = mapped_column(
        Enum(ScreeningStatus, native_enum=False, length=20),
        default=ScreeningStatus.PENDING,
        nullable=False,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """Total claims by a worker. Never reset — it is also what makes each dispatch's
    queue job id unique, so a replay is not refused as a duplicate."""

    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """The retry budget. Cleared by a success or a manual retry."""

    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requirements_hash: Mapped[str | None] = mapped_column(String(64))
    """Fingerprint of what the judge was actually shown — kind, label, detail and
    their order (`pipeline.judge.requirements_fingerprint`).

    Deliberately excludes `must_have` and `weight`: neither reaches the judge, so
    changing them cannot change a verdict. They are ranking's inputs, and changing
    one should stale a *ranking*, not a screening that is still correct."""

    prompt_version: Mapped[str | None] = mapped_column(String(60))
    """Which judging prompt produced this. Kept beside the hash rather than folded
    into it so "the requirements changed" and "we changed the prompt" stay
    distinguishable — they call for different conversations."""

    result: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT)
    """A serialized `Judgment`, dropped claims included."""

    # Lifted out of the JSON so the metrics query is a GROUP BY, not a JSON walk —
    # the same call `ExtractedProfileRow` makes.
    requirements_met: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    requirements_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claims_verified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claims_dropped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hallucination_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    job: Mapped[Job] = relationship()
    resume: Mapped[Resume] = relationship()

    def is_stale(self, *, requirements_hash: str, prompt_version: str) -> bool:
        """Whether this result answers a question that is no longer being asked.

        A completed screening whose job has since been edited is not wrong — it was
        true of the requirements it saw — so it is reported as stale rather than
        deleted or silently recomputed. Anything not yet completed is never stale:
        it has no answer to be out of date.
        """
        if self.status is not ScreeningStatus.COMPLETED:
            return False
        return self.requirements_hash != requirements_hash or self.prompt_version != prompt_version
