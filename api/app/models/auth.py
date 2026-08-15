"""Revoked tokens — the thing that makes a signed-out session actually signed out.

Access and refresh tokens are stateless JWTs, so until now nothing could take one
back. `POST /auth/change-password` said so in a characterization test, and there was
no `/auth/logout` at all, because a route that only asks the client to forget its
token is theatre. `docs/RUNBOOK.md` made the gap concrete rather than theoretical:
rotating `JWT_SECRET` was the *only* revocation available, and it signs everybody out
at once.

**The identity this rests on was already there.** `security.py` has put a `jti` in
every token since M1, with a comment saying it exists "so revocation can be added
without reissuing the whole scheme". So this table revokes tokens that were already
issued, and no token format changes.

**A table rather than Redis**, for two reasons. The suite runs on in-memory SQLite
with no server, and a denylist behind a Redis-only backend would break the no-server
default that `fake.py`, `JSON_VARIANT` and `QUEUE_BACKEND=inline` all exist to keep.
And more importantly: `docker-compose.yml` runs Redis with `--save "" --appendonly
no`, so **a denylist there would forget every revocation on restart** — a denylist
that forgets is a denylist that quietly un-revokes, which is worse than not having
one, because the operator believes the session is dead.

The table only ever holds tokens that have not yet expired; `purge_expired` sweeps
the rest on the same arq cron that reclaims stalled jobs. So it grows with
outstanding sessions, not with history.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class RevocationReason(StrEnum):
    """Why a token stopped being accepted.

    Stored so an operator answering "why am I signed out" has an answer, and because
    the three cases are genuinely different events rather than one with three names.
    """

    LOGOUT = "logout"
    """Somebody signed out deliberately."""

    REFRESH_ROTATED = "refresh_rotated"
    """A refresh token was spent for a new pair.

    `POST /auth/refresh` has always issued a fresh pair and left the presented token
    valid for the rest of its fourteen days, so a stolen refresh token stayed usable
    *even after the real user had rotated it*. This is the reason that closes that.
    """

    PASSWORD_CHANGED = "password_changed"
    """The account's password changed, so the tokens proving the old one are void."""


class RevokedToken(Base):
    """One token that will not be accepted again, until it expires on its own."""

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(32), primary_key=True)
    """The token's own id, straight out of the JWT. `uuid4().hex`, so 32 characters.

    The primary key rather than a surrogate: the question this table answers is
    "is *this* token revoked", and that is a primary-key lookup rather than a scan.
    """

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        # Erasure removes the account, and `get_current_candidate` already answers
        # 401 for a token whose account is gone — so keeping revocation rows for a
        # deleted account would be retaining a fragment of them for nothing. PDPA
        # again: delete means delete.
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    token_type: Mapped[str] = mapped_column(String(16), nullable=False)
    """`access` or `refresh`, as the token itself spells it."""

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    """When the token would have expired anyway, and so when this row stops mattering.

    Indexed because the cron sweep's only query is `expires_at < now()`.
    """

    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, nullable=False
    )

    reason: Mapped[RevocationReason] = mapped_column(
        Enum(RevocationReason, native_enum=False, length=20), nullable=False
    )
