"""Registration and login.

Minimal but real: argon2 hashing, separate access and refresh tokens, and no
distinction in the error message between "no such account" and "wrong password".
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CandidateDep, ClaimsDep, SessionDep, SettingsDep, StorageDep
from app.config import Settings
from app.models import Candidate, RevocationReason, Role
from app.security import (
    TOKEN_TYPE_REFRESH,
    AuthError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services import privacy_service, token_service
from app.services.privacy_service import ErasureIncomplete

router = APIRouter(prefix="/auth", tags=["auth"])


class SelfServiceRole(StrEnum):
    """The roles an account may claim for itself.

    `admin` is absent on purpose: an account that can grant itself admin is not a
    role system. It is set out of band, which for now means a SQL statement.

    **`recruiter` being self-selectable is a known limitation, not a decision that
    an employer needs no verification.** Checking that someone really represents the
    company they say they do is an identity problem, and this project has no answer
    to it — so the limitation is written down (`README.md`) rather than papered over
    with a check that proves nothing. What the role does buy is real: a `candidate`
    account cannot reach a recruiter route at all.
    """

    CANDIDATE = "candidate"
    RECRUITER = "recruiter"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    role: SelfServiceRole = SelfServiceRole.CANDIDATE


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def _issue(settings: Settings, candidate: Candidate) -> TokenPair:
    """Mint a pair under the account's *current* epoch.

    One helper rather than four call sites spelling it out, because a pair minted
    under a stale epoch is refused on its first use — a failure that reads as a bug
    in authentication rather than as the omission it is. `change_password` in
    particular has to bump the row **before** calling this, or it hands back
    credentials it has just invalidated.
    """
    return TokenPair(
        access_token=create_access_token(settings, candidate.id, candidate.token_epoch),
        refresh_token=create_refresh_token(settings, candidate.id, candidate.token_epoch),
    )


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
    """Optional, because the access token alone still ends the current request's
    session — but omitting it leaves the session renewable for the refresh token's
    full lifetime, which is almost never what a caller means."""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class CandidateOut(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: Role
    """So a client can render the right home page without probing a route to see
    whether it 403s."""


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, session: SessionDep, settings: SettingsDep
) -> TokenPair:
    candidate = Candidate(
        email=payload.email.lower(),
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role=Role(payload.role.value),
    )
    session.add(candidate)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email is already registered"
        ) from exc

    return _issue(settings, candidate)


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenPair:
    result = await session.execute(
        select(Candidate).where(Candidate.email == payload.email.lower())
    )
    candidate = result.scalar_one_or_none()

    # One message for both failure modes, so the endpoint is not an account oracle.
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
    )
    if candidate is None or candidate.password_hash is None:
        raise invalid
    if not verify_password(payload.password, candidate.password_hash):
        raise invalid

    return _issue(settings, candidate)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, session: SessionDep, settings: SettingsDep) -> TokenPair:
    """Trade a refresh token for a fresh pair.

    The refresh token is rotated on every use; `decode_token` enforces the type,
    so an access token presented here is rejected just as a refresh token is on
    protected routes.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
    )
    try:
        claims = decode_token(settings, payload.refresh_token, expected_type=TOKEN_TYPE_REFRESH)
    except AuthError as exc:
        raise invalid from exc

    candidate = await session.get(Candidate, claims.subject)
    if candidate is None:
        raise invalid

    try:
        # Loaded first, then checked — `assert_live` compares the token's epoch
        # against the row, so a refresh token from a device that never saw the
        # password change is refused here rather than minting a fresh pair for it.
        await token_service.assert_live(session, claims, candidate)
    except AuthError as exc:
        raise invalid from exc

    # Rotation only means something if the token that was spent stops working. Until
    # this line, `refresh` issued a new pair and left the presented one valid for the
    # rest of its fourteen days — so a stolen refresh token kept working *after* the
    # real user had rotated it, and neither of them could tell.
    await token_service.revoke(session, claims, RevocationReason.REFRESH_ROTATED)
    await session.commit()

    return _issue(settings, candidate)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    claims: ClaimsDep,
    candidate: CandidateDep,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    """End this session: the access token that authenticated the call, and the
    refresh token behind it.

    **The first time this route can mean anything.** It did not exist before, and
    deliberately so — with no denylist, a `/auth/logout` that only asked the client to
    forget its token would report success while the token went on working, which is a
    worse answer than not offering the route at all.

    The refresh token is the one that matters, because it is what can mint new access
    tokens for the next fourteen days. It is taken in the body rather than inferred,
    since the server never sees it otherwise.

    A refresh token belonging to **somebody else is ignored rather than revoked**, or
    this route would be a way to sign out any account whose refresh token you had
    got hold of — the caller may only end their own session. It answers 204 either
    way, so it is not an oracle for whose token is whose.
    """
    await token_service.revoke(session, claims, RevocationReason.LOGOUT)

    if payload.refresh_token is not None:
        try:
            refresh_claims = decode_token(
                settings, payload.refresh_token, expected_type=TOKEN_TYPE_REFRESH
            )
        except AuthError:
            # A malformed or expired refresh token is nothing to do: it cannot mint
            # anything. The access token is already revoked above, so the session is
            # over either way and there is no reason to fail the call.
            refresh_claims = None
        if refresh_claims is not None and refresh_claims.subject == candidate.id:
            await token_service.revoke(session, refresh_claims, RevocationReason.LOGOUT)

    await session.commit()


@router.post("/change-password", response_model=TokenPair)
async def change_password(
    payload: ChangePasswordRequest,
    claims: ClaimsDep,
    candidate: CandidateDep,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenPair:
    """Change the signed-in account's password, proving the old one first.

    **Every session on every device ends here**, including ones this server has no
    record of. That is `Candidate.token_epoch`: each token carries the generation it
    was minted under, the bump below moves the account past all of them, and the
    next request any of them makes is refused. The old password's credentials should
    not outlive the old password, and until this landed only the caller's own did —
    a session on another machine kept working for the refresh token's full fourteen
    days, which was pinned as a known limitation rather than left to be discovered.

    Returns a fresh pair so the caller is not signed out by their own password
    change. The bump has to happen **before** the pair is minted, or `_issue` stamps
    the old epoch onto tokens that are already invalid.
    """
    if candidate.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account has no password set",
        )
    if not verify_password(payload.current_password, candidate.password_hash):
        # 403, not 401: the bearer token is fine, the claim about the old password
        # is not. A 401 would send a client into its token-refresh path for a
        # failure no new token can fix.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Current password is incorrect"
        )

    candidate.password_hash = hash_password(payload.new_password)
    candidate.token_epoch += 1
    # Redundant as a guard — the bump above already refuses this token — and kept
    # anyway, because it is the only *record* that the change ended anything.
    # Bumping an integer writes no history, so without this row a password change is
    # the one revocation an operator cannot see a reason for. Mutation-testing says
    # so plainly: deleting this line breaks no test, which is why one was written to
    # pin it rather than leaving a line nobody can justify.
    await token_service.revoke(session, claims, RevocationReason.PASSWORD_CHANGED)
    await session.commit()

    return _issue(settings, candidate)


@router.get("/me", response_model=CandidateOut)
async def me(candidate: CandidateDep) -> CandidateOut:
    return CandidateOut(
        id=str(candidate.id),
        email=candidate.email,
        display_name=candidate.display_name,
        # Read from the row, never from the token: a role change has to take effect
        # on the next request, not whenever the access token happens to expire.
        role=candidate.role,
    )


class ErasureOut(BaseModel):
    """What was destroyed, so the answer is a receipt rather than a bare 204."""

    account_id: str
    stored_files_removed: int
    message: str


@router.get("/me/export")
async def export_me(candidate: CandidateDep, session: SessionDep) -> dict[str, Any]:
    """Everything the system holds about this account, as one JSON document.

    A subject-access request, not a dump of everything the caller can see. A
    recruiter may read the resumes of people who applied to their postings; those
    belong to the applicants, who can export them from their own accounts.

    The response carries `document_text` and verified profiles — the substance of
    what is stored. Withholding it would make the export decorative, and it is the
    caller's own data. It is never logged, which is the rule everywhere here.
    """
    return await privacy_service.export_account(session, candidate=candidate)


@router.delete("/me", response_model=ErasureOut)
async def delete_me(
    candidate: CandidateDep, session: SessionDep, storage: StorageDep
) -> ErasureOut:
    """Erase this account and everything that cascades from it. Not undoable.

    **Stored files go before rows**, and a file that will not delete abandons the
    whole thing with nothing changed. The other order leaves an object in the bucket
    that no row points at — undiscoverable and therefore unerasable, which is the
    actual failure. This way the worst case is a row whose file is missing, a state
    the pipeline already reports.

    Worth knowing before calling it: deleting a **recruiter** deletes their postings,
    and with them every screening and every other person's application to those
    postings. That is what a posting ceasing to exist means, but it is other
    people's history, so it is said out loud rather than discovered.

    Erasure does not bother revoking the account's tokens, and does not need to: they
    authenticate nothing, because `get_current_candidate` answers **401** for a valid
    signature over an account that is gone. The account's rows in `revoked_tokens` go
    with it on the cascade — keeping them would retain a fragment of somebody who
    asked to be forgotten, for tokens that are already refused.
    """
    account_id = str(candidate.id)
    try:
        removed = await privacy_service.delete_account(
            session, candidate=candidate, storage=storage
        )
    except ErasureIncomplete as exc:
        # 503, not 500: the request was fine, the store was not, and retrying is the
        # right next move. Nothing was deleted.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return ErasureOut(
        account_id=account_id,
        stored_files_removed=removed,
        message="The account and everything belonging to it have been deleted.",
    )
