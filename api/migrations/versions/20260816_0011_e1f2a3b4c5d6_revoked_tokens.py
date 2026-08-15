"""Let a token be taken back before it expires.

Access and refresh tokens are stateless JWTs, so until this table nothing could
revoke one. `POST /auth/change-password` said as much in its own docstring and there
was no `/auth/logout` at all, because a logout route with no denylist behind it
reports success while the token goes on working. `docs/RUNBOOK.md` turned that from a
theoretical gap into an operational one: rotating `JWT_SECRET` was the only revocation
available, and it signs every account out at once.

The concrete hole this closes is in `POST /auth/refresh`, which has always issued a
fresh pair and left the presented refresh token valid for the rest of its fourteen
days — so a stolen refresh token kept working *after* the real user had rotated it,
and neither of them could tell.

Nothing about the token format changes. `security.py` has put a `jti` in every token
since M1 with a comment saying it exists so revocation could be added later, so this
revokes tokens that are already in people's browsers.

Written by hand like the migrations before it. Two things it repeats from earlier
lessons: the enum is declared as `native_enum=False` with the **upper-case names**
SQLAlchemy actually persists (`0004`'s lesson, and `0007`'s), and the whole thing is
plain `create_table`, which needs no `batch_alter_table` because it alters nothing.

`revoked_at` carries a server default so a row inserted outside the application still
records when it happened.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "revoked_tokens",
        # The JWT's own id — `uuid4().hex`, so 32 characters. The primary key rather
        # than a surrogate, because the only question this table answers is "is *this*
        # token revoked", and that should be a primary-key lookup on every
        # authenticated request.
        sa.Column("jti", sa.String(length=32), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("token_type", sa.String(length=16), nullable=False),
        # When the token dies on its own, and so when this row stops meaning anything.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Enum(
                "LOGOUT",
                "REFRESH_ROTATED",
                "PASSWORD_CHANGED",
                name="revocationreason",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        # Erasure deletes the account; keeping its revocation rows would be retaining
        # a fragment of somebody who asked to be forgotten, for a token that
        # `get_current_candidate` already refuses because the account is gone.
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_revoked_tokens_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("jti", name=op.f("pk_revoked_tokens")),
    )
    op.create_index(
        op.f("ix_revoked_tokens_candidate_id"), "revoked_tokens", ["candidate_id"], unique=False
    )
    # The cron sweep's only query is `expires_at < now()`.
    op.create_index(
        op.f("ix_revoked_tokens_expires_at"), "revoked_tokens", ["expires_at"], unique=False
    )


def downgrade() -> None:
    # Dropping this un-revokes every outstanding revocation — a signed-out session
    # becomes live again, and a token revoked because its account's password changed
    # starts working. That is not recoverable by re-running the upgrade, because the
    # rows are the only record. Worth knowing before reaching for it, which is the
    # same warning `0007` carries about the role backfill.
    op.drop_index(op.f("ix_revoked_tokens_expires_at"), table_name="revoked_tokens")
    op.drop_index(op.f("ix_revoked_tokens_candidate_id"), table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
