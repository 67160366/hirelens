"""Taking a token back.

The other half of `app.security`, which verifies what a token *says* — signature,
type, expiry — and deliberately holds no database session. Whether a token has been
revoked is a fact about the system rather than about the token, so it lives here.

The pairing to keep: **`decode_token` then `assert_live`.** Either alone is a hole.
Verifying without checking revocation accepts a token somebody signed out; checking
revocation without verifying trusts a `jti` an attacker chose. `assert_live` takes
the account row as a required argument so the pairing stays two things rather than
three — see its docstring.

**Two mechanisms live here, not one.** The denylist below answers "was *this token*
taken back". `Candidate.token_epoch` answers "is this token's whole *generation*
over", which is the question a password change asks and which no list of dead
tokens can answer.

Three things revoke, and they are `RevocationReason`'s three values:

  * **logout** — the session the caller is holding, which is the first time
    `/auth/logout` can mean anything here.
  * **refresh rotation** — the presented refresh token, once it has been spent.
    `POST /auth/refresh` has always issued a fresh pair and left the old token valid
    for the rest of its fourteen days, so a stolen one stayed usable after the real
    user had rotated it. This is the concrete hole the slice closes.
  * **password change** — the pair the caller presented.

**Other devices are the epoch's job, not the denylist's.** That used to be recorded
here as a limitation: nothing knows which tokens are outstanding, only which are
dead, so a password change had no list to walk. The fix named at the time was "a
session registry or a per-account epoch", and it is the epoch — bumping one integer
on the account ends every generation before it, with nothing enumerated. The two
mechanisms stay separate on purpose: one is about a token, the other about an
account, and collapsing them would mean either storing every live session or
signing out every device on an ordinary logout.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, RevocationReason, RevokedToken
from app.models.base import utcnow
from app.security import AuthError, TokenClaims

logger = logging.getLogger(__name__)


async def revoke(session: AsyncSession, claims: TokenClaims, reason: RevocationReason) -> None:
    """Refuse this token from now until it would have expired anyway.

    Idempotent on the `jti`: signing out twice, or two tabs racing to spend the same
    refresh token, must not raise. The first revocation is the one that stands — its
    reason is kept rather than overwritten, because "why was this revoked" should
    answer with what actually happened first.

    The insert is guarded by a SAVEPOINT rather than by an `ON CONFLICT` clause, and
    that is deliberate: `on_conflict_do_nothing` is spelled per dialect, and the
    SQLite spelling runs happily on the SQLite the whole suite uses while failing on
    the Postgres that production runs — a green suite and a broken deployment, which
    is the same shape as SQLite silently ignoring `ON DELETE` before
    `PRAGMA foreign_keys=ON`. A nested transaction is portable, and the losing racer
    still ends up with exactly the row it wanted.

    **There was a `if await is_revoked(...): return` fast path here and it was
    deleted.** Mutation-testing showed the two guards were redundant — either alone
    passed every case, because the tests exercise sequential double-revocation and
    not a genuine race. The savepoint is the one that survives *both*: check-then-
    insert has a window between the check and the insert, so keeping the cheaper
    guard would have meant keeping the one that is only correct when nothing is
    concurrent. Same discipline as the separator reset deleted from
    `pipeline/geometry.py`: a line the tests prove cannot fail is not a careful line.

    Does not commit. The caller owns the transaction, the way every service here does.
    """
    try:
        async with session.begin_nested():
            session.add(
                RevokedToken(
                    jti=claims.jti,
                    candidate_id=claims.subject,
                    token_type=claims.token_type,
                    expires_at=claims.expires_at,
                    revoked_at=utcnow(),
                    reason=reason,
                )
            )
    except IntegrityError:
        # Already revoked — by an earlier call, or by another connection between this
        # statement being built and executed. The end state is the one this call was
        # asking for, so it is a success, and the first reason recorded is the one
        # that stands.
        logger.debug("token already revoked")


async def is_revoked(session: AsyncSession, jti: str) -> bool:
    """Whether this token has been taken back. A primary-key lookup."""
    found = await session.scalar(select(RevokedToken.jti).where(RevokedToken.jti == jti))
    return found is not None


async def assert_live(session: AsyncSession, claims: TokenClaims, candidate: Candidate) -> None:
    """Raise `AuthError` unless this token is still good: not revoked, and minted
    under the account's current epoch.

    Raises the same exception `decode_token` does, so every call site that already
    turns an `AuthError` into a 401 keeps working without learning a second failure
    mode — and a revoked, stale or invalid token are all indistinguishable to
    whoever presented one, which is the right amount to say.

    **`candidate` is required rather than looked up here, and that is the design.**
    The standing rule is that `decode_token` and `assert_live` are called together;
    a third thing to remember would be the one somebody forgets, so instead the
    account row is a parameter and mypy refuses a call that has not loaded it. You
    cannot check a token without having looked up whose it is. It costs nothing:
    every caller needs the row anyway, and SQLAlchemy's identity map means a second
    `session.get` for the same id is not a second query.

    The two halves answer different questions. The denylist knows about *this
    token* — it was signed out, or spent on a refresh. The epoch knows about *this
    account* — everything issued before a password change is over, including the
    sessions nothing recorded.
    """
    if await is_revoked(session, claims.jti):
        raise AuthError("Invalid token: revoked")
    if claims.epoch != candidate.token_epoch:
        raise AuthError("Invalid token: superseded")


async def purge_expired(session: AsyncSession) -> int:
    """Delete revocations for tokens that have expired on their own.

    Once a token is past its own `exp`, `decode_token` rejects it without help, so
    the row stops carrying information. Sweeping is what keeps the table sized by
    outstanding sessions rather than by history.

    Returns the number of rows removed. Does not commit.
    """
    result = await session.execute(delete(RevokedToken).where(RevokedToken.expires_at < utcnow()))
    # `CursorResult.rowcount` is the count of rows the DELETE matched. Typed off the
    # generic `Result`, which does not declare it, so it is narrowed rather than
    # ignored.
    return int(cast("CursorResult[Any]", result).rowcount or 0)
