"""The publication lifecycle: who may make a posting public, and what a draft is.

Two halves, and the first is the one the careers site rests on.

**Only an admin may publish.** `SelfServiceRole` lets anyone register as a recruiter, so
a recruiter who could publish would mean anyone who can register can put a posting on the
public site under HireLens's name. That is not a permissions detail — it is the reason
migration `0013` has to land before any public route exists, and it is why the refusal is
tested from the recruiter's side rather than only asserted from the admin's.

**A draft is invisible, and "invisible" has to mean invisible to every door.** A rule that
only hides a row from the list it is normally reached through is not a rule, it is a
default. So the same posting is knocked on three ways here — read it directly, find it in
a list, apply to it — because those are three separate code paths and each could grow its
own answer.

The rule table itself is exercised without a database at the bottom of the module, the
way `applications.py`'s is: it is a pure function, so every cell is cheap to check and
none of them needs a server.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import JobStatus, Role
from app.publication import Publisher, Refused, decide, is_public
from tests.conftest import publish_job, register_as, resume_upload, set_role

JOB = {
    "title": "Backend Engineer",
    "description": "Written, but not yet public.",
    "location": "กรุงเทพมหานคร",
    "requirements": [{"kind": "skill", "label": "Python"}],
}


async def _post_a_job(client: AsyncClient) -> str:
    response = await client.post("/jobs", json=JOB)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


class TestWhereAPostingStarts:
    async def test_a_new_posting_is_a_draft_and_says_when_it_is_not_public(
        self, recruiter_client: AsyncClient
    ):
        """The default is the safe one, which is the whole point of having it.

        `published_at` is null rather than the creation time: a board orders by it, and
        a posting nobody has published has no date on which it appeared.
        """
        response = await recruiter_client.post("/jobs", json=JOB)
        body = response.json()

        assert body["status"] == "draft"
        assert body["published_at"] is None
        assert body["location"] == "กรุงเทพมหานคร"

    async def test_a_posting_cannot_be_created_already_published(
        self, recruiter_client: AsyncClient
    ):
        """`status` is not an authoring field, so this is ignored rather than obeyed.

        A second way to reach `published` would be a second thing to guard, and the
        one that gets forgotten. Pydantic drops the unknown key; the assertion is that
        the row is a draft anyway.
        """
        response = await recruiter_client.post("/jobs", json={**JOB, "status": "published"})
        assert response.json()["status"] == "draft"


class TestWhoMayPublish:
    async def test_a_recruiter_cannot_publish_their_own_posting(
        self, recruiter_client: AsyncClient
    ):
        """The rule the careers site rests on, refused from the side that matters.

        Anyone can register as a recruiter, so if this returned 200 then the answer to
        "who may publish under HireLens's name?" would be "anybody".
        """
        job_id = await _post_a_job(recruiter_client)

        response = await recruiter_client.post(
            f"/jobs/{job_id}/publication", json={"status": "published"}
        )
        assert response.status_code == 409
        # In words, not a bare code: a recruiter who cannot publish their own posting
        # deserves to know it is a rule rather than a bug.
        assert "administrator" in response.json()["detail"]
        assert "register as a recruiter" in response.json()["detail"]

    async def test_an_admin_can_publish_and_the_date_is_stamped(
        self,
        recruiter_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        job_id = await _post_a_job(recruiter_client)
        await set_role(sessionmaker_for_tests, "recruiter@example.com", Role.ADMIN)

        response = await recruiter_client.post(
            f"/jobs/{job_id}/publication", json={"status": "published"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "published"
        assert response.json()["published_at"] is not None

    async def test_republishing_does_not_move_the_date_it_first_appeared(
        self,
        recruiter_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """A board orders by `published_at`, so a posting taken down and put back must
        not jump to the top as though it were new."""
        job_id = await _post_a_job(recruiter_client)
        await set_role(sessionmaker_for_tests, "recruiter@example.com", Role.ADMIN)

        first = (
            await recruiter_client.post(f"/jobs/{job_id}/publication", json={"status": "published"})
        ).json()["published_at"]
        await recruiter_client.post(f"/jobs/{job_id}/publication", json={"status": "draft"})
        again = (
            await recruiter_client.post(f"/jobs/{job_id}/publication", json={"status": "published"})
        ).json()["published_at"]

        # Parsed rather than string-compared: the *same* instant serializes with a
        # trailing `Z` when it is still the value we set and without one after a
        # SQLite round trip, because SQLite has no `timestamptz` and drops the
        # offset. Pre-existing and shared with `created_at`; on Postgres the column
        # is `timestamptz` and stays aware. The property under test is the instant.
        assert datetime.fromisoformat(again.rstrip("Z")) == datetime.fromisoformat(
            first.rstrip("Z")
        )

    async def test_an_owner_may_take_their_own_posting_down(
        self,
        recruiter_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """The asymmetry, and it is deliberate: withdrawing something you wrote needs
        no gatekeeper, while putting it in front of the public does."""
        job_id = await _post_a_job(recruiter_client)
        await publish_job(
            recruiter_client,
            job_id=job_id,
            as_email="recruiter@example.com",
        )

        response = await recruiter_client.post(
            f"/jobs/{job_id}/publication", json={"status": "draft"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "draft"

    async def test_asking_for_the_status_it_already_has_is_not_an_error(
        self, recruiter_client: AsyncClient
    ):
        """200 rather than 409, the same instinct as a duplicate upload: a retried
        request must not look like an illegal move."""
        job_id = await _post_a_job(recruiter_client)

        response = await recruiter_client.post(
            f"/jobs/{job_id}/publication", json={"status": "draft"}
        )
        assert response.status_code == 200

    async def test_a_stranger_cannot_publish_or_learn_that_the_id_exists(
        self, recruiter_client: AsyncClient
    ):
        """404, not 403 — a 403 on an id confirms the id, which is the enumeration
        answer `_owned_job` is written to avoid."""
        job_id = await _post_a_job(recruiter_client)
        await register_as(recruiter_client, email="stranger@example.com", role="recruiter")

        response = await recruiter_client.post(
            f"/jobs/{job_id}/publication", json={"status": "published"}
        )
        assert response.status_code == 404


class TestWhatADraftIsInvisibleTo:
    """Three doors to the same row, because each is a separate code path."""

    @pytest.fixture
    async def a_strangers_draft(self, recruiter_client: AsyncClient) -> str:
        job_id = await _post_a_job(recruiter_client)
        await register_as(recruiter_client, email="outsider@example.com", role="candidate")
        return job_id

    async def test_it_cannot_be_read_directly(
        self, recruiter_client: AsyncClient, a_strangers_draft: str
    ):
        assert (await recruiter_client.get(f"/jobs/{a_strangers_draft}")).status_code == 404

    async def test_it_is_not_on_the_discovery_list(
        self, recruiter_client: AsyncClient, a_strangers_draft: str
    ):
        assert (await recruiter_client.get("/jobs")).json() == []

    async def test_it_cannot_be_applied_to(
        self, recruiter_client: AsyncClient, a_strangers_draft: str
    ):
        """404 rather than 409 here, because the caller is not supposed to know the
        posting exists at all — the same distinction `_owned_job` draws."""
        resume_id = (await recruiter_client.post("/resumes", **resume_upload())).json()["id"]
        response = await recruiter_client.post(
            f"/jobs/{a_strangers_draft}/applications", json={"resume_id": resume_id}
        )
        assert response.status_code == 404

    async def test_a_closed_posting_refuses_applications_with_a_reason(
        self,
        recruiter_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """409 and a sentence, not 404. The applicant could see this posting a moment
        ago, so hiding it now would be pretending rather than refusing."""
        job_id = await _post_a_job(recruiter_client)
        await publish_job(
            recruiter_client,
            job_id=job_id,
            as_email="recruiter@example.com",
        )
        await recruiter_client.post(f"/jobs/{job_id}/publication", json={"status": "closed"})

        resume_id = (await recruiter_client.post("/resumes", **resume_upload())).json()["id"]
        response = await recruiter_client.post(
            f"/jobs/{job_id}/applications", json={"resume_id": resume_id}
        )
        assert response.status_code == 409
        assert "closed" in response.json()["detail"]

    async def test_its_owner_still_sees_it(self, recruiter_client: AsyncClient):
        """The half that makes drafts worth having: a recruiter has to be able to read
        and list the posting they are still writing."""
        job_id = await _post_a_job(recruiter_client)

        assert (await recruiter_client.get(f"/jobs/{job_id}")).status_code == 200
        assert [job["id"] for job in (await recruiter_client.get("/jobs")).json()] == [job_id]


class TestTheRuleTable:
    """The decision itself, with no database in sight."""

    def test_only_an_admin_reaches_published(self):
        assert (
            decide(current=JobStatus.DRAFT, target=JobStatus.PUBLISHED, publisher=Publisher.ADMIN)
            is JobStatus.PUBLISHED
        )

        refused = decide(
            current=JobStatus.DRAFT, target=JobStatus.PUBLISHED, publisher=Publisher.OWNER
        )
        assert isinstance(refused, Refused)

    def test_an_owner_may_withdraw_but_not_reinstate(self):
        assert (
            decide(current=JobStatus.PUBLISHED, target=JobStatus.DRAFT, publisher=Publisher.OWNER)
            is JobStatus.DRAFT
        )
        assert isinstance(
            decide(current=JobStatus.CLOSED, target=JobStatus.PUBLISHED, publisher=Publisher.OWNER),
            Refused,
        )

    def test_nobody_is_not_a_publisher(self):
        assert isinstance(
            decide(current=JobStatus.DRAFT, target=JobStatus.CLOSED, publisher=None), Refused
        )

    def test_every_status_pair_has_an_answer(self):
        """Exhaustive, because a missing cell in `_ALLOWED` is a `KeyError` at runtime
        rather than a refusal — the same reason `applications.py` lists its terminal
        states with empty tables instead of leaving them out."""
        for current in JobStatus:
            for target in JobStatus:
                for publisher in (Publisher.OWNER, Publisher.ADMIN):
                    outcome = decide(current=current, target=target, publisher=publisher)
                    assert isinstance(outcome, (JobStatus, Refused))

    def test_publicness_is_one_predicate(self):
        assert is_public(JobStatus.PUBLISHED)
        assert not is_public(JobStatus.DRAFT)
        # A closed posting was public and is not any more. If this ever flips, the
        # public board starts advertising roles nobody can apply to.
        assert not is_public(JobStatus.CLOSED)

    def test_the_publisher_resolves_admin_before_owner(self):
        """Admin is *wider* than owner, so an admin who happens to own the posting
        still gets an admin's powers — the opposite of the narrowing a role gate
        would produce."""
        assert Publisher.of(Role.ADMIN, is_owner=True) is Publisher.ADMIN
        assert Publisher.of(Role.RECRUITER, is_owner=True) is Publisher.OWNER
        assert Publisher.of(Role.RECRUITER, is_owner=False) is None
        assert Publisher.of(Role.CANDIDATE, is_owner=False) is None
