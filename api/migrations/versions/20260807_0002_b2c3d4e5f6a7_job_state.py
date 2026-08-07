"""Job state on resumes: attempt counters and when the last attempt ran.

Written by hand, like the initial migration, so the JSONB variant is not flattened
by autogenerating against SQLite.

`status` needs no change: `ResumeStatus` renders as a plain VARCHAR(20) with no
CHECK constraint, so the new `processing` and `dead_lettered` values fit as they
are. The existing rows are all pre-retry work, so both counters start at zero and
`last_attempt_at` starts null.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills the existing rows; the model supplies the default
    # for new ones, so it is dropped again below.
    op.add_column(
        "resumes", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "resumes", sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "resumes", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )

    with op.batch_alter_table("resumes") as batch:
        batch.alter_column("attempts", server_default=None)
        batch.alter_column("failed_attempts", server_default=None)


def downgrade() -> None:
    op.drop_column("resumes", "last_attempt_at")
    op.drop_column("resumes", "failed_attempts")
    op.drop_column("resumes", "attempts")
