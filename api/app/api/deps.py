"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.cookies import ACCESS_COOKIE
from app.db import get_session
from app.llm.base import StructuredExtractor
from app.models import Candidate, Role
from app.pipeline.retrieval import Retriever
from app.queue import JobQueue
from app.security import TOKEN_TYPE_ACCESS, AuthError, TokenClaims, decode_token
from app.services import token_service
from app.storage import Storage

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _present_credential(
    request: Request, credentials: HTTPAuthorizationCredentials | None
) -> tuple[str, bool] | None:
    """The access token this request offers, and whether it came from a cookie.

    **Bearer wins when both are present**, which keeps every existing caller — the
    whole test suite, every `curl` in the runbook, every recorded verification run —
    behaving exactly as it did, and makes a stale cookie in some browser unable to
    shadow a header a script deliberately set.

    Returning *where* it came from is not bookkeeping: it decides whether the CSRF
    check below applies. A cookie is attached by the browser whatever page asked; an
    `Authorization` header can only be set by script that already has the token, and
    a cross-site page cannot set one without a preflight this API refuses.
    """
    if credentials is not None:
        return credentials.credentials, False
    from_cookie = request.cookies.get(ACCESS_COOKIE)
    if from_cookie:
        return from_cookie, True
    return None


def _refuse_cross_site_write(request: Request, settings: Settings) -> None:
    """Refuse a cookie-authenticated write that came from somewhere else's page.

    `SameSite=lax` already stops the browser attaching these cookies to a cross-site
    write, so on the default configuration this guard never fires. It exists for the
    configuration where that protection is deliberately switched off:
    `COOKIE_SAMESITE=none`, which a genuinely cross-domain deploy needs and which
    removes the only thing standing between a cookie and a forged write. Without
    this, turning that knob would open CSRF and nothing would say so — a security
    property that evaporates on a config change is not one.

    **A missing `Origin` is allowed, and that is the deliberate part.** Browsers
    attach `Origin` to every unsafe method, so its absence means a non-browser
    client — `curl` with a cookie jar, a script, the runbook — and those are not what
    CSRF is. Refusing them would break real callers to defend against an attacker who
    cannot reach this code path anyway.

    Only unsafe methods are checked. Nothing here mutates on `GET`, so a cross-site
    navigation to one would leak nothing an attacker could read.
    """
    if request.method in _SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None or origin in settings.cors_origins:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Cookie authentication is not accepted for a request from another origin.",
    )


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


def get_retriever(request: Request) -> Retriever:
    """The retrieval backend built once at startup, so an unimplemented one is
    refused there rather than on the first request that needs it."""
    return request.app.state.retriever  # type: ignore[no-any-return]


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
RetrieverDep = Annotated[Retriever, Depends(get_retriever)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


async def get_current_candidate(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AsyncIterator[Candidate]:
    presented = _present_credential(request, credentials)
    if presented is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, from_cookie = presented
    if from_cookie:
        _refuse_cross_site_write(request, settings)

    try:
        claims = decode_token(settings, token, expected_type=TOKEN_TYPE_ACCESS)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # The account is loaded before the token is accepted, not after: `assert_live`
    # needs the row to compare the token's epoch against, and requiring it as an
    # argument is what stops the epoch check from being a third thing to remember.
    candidate = await session.get(Candidate, claims.subject)
    if candidate is None:
        # A valid signature for a deleted account. 401, not 404: the token itself
        # is no longer usable.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists"
        )

    try:
        # Verify, then check it still counts. `decode_token` answers what the token
        # says; only the database knows whether it has been taken back or belongs to
        # a generation a password change ended. Every failure raises `AuthError`, so
        # a revoked, superseded and forged token look identical to whoever presented
        # one — which is the right amount to disclose.
        await token_service.assert_live(session, claims, candidate)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    yield candidate


CandidateDep = Annotated[Candidate, Depends(get_current_candidate)]


async def get_current_claims(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenClaims:
    """The verified claims of the access token that authenticated this request.

    Its own dependency rather than a value smuggled onto `request.state` by
    `get_current_candidate`: FastAPI does not promise an order between two
    dependencies of the same route, and a value that exists only because something
    else happened to run first is the kind of coupling that breaks silently.

    Decoding twice costs one HMAC verification. Only `/auth/logout` needs this — the
    one route whose job is to act on the token itself rather than on the account
    behind it.

    The `session.get` below is not a second query in practice: both routes using
    this also depend on `CandidateDep`, so the row is already in the identity map.
    It is spelled out anyway rather than assumed, for the reason above — there is no
    promised order between two dependencies of one route.
    """
    presented = _present_credential(request, credentials)
    if presented is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, from_cookie = presented
    if from_cookie:
        _refuse_cross_site_write(request, settings)

    try:
        claims = decode_token(settings, token, expected_type=TOKEN_TYPE_ACCESS)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    candidate = await session.get(Candidate, claims.subject)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists"
        )

    try:
        await token_service.assert_live(session, claims, candidate)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return claims


ClaimsDep = Annotated[TokenClaims, Depends(get_current_claims)]


def require_role(*allowed: Role) -> Callable[[Candidate], Candidate]:
    """A dependency that refuses an account whose role may not reach this route.

    **403 here, and 404 everywhere ownership is checked.** The two refusals answer
    different questions and must not be merged. A role check is about the *route*,
    which is listed in `/docs` and which the caller has plainly found — saying "not
    for your role" leaks nothing. An ownership check is about a specific *id*, and
    a 403 there would confirm the id exists, which is the account-enumeration
    problem `_owned_job` and `_owned_resume` already answer 404 to avoid.

    `ADMIN` passes everything without being listed at each call site: a role system
    where every route has to remember to name the superuser grows a hole the first
    time someone forgets.
    """
    permitted = frozenset(allowed) | {Role.ADMIN}

    def guard(candidate: CandidateDep) -> Candidate:
        if candidate.role not in permitted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action needs the "
                    f"{' or '.join(sorted(r.value for r in allowed))} role; "
                    f"this account is a {candidate.role.value}."
                ),
            )
        return candidate

    return guard


RecruiterDep = Annotated[Candidate, Depends(require_role(Role.RECRUITER))]
"""Posting a job and screening against it. Admin passes too, via `require_role`."""
