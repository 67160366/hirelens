"""Give a posting an editorial life: draft, published, closed.

Written by hand like the migrations before it.

**This migration is what gates every public route the careers site adds.** Until it
exists, `Job` carries only `owner_id`, `title` and `description`, so "which postings may
a stranger see?" has no answer in the data and any public board would have to invent one.
`SelfServiceRole` lets anyone register as a recruiter, so shipping a public page before
this would mean anyone who can register can publish under HireLens's name. Default
`DRAFT`, and `app/publication.py` is the only place that decides who may leave it.

**Everything that already exists is backfilled to `PUBLISHED`, not to the default.**
That is deliberate and it is the opposite of what a default suggests. Every posting in
this database predates the concept, and the behaviour they have today is that any
signed-in account can read them (`_readable_job`) and apply to them. Backfilling them to
`draft` would silently withdraw live postings from the candidates already applying to
them — a migration that breaks the running system on the way to making it safer. New
postings start as drafts; existing ones keep the status they effectively already had.
`published_at` is backfilled from `created_at` for the same reason: a board ordering by
publication date must not put every historical posting at the bottom with a null.

**The enum is declared with its upper-case names.** SQLAlchemy's `Enum` persists member
*names*, not values, so the database holds `DRAFT` while the API serializes `draft` — the
same split `Role`, `ResumeStatus` and `RequirementKind` already have, and the thing
migration `0001` got wrong harmlessly and `0004` stopped copying.

`batch_alter_table` because CI runs this on SQLite, where an ALTER that adds a
constrained column has to be a table rebuild — the lesson migration `0006` paid for. The
server default is dropped once the backfill has run: it exists to make the column NOT
NULL for rows that already exist, and leaving it behind would let an INSERT that forgets
a status quietly succeed.

**The downgrade loses only what it must.** Dropping the three columns discards the
publication state, and no version of it could not. Re-running this migration forward
after a downgrade republishes everything, which is right for the pre-publication data it
was written for and wrong for a database where drafts already exist — so re-run it only
if you are prepared to re-hide them.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_STATUS_ENUM = sa.Enum(
    "DRAFT",
    "PUBLISHED",
    "CLOSED",
    name="jobstatus",
    native_enum=False,
    length=20,
)


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(
            sa.Column("status", JOB_STATUS_ENUM, nullable=False, server_default="DRAFT")
        )
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("location", sa.String(length=120), nullable=True))

    # Every posting that already exists was readable by any signed-in account and
    # could be applied to, so `published` is the status it effectively already had.
    # Backfilling to the column default would take live postings away from the
    # candidates looking at them.
    op.execute("UPDATE jobs SET status = 'PUBLISHED', published_at = created_at")

    with op.batch_alter_table("jobs") as batch:
        batch.alter_column("status", server_default=None)

    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status", table_name="jobs")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("location")
        batch.drop_column("published_at")
        batch.drop_column("status")
