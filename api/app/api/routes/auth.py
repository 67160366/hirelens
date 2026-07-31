"""Registration and login.

Minimal but real: argon2 hashing, separate access and refresh tokens, and no
distinction in the error message between "no such account" and "wrong password".
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CandidateDep, SessionDep, SettingsDep
from app.models import Candidate
from app.security import create_access_token, create_refresh_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class CandidateOut(BaseModel):
    id: str
    email: str
    display_name: str | None


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, session: SessionDep, settings: SettingsDep
) -> TokenPair:
    candidate = Candidate(
        email=payload.email.lower(),
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
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


@router.get("/me", response_model=CandidateOut)
async def me(candidate: CandidateDep) -> CandidateOut:
    return CandidateOut(
        id=str(candidate.id),
        email=candidate.email,
        display_name=candidate.display_name,
    )
