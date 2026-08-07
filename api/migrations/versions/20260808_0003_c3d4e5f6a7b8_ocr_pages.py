"""Record which pages were read by OCR rather than from a text layer.

Written by hand, like the migrations before it, so the JSONB variant is not
flattened by autogenerating against SQLite.

`JSON_VARIANT` renders JSONB on Postgres and JSON on SQLite, matching
`pages_without_text` beside it. Nullable with no backfill: every existing row was
parsed before OCR existed, so "no pages came from OCR" is the truth for all of
them, and null already says that to `ResumeOut`, which reads it as an empty list.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.base import JSON_VARIANT

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("resumes", sa.Column("pages_from_ocr", JSON_VARIANT, nullable=True))


def downgrade() -> None:
    op.drop_column("resumes", "pages_from_ocr")
