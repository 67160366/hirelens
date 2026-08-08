"""Record where each page begins and ends inside a resume's stored text.

Written by hand, like the migrations before it, so the JSONB variant is not
flattened by autogenerating against SQLite.

`JSON_VARIANT` renders JSONB on Postgres and JSON on SQLite, matching
`pages_from_ocr` and `pages_without_text` beside it.

Nullable **and deliberately not backfilled.** Extraction never needed these spans —
it reads the live `ParsedDocument` it just built — so nothing already stored is
wrong without them; they exist because judging locates a *new* quote in text that
was parsed long ago and still has to name a page. Filling them in for existing rows
would mean re-parsing every stored file under the identical OCR configuration, and
a page rescued by OCR then but not now would come back empty and move every offset
after it. A null here makes `ParsedDocument.from_stored` report page 1, which is
the honest answer for a row that never recorded its page boundaries.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.base import JSON_VARIANT

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("resumes", sa.Column("page_spans", JSON_VARIANT, nullable=True))


def downgrade() -> None:
    op.drop_column("resumes", "page_spans")
