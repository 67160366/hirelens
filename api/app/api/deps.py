"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.llm.base import StructuredExtractor
from app.models import Candidate
from app.security import TOKEN_TYPE_ACCESS, AuthError, decode_token
from app.storage import Storage

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_storage(request: Request) -> Storage:
    """The storage built once at startup and held on app state."""
    return request.app.state.storage  # type: ignore[no-any-return]


def get_extractor(request: Request) -> StructuredExtractor:
    """The extraction backend built once at startup.

    Built at startup rather than per request so an HTTP client and its connection
    pool are reused across calls.
    """
    return request.app.state.extractor  # type: ignore[no-any-return]


StorageDep = Annotated[Storage, Depends(get_storage)]
ExtractorDep = Annotated[StructuredExtractor, Depends(get_extractor)]


async def get_current_candidate(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AsyncIterator[Candidate]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        candidate_id = decode_token(
            settings, credentials.credentials, expected_type=TOKEN_TYPE_ACCESS
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        # A valid signature for a deleted account. 401, not 404: the token itself
        # is no longer usable.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists"
        )

    yield candidate


CandidateDep = Annotated[Candidate, Depends(get_current_candidate)]
