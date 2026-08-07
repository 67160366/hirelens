"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import get_session
from app.llm.base import StructuredExtractor
from app.models import Candidate
from app.queue import JobQueue
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


def get_queue(request: Request) -> JobQueue:
    """The queue built once at startup — a Redis pool, or the inline runner."""
    return request.app.state.queue  # type: ignore[no-any-return]


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """The sessionmaker held on app state, for code that outlives its request.

    A streaming endpoint cannot use `SessionDep`: FastAPI closes dependencies with
    `yield` *before* the response body starts flowing, so by the time a stream
    emits its first frame that session is gone. Handing out the factory instead
    lets the generator open a short session per read — which also means an open
    stream does not hold a pooled connection while nothing is happening.
    """
    return request.app.state.sessionmaker  # type: ignore[no-any-return]


StorageDep = Annotated[Storage, Depends(get_storage)]
ExtractorDep = Annotated[StructuredExtractor, Depends(get_extractor)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


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
