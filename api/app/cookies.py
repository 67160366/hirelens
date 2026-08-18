"""The session tokens, delivered as cookies a browser will not show to script.

**This adds a second way to present the same token; it does not replace the first.**
Bearer auth is untouched — every `curl` in `docs/RUNBOOK.md` uses one, as does every
verification run recorded in these documents, and a script has nowhere sensible to
keep a cookie jar. What the cookie buys is that a *browser* need never hold a token
anywhere `document.cookie` or a stray XSS payload can reach it, which is the half of
the auth story the refresh-token denylist did not answer.

Two things about the shape are decisions rather than defaults:

**The refresh cookie is scoped to `/auth`.** The access cookie goes everywhere it is
needed and the refresh cookie goes only where it is spent, so the credential that
can mint fourteen days of access tokens is not attached to every upload, every
screening and every PDF fetch. The cost is that clearing it needs the *same* path —
a mismatch leaves a cookie the browser keeps sending while the server believes it
has been cleared, which is silent in the worst direction, so
`test_cookie_auth.py` proves the cleared cookie no longer authenticates rather than
proving a `Set-Cookie` header was emitted.

**Nothing here revokes anything.** These functions move tokens onto and off the
client; `token_service` decides what is still valid. Clearing a cookie only makes
the browser forget it — the token stays mintable until it is revoked, which is why
`/auth/logout` does both and why a "logout" that only cleared cookies would be the
same empty gesture the route deliberately did not exist to make before `0011`.
"""

from __future__ import annotations

from fastapi import Request, Response

from app.config import Settings

ACCESS_COOKIE = "hirelens_access"
REFRESH_COOKIE = "hirelens_refresh"

ACCESS_COOKIE_PATH = "/"
REFRESH_COOKIE_PATH = "/auth"
"""Covers `/auth/refresh`, which spends it, and `/auth/logout`, which revokes it —
and nothing else."""


def refresh_token_of_this_session(request: Request, body_token: str | None) -> str | None:
    """The refresh token belonging to the session that made this call.

    Used by `/auth/logout`, where the point is to end *the caller's* session and not
    some other one. The rule is that the refresh token comes from the same place the
    access token did, mirroring `deps._present_credential`'s precedence:

      * an explicit body wins, because the caller named it;
      * otherwise a caller who authenticated by **cookie** gets the cookie, which is
        the only way a browser can reach a token it is not allowed to read;
      * a caller who authenticated by **header** gets nothing, even if a cookie is
        sitting in the jar — the two credentials can belong to two different sessions
        of the same account, and revoking one the caller never mentioned would sign
        out a device they were not talking about.

    That last clause is why an `Authorization` header suppresses the cookie here
    rather than merely losing to it.
    """
    if body_token:
        return body_token
    if "authorization" in request.headers:
        return None
    return request.cookies.get(REFRESH_COOKIE)


def set_session(
    response: Response, *, settings: Settings, access_token: str, refresh_token: str
) -> None:
    """Put both tokens where a browser will send them back and script cannot read them.

    `max_age` mirrors each token's own lifetime, so the browser forgets a cookie at
    about the moment the token inside it stops verifying. That is a convenience, not
    a control: a cookie kept longer would carry a token the server refuses anyway.
    """
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.jwt_access_ttl_minutes * 60,
        path=ACCESS_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite.value,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.jwt_refresh_ttl_days * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite.value,
    )


def clear_session(response: Response, *, settings: Settings) -> None:
    """Ask the browser to forget both, on the paths they were set with.

    `path` and `domain` have to match what `set_session` used or the delete lands on
    a different cookie and the original keeps being sent — the failure this module's
    docstring warns about, and the reason a test drives the cleared cookie against a
    protected route instead of inspecting headers.
    """
    response.delete_cookie(
        ACCESS_COOKIE,
        path=ACCESS_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite.value,
    )
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite.value,
    )
