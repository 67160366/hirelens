"""Job postings and their requirements: CRUD, the caps, and ownership isolation.

Ownership is the part worth testing hardest. A job carries what a recruiter is
screening for, and until M4's RBAC lands the only rule keeping one account out of
another's jobs is the `_owned_job` lookup — which must answer 404, not 403, so a
response never confirms that an id exists.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes.jobs import MAX_REQUIREMENTS_PER_JOB
from app.models import JobRequirement
from tests.conftest import publish_job, register_as

BACKEND_JOB = {
    "title": "Senior Backend Engineer",
    "description": "Thai-language postings are the norm here.",
    "requirements": [
        {"kind": "skill", "label": "Python", "must_have": True, "weight": 2.0},
        {"kind": "skill", "label": "FastAPI"},
        {"kind": "experience", "label": "3+ years backend", "detail": "Production services."},
        {"kind": "language", "label": "ภาษาไทย", "must_have": True},
    ],
}


async def create_job(client: AsyncClient, payload: dict | None = None) -> dict:
    response = await client.post("/jobs", json=payload or BACKEND_JOB)
    assert response.status_code == 201, response.text
    return response.json()


async def register_another_candidate(client: AsyncClient, email: str) -> None:
    """Swap the client onto a second account, so the first one's rows are foreign."""
    response = await client.post(
        "/auth/register", json={"email": email, "password": "another-pw", "role": "recruiter"}
    )
    assert response.status_code == 201, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


@pytest.fixture
async def authed_client(recruiter_client: AsyncClient) -> AsyncClient:
    """This whole module is the recruiter side, so the default client is one."""
    return recruiter_client


class TestCreatingAJob:
    async def test_requirements_come_back_in_the_order_they_were_given(
        self, authed_client: AsyncClient
    ):
        job = await create_job(authed_client)

        assert [item["label"] for item in job["requirements"]] == [
            "Python",
            "FastAPI",
            "3+ years backend",
            "ภาษาไทย",
        ]
        assert [item["position"] for item in job["requirements"]] == [0, 1, 2, 3]
        assert all(item["id"] for item in job["requirements"])

    async def test_the_fields_that_drive_judging_and_ranking_round_trip(
        self, authed_client: AsyncClient
    ):
        job = await create_job(authed_client)
        python, fastapi, experience, thai = job["requirements"]

        assert (python["kind"], python["must_have"], python["weight"]) == ("skill", True, 2.0)
        # The defaults matter: an unweighted requirement counts once and gates nothing.
        assert (fastapi["must_have"], fastapi["weight"]) == (False, 1.0)
        assert experience["detail"] == "Production services."
        assert thai["label"] == "ภาษาไทย"

    async def test_a_posting_may_be_created_before_it_is_decomposed(
        self, authed_client: AsyncClient
    ):
        job = await create_job(authed_client, {"title": "Draft role", "requirements": []})
        assert job["requirements"] == []

    async def test_it_requires_authentication(self, client: AsyncClient):
        assert (await client.post("/jobs", json=BACKEND_JOB)).status_code == 401

    @pytest.mark.parametrize(
        "requirement",
        [
            pytest.param({"label": "Python", "weight": 0}, id="zero weight"),
            pytest.param({"label": "Python", "weight": -1}, id="negative weight"),
            pytest.param({"label": ""}, id="empty label"),
            pytest.param({"label": "Python", "kind": "vibes"}, id="unknown kind"),
        ],
    )
    async def test_an_unusable_requirement_is_refused(
        self, authed_client: AsyncClient, requirement: dict
    ):
        response = await authed_client.post(
            "/jobs", json={"title": "Role", "requirements": [requirement]}
        )
        assert response.status_code == 422

    async def test_more_requirements_than_one_prompt_should_carry_are_refused(
        self, authed_client: AsyncClient
    ):
        """The whole list travels in one judging prompt, so the cap is a cost gate."""
        too_many = [{"label": f"Skill {n}"} for n in range(MAX_REQUIREMENTS_PER_JOB + 1)]
        response = await authed_client.post(
            "/jobs", json={"title": "Role", "requirements": too_many}
        )
        assert response.status_code == 422


class TestReadingJobs:
    async def test_a_job_reads_back_with_its_requirements(self, authed_client: AsyncClient):
        created = await create_job(authed_client)
        response = await authed_client.get(f"/jobs/{created['id']}")

        assert response.status_code == 200
        assert response.json() == created

    async def test_the_list_holds_only_your_own_jobs(self, authed_client: AsyncClient):
        await create_job(authed_client)
        await register_another_candidate(authed_client, "second@example.com")
        await create_job(authed_client, {"title": "Someone else's role", "requirements": []})

        response = await authed_client.get("/jobs")
        assert response.status_code == 200
        assert [job["title"] for job in response.json()] == ["Someone else's role"]

    async def test_an_unknown_id_is_not_found(self, authed_client: AsyncClient):
        missing = "00000000-0000-0000-0000-000000000000"
        assert (await authed_client.get(f"/jobs/{missing}")).status_code == 404


class TestOwnership:
    """404 rather than 403 everywhere: the answer must not confirm the id exists."""

    @pytest.fixture
    async def foreign_job_id(self, authed_client: AsyncClient) -> str:
        job = await create_job(authed_client)
        await register_another_candidate(authed_client, "intruder@example.com")
        return str(job["id"])

    async def test_someone_elses_draft_cannot_even_be_read(
        self, authed_client: AsyncClient, foreign_job_id: str
    ):
        """New with migration `0013`, and the reason the open read narrowed.

        A posting is created as a draft, and a draft is not an advertisement — it
        is something somebody is still writing. Before the publication lifecycle
        there was no way to say so, so every posting was readable by every
        signed-in account from the moment it existed.
        """
        assert (await authed_client.get(f"/jobs/{foreign_job_id}")).status_code == 404

    async def test_someone_elses_published_posting_can_be_read(
        self,
        client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """The one read that is deliberately open, and the only one.

        A published posting is an advertisement — it exists to be read by people
        who do not own it, and a candidate who cannot read one cannot decide
        whether to apply. Everything else here still answers 404, which is the
        distinction that matters: reading a posting is open, *doing* anything with
        it is not.

        The property is the one this test always pinned. Only the setup changed:
        it now takes a publishing step, because a posting has an editorial state
        to be in.
        """
        await register_as(client, email="poster@example.com", role="recruiter")
        job_id = str((await create_job(client))["id"])
        await publish_job(
            client,
            job_id=job_id,
            as_email="poster@example.com",
        )

        await register_another_candidate(client, "reader@example.com")
        response = await client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        assert response.json()["id"] == job_id

    async def test_someone_elses_job_cannot_be_edited(
        self, authed_client: AsyncClient, foreign_job_id: str
    ):
        response = await authed_client.patch(f"/jobs/{foreign_job_id}", json={"title": "Mine now"})
        assert response.status_code == 404

    async def test_someone_elses_job_cannot_be_deleted(
        self, authed_client: AsyncClient, foreign_job_id: str
    ):
        assert (await authed_client.delete(f"/jobs/{foreign_job_id}")).status_code == 404

    async def test_requirements_cannot_be_added_to_someone_elses_job(
        self, authed_client: AsyncClient, foreign_job_id: str
    ):
        response = await authed_client.post(
            f"/jobs/{foreign_job_id}/requirements", json={"label": "Injected"}
        )
        assert response.status_code == 404


class TestUpdatingAJob:
    async def test_a_patch_leaves_the_fields_it_does_not_mention_alone(
        self, authed_client: AsyncClient
    ):
        created = await create_job(authed_client)
        response = await authed_client.patch(
            f"/jobs/{created['id']}", json={"title": "Staff Backend Engineer"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "Staff Backend Engineer"
        assert body["description"] == created["description"]
        assert body["requirements"] == created["requirements"]

    async def test_an_explicit_null_clears_a_nullable_field(self, authed_client: AsyncClient):
        created = await create_job(authed_client)
        response = await authed_client.patch(f"/jobs/{created['id']}", json={"description": None})

        assert response.status_code == 200
        assert response.json()["description"] is None

    async def test_nulling_a_field_the_column_cannot_hold_is_refused(
        self, authed_client: AsyncClient
    ):
        """Better a 422 naming the field than an IntegrityError from the database."""
        created = await create_job(authed_client)
        response = await authed_client.patch(f"/jobs/{created['id']}", json={"title": None})

        assert response.status_code == 422
        assert "title" in response.json()["detail"]


class TestRequirements:
    async def test_an_added_requirement_lands_after_the_existing_ones(
        self, authed_client: AsyncClient
    ):
        created = await create_job(authed_client)
        response = await authed_client.post(
            f"/jobs/{created['id']}/requirements",
            json={"kind": "education", "label": "ปริญญาตรี วิศวกรรม"},
        )

        assert response.status_code == 201
        assert response.json()["position"] == len(created["requirements"])

        job = (await authed_client.get(f"/jobs/{created['id']}")).json()
        assert [item["label"] for item in job["requirements"]][-1] == "ปริญญาตรี วิศวกรรม"

    async def test_the_cap_is_enforced_when_adding_one_at_a_time_too(
        self, authed_client: AsyncClient
    ):
        full = [{"label": f"Skill {n}"} for n in range(MAX_REQUIREMENTS_PER_JOB)]
        created = await create_job(authed_client, {"title": "Role", "requirements": full})

        response = await authed_client.post(
            f"/jobs/{created['id']}/requirements", json={"label": "One too many"}
        )
        assert response.status_code == 409

    async def test_a_requirement_can_be_promoted_to_a_gate(self, authed_client: AsyncClient):
        created = await create_job(authed_client)
        fastapi = created["requirements"][1]

        response = await authed_client.patch(
            f"/jobs/{created['id']}/requirements/{fastapi['id']}",
            json={"must_have": True, "weight": 3.0},
        )

        assert response.status_code == 200
        assert response.json()["must_have"] is True
        assert response.json()["weight"] == 3.0
        # Untouched fields survive the patch.
        assert response.json()["label"] == "FastAPI"

    async def test_a_requirement_can_be_deleted(self, authed_client: AsyncClient):
        created = await create_job(authed_client)
        target = created["requirements"][0]

        response = await authed_client.delete(f"/jobs/{created['id']}/requirements/{target['id']}")
        assert response.status_code == 204

        job = (await authed_client.get(f"/jobs/{created['id']}")).json()
        assert "Python" not in [item["label"] for item in job["requirements"]]

    async def test_a_requirement_from_another_job_is_not_found(self, authed_client: AsyncClient):
        first = await create_job(authed_client)
        second = await create_job(authed_client, {"title": "Other role", "requirements": []})

        response = await authed_client.patch(
            f"/jobs/{second['id']}/requirements/{first['requirements'][0]['id']}",
            json={"label": "Crossed over"},
        )
        assert response.status_code == 404


class TestDeletingAJob:
    async def test_its_requirements_go_with_it(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """Orphaned requirements would be invisible rows nothing could ever reach."""
        created = await create_job(authed_client)

        assert (await authed_client.delete(f"/jobs/{created['id']}")).status_code == 204
        assert (await authed_client.get(f"/jobs/{created['id']}")).status_code == 404

        async with sessionmaker_for_tests() as session:
            remaining = await session.execute(select(func.count()).select_from(JobRequirement))
            assert remaining.scalar_one() == 0
