"""Give an account a token generation, so a password change can end all of them.

Written by hand like the migrations before it.

**Why a counter on the account rather than a row per session.** The denylist
migration `0011` added records tokens that are *dead*; nothing anywhere records
which are outstanding, so a password change had no list to walk and a session on
another device kept working for the refresh token's full fourteen days. The two
honest fixes were a session registry or this. A registry means a write on every
login and a row per live session to sweep; a counter means one integer, no writes
outside the password path, and nothing to keep in sync — and it answers the whole
question, because ending a *generation* does not require knowing its members.

**The backfill is zero, and that is what keeps tokens already in browsers
working.** `decode_token` reads a missing `epoch` claim as zero, so a token minted
before this migration matches a row it has never heard of. They are not
grandfathered past anything: the first password change moves the row to one and
they stop verifying with everything else. This is the same shape as `0011`, where
the `jti` had been in every token since M1 and no token format changed.

`batch_alter_table` because CI runs this on SQLite (`Verify migrations apply and
reverse`), where an ALTER that adds a NOT NULL column has to be a table rebuild —
the lesson migration `0006` paid for. The server default is dropped once existing
rows are filled: it exists for them alone, and leaving it behind would let an
INSERT that forgets the epoch quietly succeed.

**The downgrade signs everybody out, and no version of it could not.** Dropping
the column discards the only record of which generation is current, so tokens
minted at epoch 3 have nothing left to match. That is the correct failure — every
one of them is refused rather than accepted on a guess — but it means a downgrade
on a live database is a forced re-login, not a no-op.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("candidates") as batch:
        batch.add_column(sa.Column("token_epoch", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("candidates") as batch:
        batch.alter_column("token_epoch", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("candidates") as batch:
        batch.drop_column("token_epoch")
