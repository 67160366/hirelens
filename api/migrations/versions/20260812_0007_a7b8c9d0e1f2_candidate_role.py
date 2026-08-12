"""Give an account a role: candidate, recruiter or admin.

Written by hand like the migrations before it.

**The enum is declared with its upper-case names.** SQLAlchemy's `Enum` persists
member *names*, not values, so the database holds `RECRUITER` while the API
serializes `recruiter` — the same split `ResumeStatus` and `RequirementKind`
already have. Migration `0001` listed the lower-case values, which is misleading
but inert under `native_enum=False`; `0004` stopped copying it and so does this.

**The backfill is derived from the data rather than guessed.** Until now one
account both uploaded resumes and owned job postings, so neither default is right
for everyone: making everybody a candidate would orphan every existing posting from
the routes that manage it, and making everybody a recruiter would hand the role to
accounts that never posted anything. Who owns a job is a fact already in the
database, so that is what decides it. Anyone else becomes a candidate.

**The downgrade loses information, and no version of it could not.** Dropping the
column discards the only place a role is recorded, so re-applying this migration
re-derives every role from `jobs` — and a recruiter who has not yet posted anything
comes back a *candidate*. Watched on Postgres rather than assumed, 2026-08-12.
Running forward once over pre-role data, which is what this migration is for, that
is exactly right: nobody had a role then and owning a job is the only signal there
is. On a database where roles already exist it is a demotion, so re-run it only if
you are prepared to re-grant them.

`batch_alter_table` because CI runs this on SQLite (`Verify migrations apply and
reverse`), where an ALTER that adds a constrained column has to be a table rebuild —
the lesson migration `0006` paid for. The server default is dropped once the backfill
has run: it exists to make the column NOT NULL for rows that already exist, and
leaving it behind would let an INSERT that forgets a role quietly succeed.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_ENUM = sa.Enum(
    "CANDIDATE",
    "RECRUITER",
    "ADMIN",
    name="role",
    native_enum=False,
    length=20,
)


def upgrade() -> None:
    with op.batch_alter_table("candidates") as batch:
        batch.add_column(sa.Column("role", ROLE_ENUM, nullable=False, server_default="CANDIDATE"))

    # Every account that owns a posting was acting as a recruiter, whatever the
    # column would otherwise have defaulted them to.
    op.execute(
        "UPDATE candidates SET role = 'RECRUITER' WHERE id IN (SELECT DISTINCT owner_id FROM jobs)"
    )

    with op.batch_alter_table("candidates") as batch:
        batch.alter_column("role", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("candidates") as batch:
        batch.drop_column("role")
