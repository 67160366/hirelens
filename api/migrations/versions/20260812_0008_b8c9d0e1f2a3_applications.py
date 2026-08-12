"""A candidate applying to a job, and the log of every move that application made.

Written by hand like the migrations before it.

Two tables, and the relationship between them is the milestone's whole idea:
`applications.state` is a *projection* of `application_events`, which is
append-only. Nothing here enforces that — a database cannot tell a projection from
a fact — so it is held by `app/services/application_service.py` being the only
writer of both, and by `tests/test_applications.py` replaying the log and comparing.

Three things worth knowing about the columns:

*   **Both enums declare their upper-case names.** SQLAlchemy persists enum member
    names, so `WHERE state = 'applied'` returns nothing against data you just
    watched go in. `0004` established the shape; `0001`'s lower-case list is the
    counterexample.
*   **`application_events.actor_id` is `SET NULL`, not `CASCADE`.** Deleting an
    account must not delete the record of what happened to *other people's*
    applications — the audit entry survives with the actor anonymised, which is
    also the shape PDPA erasure wants. Everything else cascades, because an
    application with no job or no resume describes nothing.
*   **`application_events` has no `updated_at`**, alone among the tables here. A
    column named "when this was last changed" on an append-only record is an
    invitation, and there is no code path that updates one.
*   **`position` is what the log is ordered by, not `created_at`.** SQLite's
    `CURRENT_TIMESTAMP` has one-second granularity, so a journey that takes
    milliseconds writes every event with the same timestamp and the order falls
    through to a random UUID — watched, in a test that came back shuffled. The
    unique constraint on `(application_id, position)` is what makes the sequence a
    fact rather than a probability.

Both foreign keys are declared inline in `create_table`, which is safe on SQLite —
`0006`'s lesson was about `create_foreign_key` against a table that *already
exists*, where SQLite cannot ALTER a constraint on at all.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATE_ENUM = sa.Enum(
    "APPLIED",
    "SCREENING",
    "SCREENED",
    "SHORTLISTED",
    "REJECTED",
    "WITHDRAWN",
    name="applicationstate",
    native_enum=False,
    length=20,
)

ROLE_ENUM = sa.Enum(
    "CANDIDATE",
    "RECRUITER",
    "ADMIN",
    name="role",
    native_enum=False,
    length=20,
)


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("state", STATE_ENUM, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_applications_job_id_jobs", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name="fk_applications_candidate_id_candidates",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resume_id"],
            ["resumes.id"],
            name="fk_applications_resume_id_resumes",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_applications"),
        # The natural idempotency key: applying twice is the same act, so the second
        # request answers 200 with this row rather than needing a key table.
        sa.UniqueConstraint("job_id", "candidate_id", name="uq_applications_job_candidate"),
    )
    op.create_index("ix_applications_job_id", "applications", ["job_id"])
    op.create_index("ix_applications_candidate_id", "applications", ["candidate_id"])
    op.create_index("ix_applications_resume_id", "applications", ["resume_id"])
    op.create_index("ix_applications_state", "applications", ["state"])

    op.create_table(
        "application_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("from_state", STATE_ENUM, nullable=True),
        sa.Column("to_state", STATE_ENUM, nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_role", ROLE_ENUM, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("screening_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name="fk_application_events_application_id_applications",
            ondelete="CASCADE",
        ),
        # SET NULL: erasing an account anonymises its entries in other people's
        # history rather than deleting that history.
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["candidates.id"],
            name="fk_application_events_actor_id_candidates",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["screening_id"],
            ["screenings.id"],
            name="fk_application_events_screening_id_screenings",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_application_events"),
        # One event per place in a history: two claiming the same position
        # would make the log unorderable, which is the whole point of it.
        sa.UniqueConstraint(
            "application_id", "position", name="uq_application_events_application_position"
        ),
    )
    op.create_index(
        "ix_application_events_application_id", "application_events", ["application_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_application_events_application_id", table_name="application_events")
    op.drop_table("application_events")
    op.drop_index("ix_applications_state", table_name="applications")
    op.drop_index("ix_applications_resume_id", table_name="applications")
    op.drop_index("ix_applications_candidate_id", table_name="applications")
    op.drop_index("ix_applications_job_id", table_name="applications")
    op.drop_table("applications")
