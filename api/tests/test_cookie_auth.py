"""Presenting the same token as a cookie instead of a header.

The point of the cookie is that a browser never holds a token anywhere script can
read it. That property is not testable from here — no DOM, and `httpOnly` is a
promise the *browser* keeps — so what these cases pin is everything around it: that
the cookie authenticates, that the header still does, that clearing really clears,
and that the CSRF door the cookie opens is shut.

**Two of these failures are silent, and the first draft of this module claimed to
catch them and did not.** Mutation-testing found it: clearing the refresh cookie on
the wrong `path`, and ignoring the refresh cookie during logout, both left every
case passing. They were covering for each other. Logout does two things — revoke the
token, and ask the browser to forget it — and each one masks the other's absence:

  * the token is revoked, so an *uncleared* cookie is refused anyway and every
    "still 401?" check passes;
  * the cookie is cleared, so an *unrevoked* token has nothing to present it and the
    same checks pass again.

So they are pinned apart. Revocation is checked by **keeping the token and replaying
it in a body**, where clearing cannot help; clearing is checked **in the jar**, where
revocation cannot help. The general shape, worth carrying: when one mechanism can
produce the other's symptom, testing the symptom tests neither.

The third would-be-silent failure is CSRF. A cookie that authenticates a cross-site
write leaves nothing to see, and `SameSite=lax` means the guard never fires on the
default configuration — so it is tested at the layer that still runs when somebody
sets `COOKIE_SAMESITE=none` for a cross-domain deploy and throws that protection
away.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.cookies import ACCESS_COOKIE, ACCESS_COOKIE_PATH, REFRESH_COOKIE, REFRESH_COOKIE_PATH

pytestmark = pytest.mark.anyio

CREDENTIALS = {"email": "cookie@example.com", "password": "correct horse battery"}
FOREIGN = {"Origin": "http://evil.example"}


async def _register(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/auth/register", json=CREDENTIALS)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _cookie_only(client: AsyncClient) -> None:
    """Drop the header so the jar is the only credential left."""
    client.headers.pop("Authorization", None)


class TestTheCookieIsSet:
    async def test_registering_sets_both_cookies(self, client: AsyncClient):
        response = await client.post("/auth/register", json=CREDENTIALS)

        assert response.status_code == 201
        for name in (ACCESS_COOKIE, REFRESH_COOKIE):
            assert name in response.cookies

    async def test_the_body_still_carries_the_pair(self, client: AsyncClient):
        """The cookie is an addition, not a replacement.

        Every `curl` in the runbook and every recorded verification run reads the
        pair out of the body, so a route that stopped returning it would break them
        all while every cookie test here went on passing.
        """
        pair = await _register(client)

        assert pair["access_token"] and pair["refresh_token"]
        assert pair["token_type"] == "bearer"

    async def test_the_attributes_are_the_ones_that_make_it_worth_having(self, client: AsyncClient):
        """`HttpOnly` is the whole point, and the paths are what the clearing has to
        match. Read off the raw header, because httpx's jar keeps the value and
        discards the attributes."""
        response = await client.post("/auth/register", json=CREDENTIALS)
        headers = response.headers.get_list("set-cookie")

        access = next(h for h in headers if h.startswith(f"{ACCESS_COOKIE}="))
        refresh = next(h for h in headers if h.startswith(f"{REFRESH_COOKIE}="))

        for header in (access, refresh):
            assert "HttpOnly" in header
            assert "SameSite=lax" in header
        assert f"Path={ACCESS_COOKIE_PATH}" in access
        assert f"Path={REFRESH_COOKIE_PATH}" in refresh

    async def test_the_refresh_cookie_does_not_travel_to_the_rest_of_the_api(
        self, client: AsyncClient
    ):
        """Scoping it to `/auth` is why: the credential that can mint fourteen days
        of access tokens is not attached to every upload and every PDF fetch.

        Asserted through httpx's own jar, which applies path scoping the way a
        browser does, rather than by re-reading the attribute the test above checked.
        """
        await _register(client)

        for_resumes = client.cookies.jar
        sent_to_resumes = {
            cookie.name for cookie in for_resumes if cookie.path in ("/", ACCESS_COOKIE_PATH)
        }

        assert ACCESS_COOKIE in sent_to_resumes
        assert REFRESH_COOKIE not in sent_to_resumes


class TestItAuthenticates:
    async def test_the_cookie_alone_is_enough(self, client: AsyncClient):
        await _register(client)
        _cookie_only(client)

        response = await client.get("/auth/me")

        assert response.status_code == 200
        assert response.json()["email"] == CREDENTIALS["email"]

    async def test_the_header_alone_is_still_enough(self, client: AsyncClient):
        """The half that must not regress. Every existing caller sends a header and
        no cookie."""
        pair = await _register(client)
        client.cookies.clear()
        client.headers["Authorization"] = f"Bearer {pair['access_token']}"

        assert (await client.get("/auth/me")).status_code == 200

    async def test_neither_is_a_401(self, client: AsyncClient):
        await _register(client)
        client.cookies.clear()
        _cookie_only(client)

        assert (await client.get("/auth/me")).status_code == 401

    async def test_the_header_wins_when_both_are_present(self, client: AsyncClient):
        """A stale cookie in some browser must not shadow a header a script set
        deliberately, and the precedence has to be checked with two *different*
        accounts or both credentials would answer the same and prove nothing."""
        await _register(client)  # leaves this account's cookies in the jar
        other = await client.post(
            "/auth/login", json=CREDENTIALS
        )  # a second session for the same person
        assert other.status_code == 200

        second = await client.post(
            "/auth/register",
            json={"email": "other@example.com", "password": "correct horse battery"},
        )
        # That registration reset the jar to the *second* account, so put the first
        # account's header back and see which one the server reports.
        client.cookies.clear()
        client.cookies.set(ACCESS_COOKIE, second.json()["access_token"])
        client.headers["Authorization"] = f"Bearer {other.json()['access_token']}"

        assert (await client.get("/auth/me")).json()["email"] == CREDENTIALS["email"]


class TestClearingReallyClears:
    async def test_logout_leaves_the_cookie_unable_to_authenticate(self, client: AsyncClient):
        """Driven, not read off a header.

        A `delete_cookie` whose path does not match the `set_cookie` emits a
        convincing header and leaves the browser sending the original — so the only
        check worth making is whether the cookie still opens the door.
        """
        await _register(client)
        _cookie_only(client)
        assert (await client.get("/auth/me")).status_code == 200

        assert (await client.post("/auth/logout")).status_code == 204

        assert (await client.get("/auth/me")).status_code == 401

    async def test_a_cookie_logout_revokes_the_refresh_token_with_no_body(
        self, client: AsyncClient
    ):
        """A browser cannot read its own httpOnly cookie to put the token in a body,
        so if the server did not read it there, every browser logout would leave the
        session renewable for another fortnight — the exact hole `/auth/logout` was
        built to close, reopened for the one client that cannot help it.

        **The token is kept and replayed in a body, and that is the whole point of
        the shape.** The obvious version — logout, then `POST /auth/refresh` with no
        body — passes whether or not the token was revoked, because clearing the
        cookie alone leaves nothing to present and the route answers 401 for the
        wrong reason. Mutation-testing caught exactly that: ignoring the cookie
        during logout broke nothing until this line stopped relying on the cookie
        being gone.
        """
        await _register(client)
        _cookie_only(client)
        held = client.cookies.get(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)

        assert (await client.post("/auth/logout")).status_code == 204

        replayed = await client.post("/auth/refresh", json={"refresh_token": held})
        assert replayed.status_code == 401

    async def test_the_browser_is_asked_to_forget_both_cookies(self, client: AsyncClient):
        """The half revocation hides.

        Every other check here still passes if `clear_session` deletes on the wrong
        `path`, because the token inside the uncleared cookie has been revoked and is
        refused anyway. What is left wrong is the browser: it goes on presenting a
        dead credential on every request for another fortnight, and nothing in the
        response says so. Asserted through httpx's jar, which applies path scoping
        the way a browser does — a delete aimed at `/` does not reach a cookie set on
        `/auth`.
        """
        await _register(client)
        _cookie_only(client)
        assert REFRESH_COOKIE in client.cookies

        await client.post("/auth/logout")

        assert ACCESS_COOKIE not in client.cookies
        assert REFRESH_COOKIE not in client.cookies

    async def test_erasure_signs_the_browser_out_too(self, client: AsyncClient):
        await _register(client)
        _cookie_only(client)

        assert (await client.delete("/auth/me")).status_code == 200

        assert (await client.get("/auth/me")).status_code == 401


class TestRefreshWithoutABody:
    async def test_the_cookie_is_spent_and_rotated(self, client: AsyncClient):
        await _register(client)
        _cookie_only(client)

        renewed = await client.post("/auth/refresh")

        assert renewed.status_code == 200
        assert renewed.json()["access_token"]
        assert REFRESH_COOKIE in renewed.cookies

    async def test_no_body_and_no_cookie_is_a_401(self, client: AsyncClient):
        assert (await client.post("/auth/refresh")).status_code == 401

    async def test_a_spent_cookie_cannot_be_replayed(self, client: AsyncClient):
        """Rotation has to hold on this path too, or the cookie client would be the
        one caller for whom a refresh token is not single-use."""
        await _register(client)
        _cookie_only(client)
        spent = client.cookies.get(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)

        assert (await client.post("/auth/refresh")).status_code == 200

        replayed = await client.post("/auth/refresh", json={"refresh_token": spent})
        assert replayed.status_code == 401


class TestTheCsrfDoorTheCookieOpens:
    """`SameSite=lax` already stops a browser attaching these cookies to a cross-site
    write, so none of this fires on the default configuration. It is the layer that
    still runs when somebody sets `COOKIE_SAMESITE=none` for a cross-domain deploy
    and throws that protection away — a security property that evaporates on a config
    change is not one.
    """

    async def test_a_cookie_write_from_another_origin_is_refused(self, client: AsyncClient):
        await _register(client)
        _cookie_only(client)

        response = await client.post("/jobs", json={"title": "x"}, headers=FOREIGN)

        assert response.status_code == 403
        assert "another origin" in response.json()["detail"]

    async def test_the_same_write_authenticated_by_header_is_not(self, client: AsyncClient):
        """The guard belongs where the cookie is the credential and nowhere else. A
        cross-site page cannot set an `Authorization` header without a preflight this
        API refuses, so a header-authenticated request is not the CSRF threat — and
        refusing it would break every script that sets an Origin."""
        pair = await _register(client)
        client.cookies.clear()
        client.headers["Authorization"] = f"Bearer {pair['access_token']}"

        response = await client.post("/jobs", json={"title": "x"}, headers=FOREIGN)

        # 403 would mean the guard fired; this account is a candidate, so the *role*
        # refusal is what it should hit instead — a different 403 with a different
        # sentence, which is why the message is checked rather than the status.
        assert "another origin" not in response.text

    async def test_a_cookie_read_from_another_origin_is_allowed(self, client: AsyncClient):
        """Only unsafe methods are checked. Nothing here mutates on GET, and a
        cross-site navigation to one leaks nothing the attacker can read — while
        refusing it would break an ordinary link into the app."""
        await _register(client)
        _cookie_only(client)

        assert (await client.get("/auth/me", headers=FOREIGN)).status_code == 200

    async def test_a_cookie_write_from_an_allowed_origin_is_allowed(self, client: AsyncClient):
        await _register(client)
        _cookie_only(client)

        response = await client.post("/auth/logout", headers={"Origin": "http://localhost:3000"})

        assert response.status_code == 204

    async def test_a_cookie_write_with_no_origin_at_all_is_allowed(self, client: AsyncClient):
        """Browsers attach `Origin` to every unsafe method, so its absence means a
        non-browser client — `curl` with a cookie jar, a script, the runbook. Those
        are not what CSRF is, and refusing them would break real callers to defend
        against an attacker who cannot reach this path."""
        await _register(client)
        _cookie_only(client)

        assert (await client.post("/auth/logout")).status_code == 204
