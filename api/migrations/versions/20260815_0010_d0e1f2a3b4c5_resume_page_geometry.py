"""Record where each character of a resume's stored text sits on its page.

Written by hand, like the migrations before it, so the JSONB variant is not
flattened by autogenerating against SQLite. `JSON_VARIANT` renders JSONB on
Postgres and JSON on SQLite, matching `page_spans` beside it.

What it is for: the pdf.js overlay (M5 slice 4) has to draw a box around an
evidence span, and until now no stored row could say where on a page a character
range sits — `page_spans` holds page boundaries and `EvidenceRef` holds character
offsets and a page number, and neither is a position. `layout.py` computes bounding
boxes to *crop* columns and discards them inside the same function.

Nullable **and deliberately not backfilled**, exactly like `page_spans` in `0005`
and for the same reason: filling it in would mean re-parsing every stored file under
the identical OCR configuration, and a page rescued by OCR then but not now would
come back empty and move every offset after it. A null here means the overlay falls
back to the text pane and says why — a state it has to support regardless, since a
page recovered by OCR has no glyph boxes to overlay onto either.

The column is sparse even on rows that have it: a page whose measured geometry could
not be proven consistent with its text is absent rather than approximated. See
`app/pipeline/geometry.py` for why a wrong box is worse than no box here.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.base import JSON_VARIANT

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("resumes", sa.Column("page_geometry", JSON_VARIANT, nullable=True))


def downgrade() -> None:
    op.drop_column("resumes", "page_geometry")
