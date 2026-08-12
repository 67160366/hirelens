"""Roles: which routes an account may reach, and which rows it may touch.

Two refusals live here and the whole module exists to keep them apart.

*   **403** — the wrong *role* for a route. The route is in `/docs`, the caller has
    plainly found it, and naming the role it needs leaks nothing.
*   **404** — not *your* resource. Unchanged from M3, and a 403 here would confirm
    the id exists, which is exactly the account-enumeration answer `_owned_job` and
    `_owned_resume` were written to avoid.

Merging them is the easiest way to undo M3's ownership story without any test
noticing, which is why several cases below assert the *code* rather than just that
the request was refused.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Candidate, Role
from tests.conftest import register_as, resume_upload

JOB = {"title": "Backend Engineer", "requirements": [{"kind": "skill", "label": "Python"}]}


async def _set_role(sessionmaker: async_sessionmaker[AsyncSession], email: str, role: Role) -> None:
    """Change a role out of band, the way an operator would.

    There is no endpoint for this on purpose — `admin` in particular is not
    self-selectable, so a SQL statement is how it is granted.
    """
    async with sessionmaker() as session:
        account = (
            await session.execute(select(Candidate).where(Candidate.email == email))
        ).scalar_one()
        account.role = role
        await session.commit()


class TestTheDefault:
    async def test_a_new_account_is_a_candidate(self, authed_client: AsyncClient):
        response = await authed_client.get("/auth/me")
        assert response.status_code == 200
        assert response.json()["role"] == "candidate"

    async def test_an_account_may_register_as_a_recruiter(self, recruiter_client: AsyncClient):
        assert (await recruiter_client.get("/auth/me")).json()["role"] == "recruiter"

    async def test_an_account_may_not_register_as_an_admin(self, client: AsyncClient):
        """Self-granted admin is not a role system.

        `SelfServiceRole` omits it, so the request never reaches a handler — the
        refusal is schema validation, which is the cheapest place for it to live.
        """
        response = await client.post(
            "/auth/register",
            json={"email": "sneaky@example.com", "password": "a-good-password", "role": "admin"},
        )
        assert response.status_code == 422

    async def test_an_unknown_role_is_refused(self, client: AsyncClient):
        response = await client.post(
            "/auth/register",
            json={"email": "odd@example.com", "password": "a-good-password", "role": "wizard"},
        )
        assert response.status_code == 422


class TestWhatARoleGates:
    async def test_a_candidate_cannot_author_a_job(self, authed_client: AsyncClient):
        response = await authed_client.post("/jobs", json=JOB)
        assert response.status_code == 403
        # The message names the role, because the caller can act on that.
        assert "recruiter" in response.json()["detail"]

    async def test_a_recruiter_can(self, recruiter_client: AsyncClient):
        assert (await recruiter_client.post("/jobs", json=JOB)).status_code == 201

    async def test_an_admin_passes_without_being_named_at_the_call_site(
        self,
        client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """`require_role` adds ADMIN itself.

        A role system where every route has to remember to list the superuser grows
        a hole the first time someone forgets, so the dependency does it once.
        """
        await register_as(client, email="boss@example.com")
        await _set_role(sessionmaker_for_tests, "boss@example.com", Role.ADMIN)

        assert (await client.get("/auth/me")).json()["role"] == "admin"
        assert (await client.post("/jobs", json=JOB)).status_code == 201

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("post", "/jobs"),
            ("patch", "/jobs/{job}"),
            ("delete", "/jobs/{job}"),
            ("post", "/jobs/{job}/requirements"),
            ("post", "/jobs/{job}/screenings"),
        ],
    )
    async def test_every_authoring_route_is_closed_to_a_candidate(
        self,
        client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        method: str,
        path: str,
    ):
        """One job, then the same account demoted — so every 403 here is about the
        *role* and cannot be an ownership 404 wearing a different number."""
        await register_as(client, email="demoted@example.com", role="recruiter")
        job_id = (await client.post("/jobs", json=JOB)).json()["id"]
        await _set_role(sessionmaker_for_tests, "demoted@example.com", Role.CANDIDATE)

        response = await client.request(method, path.format(job=job_id), json={"title": "x"})
        assert response.status_code == 403, response.text

    async def test_a_candidate_may_still_read_a_job(
        self, client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        """Reads are not gated by role, and must not be.

        Slice 3 has candidates applying to postings, which means seeing one first.
        Ownership still applies — this account owns the job, having authored it
        before being demoted.
        """
        await register_as(client, email="reader@example.com", role="recruiter")
        job_id = (await client.post("/jobs", json=JOB)).json()["id"]
        await _set_role(sessionmaker_for_tests, "reader@example.com", Role.CANDIDATE)

        assert (await client.get(f"/jobs/{job_id}")).status_code == 200
        assert (await client.get("/jobs")).status_code == 200

    async def test_a_candidate_keeps_the_whole_resume_journey(self, authed_client: AsyncClient):
        """The default role must not have lost anything it had before M4."""
        uploaded = await authed_client.post("/resumes", **resume_upload())
        assert uploaded.status_code == 201
        assert (await authed_client.get("/resumes")).status_code == 200
        assert (await authed_client.get(f"/resumes/{uploaded.json()['id']}")).status_code == 200


class TestTheTwoRefusalsStayApart:
    async def test_someone_elses_job_is_404_even_for_a_recruiter(self, client: AsyncClient):
        """The case that would silently become 403 if the two checks were merged.

        Both accounts have the role, so nothing about the *route* is refused — only
        the row — and the answer must not confirm the id exists.
        """
        await register_as(client, email="owner@example.com", role="recruiter")
        job_id = (await client.post("/jobs", json=JOB)).json()["id"]

        await register_as(client, email="rival@example.com", role="recruiter")

        assert (await client.get(f"/jobs/{job_id}")).status_code == 404
        assert (
            await client.patch(f"/jobs/{job_id}", json={"title": "mine now"})
        ).status_code == 404
        assert (await client.delete(f"/jobs/{job_id}")).status_code == 404

    async def test_a_candidate_hitting_someone_elses_job_is_refused_by_role_first(
        self, client: AsyncClient
    ):
        """403 rather than 404, and that is not a leak.

        The role check runs as a dependency, before any row is looked up, so it
        cannot distinguish a real id from an invented one — and therefore cannot
        confirm either. Asserted so the ordering is a decision rather than an
        accident of how FastAPI resolves dependencies.
        """
        await register_as(client, email="owner2@example.com", role="recruiter")
        job_id = (await client.post("/jobs", json=JOB)).json()["id"]

        await register_as(client, email="nosy@example.com")
        real = await client.patch(f"/jobs/{job_id}", json={"title": "x"})
        invented = await client.patch(
            "/jobs/00000000-0000-0000-0000-000000000000", json={"title": "x"}
        )

        assert real.status_code == 403
        assert invented.status_code == 403
        assert real.json() == invented.json(), "a real id and an invented one must look identical"


class TestTheRoleIsReadFromTheRow:
    async def test_a_role_change_takes_effect_without_a_new_token(
        self, client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        """The role is not in the token, on purpose.

        Putting it there would mean a demotion did nothing until the access token
        expired — a window in which a removed permission is still live. Every check
        reads `candidates.role`, so the next request is already correct.
        """
        await register_as(client, email="promoted@example.com")
        assert (await client.post("/jobs", json=JOB)).status_code == 403

        await _set_role(sessionmaker_for_tests, "promoted@example.com", Role.RECRUITER)

        # Same bearer token, no refresh.
        assert (await client.post("/jobs", json=JOB)).status_code == 201
        assert (await client.get("/auth/me")).json()["role"] == "recruiter"
