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

from app.api.deps import CandidateDep, SessionDep, SettingsDep, StorageDep
from app.models import Candidate, Role
from app.security import (
    TOKEN_TYPE_REFRESH,
    AuthError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services import privacy_service
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


class RefreshRequest(BaseModel):
    refresh_token: str


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

    return TokenPair(
        access_token=create_access_token(settings, candidate.id),
        refresh_token=create_refresh_token(settings, candidate.id),
    )


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

    return TokenPair(
        access_token=create_access_token(settings, candidate.id),
        refresh_token=create_refresh_token(settings, candidate.id),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, session: SessionDep, settings: SettingsDep) -> TokenPair:
    """Trade a refresh token for a fresh pair.

    The refresh token is rotated on every use; `decode_token` enforces the type,
    so an access token presented here is rejected just as a refresh token is on
    protected routes.
    """
    try:
        subject = decode_token(settings, payload.refresh_token, expected_type=TOKEN_TYPE_REFRESH)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
        ) from exc

    candidate = await session.get(Candidate, subject)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
        )

    return TokenPair(
        access_token=create_access_token(settings, candidate.id),
        refresh_token=create_refresh_token(settings, candidate.id),
    )


@router.post("/change-password", response_model=TokenPair)
async def change_password(
    payload: ChangePasswordRequest,
    candidate: CandidateDep,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenPair:
    """Change the signed-in account's password, proving the old one first.

    Returns a fresh token pair so a client can swap without a second round trip.

    **Tokens issued before this call keep working until they expire.** Revoking
    them needs a refresh-token denylist, which this project does not have yet —
    the same gap that is why there is no `/auth/logout`. Saying so here is better
    than implying a guarantee the system cannot make.
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
    await session.commit()

    return TokenPair(
        access_token=create_access_token(settings, candidate.id),
        refresh_token=create_refresh_token(settings, candidate.id),
    )


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

    Tokens already issued keep working until they expire — the same gap that is why
    there is no `/auth/logout` — but they authenticate nothing: `get_current_candidate`
    answers **401** for a valid signature over an account that is gone.
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
