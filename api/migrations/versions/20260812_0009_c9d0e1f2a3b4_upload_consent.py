"""Record that somebody agreed to a document being processed, and to what.

Written by hand like the migrations before it.

Two columns, both nullable, and the nullability is the interesting part.
`consented_at` cannot be backfilled: nobody was asked. Writing "now" onto existing
rows would fabricate an agreement that never happened, which is worse than the gap
it papers over — so pre-`0009` rows say **null**, meaning "we do not have a record
of consent for this", which is the truth. The upload route refuses without consent,
so nothing new can arrive that way.

`consent_version` sits beside the timestamp rather than being implied by it, the
same shape as `prompt_version` beside `requirements_hash`: "they consented" and
"they consented to *this wording*" are different claims, and only one of them
survives the text being reworded.

`batch_alter_table` for the reason `0007` used it — CI applies this to SQLite, and
a plain ALTER there is a table rebuild.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("resumes") as batch:
        batch.add_column(sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("consent_version", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("resumes") as batch:
        batch.drop_column("consent_version")
        batch.drop_column("consented_at")
