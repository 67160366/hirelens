"""Job postings, and the requirements a candidate is judged against.

Written by hand, like the migrations before it: autogenerate has to run against a
live database, and running it against SQLite flattens the JSONB variant used on
Postgres into plain JSON.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches the model's `Enum(..., native_enum=False)`: a VARCHAR rather than a
# Postgres enum type, so adding a kind later is a code change and not a migration
# that has to rewrite a type while rows reference it.
#
# Spelled in upper case because that is what actually lands in the column:
# SQLAlchemy's `Enum` persists a Python enum's **name**, while the API serializes
# its value (`skill`). `resumestatus` in `0001` has the same split and lists the
# values instead — harmless there because `native_enum=False` emits no CHECK
# constraint to disagree with, but a reader grepping a migration for what is in a
# column should not be told the wrong thing. Any raw SQL against `kind` wants the
# upper-case form (`docs/HANDOFF.md` §7).
REQUIREMENT_KIND = sa.Enum(
    "SKILL",
    "EXPERIENCE",
    "EDUCATION",
    "LANGUAGE",
    "OTHER",
    name="requirementkind",
    native_enum=False,
    length=20,
)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["candidates.id"],
            name="fk_jobs_owner_id_candidates",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )
    op.create_index("ix_jobs_owner_id", "jobs", ["owner_id"])

    op.create_table(
        "job_requirements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", REQUIREMENT_KIND, nullable=False),
        sa.Column("label", sa.String(length=300), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("must_have", sa.Boolean(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # The bare name, not the rendered one: `ck` is the only convention in
        # `models/base.py` that interpolates `%(constraint_name)s`, so passing the
        # full `ck_job_requirements_weight_positive` here gets wrapped a second
        # time and `alembic check` then reports drift against the model forever.
        # The fk/pk/uq names above are safe spelled out — their conventions do not
        # reference the given name at all.
        sa.CheckConstraint("weight > 0", name="weight_positive"),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_job_requirements_job_id_jobs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_job_requirements"),
    )
    op.create_index(
        "ix_job_requirements_job_id_position", "job_requirements", ["job_id", "position"]
    )


def downgrade() -> None:
    op.drop_table("job_requirements")
    op.drop_table("jobs")
