"""Tables for M3: a job posting, broken into the requirements it is judged by.

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
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.core import Candidate


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
    """Relative importance among the requirements that are not gates."""

    job: Mapped[Job] = relationship(back_populates="requirements")
