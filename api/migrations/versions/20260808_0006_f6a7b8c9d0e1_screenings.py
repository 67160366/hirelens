"""One resume judged against one job's requirements.

Written by hand, like the migrations before it, so the JSONB variant is not
flattened by autogenerating against SQLite.

`screeningstatus` is spelled in upper case because that is what lands in the
column: SQLAlchemy's `Enum` persists a Python enum's **name** while the API
serializes its value (`completed`). Same split as `resumestatus` and
`requirementkind` — `docs/HANDOFF.md` §7, and the reason a raw
`WHERE status = 'completed'` returns nothing.

`llm_call_logs.screening_id` lands here too. A judging call belongs to the
screening that paid for it; hanging it off the resume instead would make "what did
extracting this document cost" wrong, and leaving it unrecorded would make every
cost figure quietly incomplete.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.base import JSON_VARIANT

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCREENING_STATUS = sa.Enum(
    "PENDING",
    "PROCESSING",
    "COMPLETED",
    "FAILED",
    "DEAD_LETTERED",
    name="screeningstatus",
    native_enum=False,
    length=20,
)


def upgrade() -> None:
    op.create_table(
        "screenings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("resume_id", sa.Uuid(), nullable=False),
        sa.Column("status", SCREENING_STATUS, nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requirements_hash", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=60), nullable=True),
        sa.Column("result", JSON_VARIANT, nullable=True),
        sa.Column("requirements_met", sa.Integer(), nullable=False),
        sa.Column("requirements_total", sa.Integer(), nullable=False),
        sa.Column("claims_verified", sa.Integer(), nullable=False),
        sa.Column("claims_dropped", sa.Integer(), nullable=False),
        sa.Column("hallucination_rate", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_screenings_job_id_jobs", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resume_id"],
            ["resumes.id"],
            name="fk_screenings_resume_id_resumes",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_screenings"),
        sa.UniqueConstraint("job_id", "resume_id", name="uq_screenings_job_resume"),
    )
    op.create_index("ix_screenings_job_id", "screenings", ["job_id"])
    op.create_index("ix_screenings_resume_id", "screenings", ["resume_id"])
    op.create_index("ix_screenings_status", "screenings", ["status"])

    # Batch mode, because SQLite cannot ALTER a constraint onto an existing table
    # and CI runs `alembic upgrade head` against SQLite (`.github/workflows/ci.yml`).
    # On Postgres this emits the ordinary ALTERs; on SQLite it rebuilds the table
    # copy-and-move. Declaring the foreign key inline on the column does *not*
    # avoid this — alembic adds the column and then adds each of its constraints as
    # a separate statement, so the inline form fails identically.
    with op.batch_alter_table("llm_call_logs") as batch_op:
        batch_op.add_column(sa.Column("screening_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_llm_call_logs_screening_id_screenings",
            "screenings",
            ["screening_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.create_index("ix_llm_call_logs_screening_id", "llm_call_logs", ["screening_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_logs_screening_id", table_name="llm_call_logs")
    # Batch mode again: dropping the column takes the foreign key with it, and on
    # SQLite that still means rebuilding the table.
    with op.batch_alter_table("llm_call_logs") as batch_op:
        batch_op.drop_column("screening_id")

    op.drop_table("screenings")
