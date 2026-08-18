"""Taking a token back.

The gap these cover was concrete rather than theoretical. `POST /auth/refresh` has
always issued a fresh pair and left the *presented* refresh token valid for the rest
of its fourteen days, so a stolen one kept working after the real user had rotated
it. And there was no `/auth/logout` at all, deliberately, because a logout route with
nothing behind it reports success while the token goes on working.

What is worth pinning here is mostly what fails **silently**. A revocation that is
written but never checked, a logout that revokes the access token and forgets the
refresh token behind it, a sweep that deletes rows it should have kept — none of
those throw, and every one of them leaves an operator believing a session is dead
when it is not.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Candidate, RevocationReason, RevokedToken
from app.security import TOKEN_TYPE_ACCESS, TOKEN_TYPE_REFRESH, AuthError, decode_token
from app.services import token_service

pytestmark = pytest.mark.anyio


async def _fresh_pair(client: AsyncClient, email: str = "session@example.com") -> dict[str, str]:
    """Register an account and return its token pair, without touching the client's
    headers — several tests here need a pair that is *not* the one authenticating
    the request."""
    response = await client.post(
        "/auth/register", json={"email": email, "password": "correct horse battery"}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _login(client: AsyncClient, email: str = "candidate@example.com") -> dict[str, str]:
    """A second pair for an account that already exists — a sign-in on another device."""
    response = await client.post(
        "/auth/login", json={"email": email, "password": "correct horse battery"}
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


class TestLogout:
    async def test_the_access_token_stops_working(self, authed_client: AsyncClient):
        assert (await authed_client.get("/auth/me")).status_code == 200

        assert (await authed_client.post("/auth/logout", json={})).status_code == 204

        # The same header that worked one line ago.
        assert (await authed_client.get("/auth/me")).status_code == 401

    async def test_the_refresh_token_behind_it_stops_working_too(
        self, authed_client: AsyncClient, client: AsyncClient
    ):
        """The half that actually ends the session.

        Revoking only the access token leaves the caller able to mint a new one for
        the next fourteen days, which is a logout in name only.
        """
        pair = await _login(client)
        client.headers["Authorization"] = f"Bearer {pair['access_token']}"

        logout = await client.post("/auth/logout", json={"refresh_token": pair["refresh_token"]})
        assert logout.status_code == 204

        refreshed = await client.post(
            "/auth/refresh", json={"refresh_token": pair["refresh_token"]}
        )
        assert refreshed.status_code == 401

    async def test_omitting_the_refresh_token_leaves_the_session_renewable(
        self, client: AsyncClient
    ):
        """Documented behaviour, not an accident — so it is pinned rather than assumed.

        The server never sees the refresh token unless it is sent, so it cannot
        revoke what it was not given. The route says so; this is the proof it
        behaves that way.
        """
        pair = await _fresh_pair(client)
        client.headers["Authorization"] = f"Bearer {pair['access_token']}"

        assert (await client.post("/auth/logout", json={})).status_code == 204

        renewed = await client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert renewed.status_code == 200

    async def test_it_will_not_revoke_somebody_elses_refresh_token(
        self, client: AsyncClient, authed_client: AsyncClient
    ):
        """Otherwise this route is a way to sign out any account whose refresh token
        you have got hold of, which is a denial-of-service handed out at 204."""
        victim = await _login(client)

        # A different account, signing itself out and attaching the victim's token.
        attacker = await client.post(
            "/auth/register",
            json={"email": "attacker@example.com", "password": "correct horse battery"},
        )
        client.headers["Authorization"] = f"Bearer {attacker.json()['access_token']}"

        logout = await client.post("/auth/logout", json={"refresh_token": victim["refresh_token"]})
        # 204 either way, so it is not an oracle for whose token is whose.
        assert logout.status_code == 204

        still_works = await client.post(
            "/auth/refresh", json={"refresh_token": victim["refresh_token"]}
        )
        assert still_works.status_code == 200

    async def test_a_malformed_refresh_token_does_not_fail_the_logout(
        self, authed_client: AsyncClient
    ):
        """The access token is revoked regardless. Failing here would leave a caller
        who mangled one field still signed in."""
        response = await authed_client.post("/auth/logout", json={"refresh_token": "not-a-jwt"})
        assert response.status_code == 204
        assert (await authed_client.get("/auth/me")).status_code == 401

    async def test_it_requires_authentication(self, client: AsyncClient):
        assert (await client.post("/auth/logout", json={})).status_code == 401

    async def test_logging_out_twice_is_not_an_error(
        self, authed_client: AsyncClient, client: AsyncClient
    ):
        """Idempotent on the `jti`. Two tabs both signing out must not 500."""
        pair = await _login(client)
        client.headers["Authorization"] = f"Bearer {pair['access_token']}"
        body = {"refresh_token": pair["refresh_token"]}

        assert (await client.post("/auth/logout", json=body)).status_code == 204
        # The access token is dead now, so a second call cannot authenticate — which
        # is itself the point. Revoking the same refresh token again goes through the
        # service directly below.
        assert (await client.post("/auth/logout", json=body)).status_code == 401


class TestRefreshRotation:
    async def test_a_spent_refresh_token_cannot_be_used_again(self, client: AsyncClient):
        """The concrete hole this slice closes.

        Before revocation, `refresh` issued a new pair and left the presented token
        valid for the rest of its fourteen days — so a copy taken from storage or a
        proxy log kept working *after* the legitimate user had rotated it, and
        nothing on either side could tell.
        """
        pair = await _fresh_pair(client)

        first = await client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert first.status_code == 200

        replay = await client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert replay.status_code == 401

    async def test_the_pair_it_returns_works(self, client: AsyncClient):
        """Rotation has to hand back something usable, or it is just revocation."""
        pair = await _fresh_pair(client)
        renewed = (
            await client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        ).json()

        client.headers["Authorization"] = f"Bearer {renewed['access_token']}"
        assert (await client.get("/auth/me")).status_code == 200

        again = await client.post("/auth/refresh", json={"refresh_token": renewed["refresh_token"]})
        assert again.status_code == 200

    async def test_an_access_token_is_still_refused_at_the_refresh_route(self, client: AsyncClient):
        """Unchanged behaviour, re-pinned because `refresh` now writes to the
        database: a type confusion here would revoke the caller's access token as
        though it were a refresh token."""
        pair = await _fresh_pair(client)
        response = await client.post("/auth/refresh", json={"refresh_token": pair["access_token"]})
        assert response.status_code == 401


class TestTheRowsBehindIt:
    async def test_a_revocation_records_which_token_whose_and_why(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        token = authed_client.headers["Authorization"].removeprefix("Bearer ")
        await authed_client.post("/auth/logout", json={})

        async with sessionmaker_for_tests() as session:
            rows = (await session.execute(select(RevokedToken))).scalars().all()

        assert len(rows) == 1
        row = rows[0]
        # The row names the exact token, not merely the account.
        assert (
            row.jti
            == decode_token(_settings_of(authed_client), token, expected_type=TOKEN_TYPE_ACCESS).jti
        )
        assert row.token_type == TOKEN_TYPE_ACCESS
        assert row.reason is RevocationReason.LOGOUT

    async def test_rotation_and_logout_are_recorded_as_different_events(
        self,
        client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """Three reasons exist because they are three different things that
        happened, and an operator asking "why am I signed out" deserves the real
        answer rather than one word covering all of them."""
        pair = await _fresh_pair(client)
        await client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})

        client.headers["Authorization"] = f"Bearer {pair['access_token']}"
        await client.post("/auth/logout", json={})

        async with sessionmaker_for_tests() as session:
            reasons = set((await session.execute(select(RevokedToken.reason))).scalars().all())

        assert reasons == {RevocationReason.REFRESH_ROTATED, RevocationReason.LOGOUT}

    async def test_a_password_change_leaves_a_record_of_why(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """This row exists for the operator, not for the guard, and the distinction
        is the whole reason the case is here.

        `Candidate.token_epoch` is what actually ends the session — mutation-testing
        proved it: deleting the `revoke` call below leaves all 656 cases passing,
        because the epoch refuses the token first and nothing else was looking. That
        makes this line untested rather than dead, which are different things.
        Without it a password change is the one revocation that leaves **no trace at
        all**, since bumping an integer writes no history, and the operator query in
        `docs/RUNBOOK.md` would quietly stop reporting the reason people are most
        likely to ask about.

        So it stays, and this pins it. A line kept for a reason no test states is a
        line the next person deletes.
        """
        await authed_client.post(
            "/auth/change-password",
            json={"current_password": "correct horse battery", "new_password": "a-brand-new-one"},
        )

        async with sessionmaker_for_tests() as session:
            rows = (await session.execute(select(RevokedToken))).scalars().all()

        assert [row.reason for row in rows] == [RevocationReason.PASSWORD_CHANGED]
        assert rows[0].token_type == TOKEN_TYPE_ACCESS

    async def test_erasing_the_account_takes_its_revocations_with_it(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """PDPA: delete means delete. Keeping revocation rows for an erased account
        would retain a fragment of somebody who asked to be forgotten, for tokens
        that are refused anyway because the account is gone.

        This is also the cascade `PRAGMA foreign_keys=ON` exists to make real — the
        assertion would pass on SQLite with foreign keys off while failing on
        Postgres.
        """
        pair = await _login(authed_client)
        authed_client.headers["Authorization"] = f"Bearer {pair['access_token']}"
        await authed_client.post("/auth/refresh", json={"refresh_token": pair["refresh_token"]})

        async with sessionmaker_for_tests() as session:
            assert (await session.execute(select(RevokedToken))).scalars().all()

        erased = await authed_client.delete("/auth/me")
        assert erased.status_code == 200

        async with sessionmaker_for_tests() as session:
            assert (await session.execute(select(RevokedToken))).scalars().all() == []


class TestTheService:
    """The parts the HTTP layer cannot reach: the sweep, and racing revocations."""

    async def test_revoking_the_same_token_twice_keeps_the_first_reason(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """ "Why was this revoked" should answer with what actually happened first,
        not with whatever wrote last."""
        token = authed_client.headers["Authorization"].removeprefix("Bearer ")
        claims = decode_token(_settings_of(authed_client), token, expected_type=TOKEN_TYPE_ACCESS)

        async with sessionmaker_for_tests() as session:
            await token_service.revoke(session, claims, RevocationReason.LOGOUT)
            await token_service.revoke(session, claims, RevocationReason.PASSWORD_CHANGED)
            await session.commit()

            rows = (await session.execute(select(RevokedToken))).scalars().all()

        assert len(rows) == 1
        assert rows[0].reason is RevocationReason.LOGOUT

    async def test_the_sweep_keeps_live_revocations_and_drops_expired_ones(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """The failure that would be silent in the wrong direction.

        Deleting a row too early un-revokes a token somebody signed out — the exact
        thing the table exists to prevent — and nothing would report it.
        """
        token = authed_client.headers["Authorization"].removeprefix("Bearer ")
        claims = decode_token(_settings_of(authed_client), token, expected_type=TOKEN_TYPE_ACCESS)

        async with sessionmaker_for_tests() as session:
            await token_service.revoke(session, claims, RevocationReason.LOGOUT)
            session.add(
                RevokedToken(
                    jti="a" * 32,
                    candidate_id=claims.subject,
                    token_type=TOKEN_TYPE_REFRESH,
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                    reason=RevocationReason.LOGOUT,
                )
            )
            await session.commit()

            removed = await token_service.purge_expired(session)
            await session.commit()

            surviving = (await session.execute(select(RevokedToken.jti))).scalars().all()

        assert removed == 1
        # The live one is still there, which is the half that matters.
        assert surviving == [claims.jti]

    async def test_assert_live_raises_the_same_error_an_invalid_token_does(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """A revoked token and a forged one must be indistinguishable to whoever
        presented them, and `AuthError` is what every call site already turns into a
        401 — so revocation needs no second failure mode threading through the
        routes."""
        token = authed_client.headers["Authorization"].removeprefix("Bearer ")
        claims = decode_token(_settings_of(authed_client), token, expected_type=TOKEN_TYPE_ACCESS)

        async with sessionmaker_for_tests() as session:
            candidate = await session.get(Candidate, claims.subject)
            assert candidate is not None
            await token_service.assert_live(session, claims, candidate)  # not revoked: silent

            await token_service.revoke(session, claims, RevocationReason.LOGOUT)
            await session.commit()

            with pytest.raises(AuthError):
                await token_service.assert_live(session, claims, candidate)

    async def test_a_stale_epoch_raises_that_same_error_too(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """The second half of `assert_live`, and it has to fail the same way.

        A token superseded by a password change is refused for a different reason
        than one that was signed out, but whoever presented it learns neither — both
        are `AuthError`, and every route already turns that into one 401. A distinct
        exception here would eventually become a distinct status code somewhere, and
        that would tell an attacker which of the two happened.
        """
        token = authed_client.headers["Authorization"].removeprefix("Bearer ")
        claims = decode_token(_settings_of(authed_client), token, expected_type=TOKEN_TYPE_ACCESS)

        async with sessionmaker_for_tests() as session:
            candidate = await session.get(Candidate, claims.subject)
            assert candidate is not None
            await token_service.assert_live(session, claims, candidate)  # in step: silent

            # What `POST /auth/change-password` does, without the HTTP layer.
            candidate.token_epoch += 1
            await session.commit()

            with pytest.raises(AuthError):
                await token_service.assert_live(session, claims, candidate)

    async def test_a_token_from_a_later_epoch_is_refused_as_well(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """Not `<`, but `!=`.

        A token claiming an epoch the account has never reached is forged or
        replayed from somewhere, and accepting it because it looks *newer* would
        make the check a lower bound rather than an identity — which an attacker
        who can mint tokens would only have to overshoot.
        """
        token = authed_client.headers["Authorization"].removeprefix("Bearer ")
        claims = decode_token(_settings_of(authed_client), token, expected_type=TOKEN_TYPE_ACCESS)
        from_the_future = replace(claims, epoch=claims.epoch + 5)

        async with sessionmaker_for_tests() as session:
            candidate = await session.get(Candidate, claims.subject)
            assert candidate is not None

            with pytest.raises(AuthError):
                await token_service.assert_live(session, from_the_future, candidate)


class TestTokenClaims:
    async def test_a_token_without_a_jti_is_refused(self, authed_client: AsyncClient):
        """Every token this application issues carries one, so a token without it is
        forged or from a scheme that predates M1 — and either way it is a token that
        can never be revoked. Refusing beats trusting it forever."""
        import jwt

        settings = _settings_of(authed_client)
        forged = jwt.encode(
            {
                "sub": "e3b0c442-98fc-1c14-9afb-f4c8996fb924",
                "type": TOKEN_TYPE_ACCESS,
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            settings.jwt_secret,
            algorithm="HS256",
        )

        with pytest.raises(AuthError):
            decode_token(settings, forged, expected_type=TOKEN_TYPE_ACCESS)


def _settings_of(client: AsyncClient):
    """The settings the app under test was built with.

    Read off the ASGI app rather than `get_settings()`, because the suite overrides
    them per test — a JWT signed with the fixture's secret will not verify against
    the process-wide default.
    """
    return client._transport.app.state.settings  # type: ignore[union-attr]
