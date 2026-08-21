"""The public careers routes: what a stranger may read, and what they may not.

Two things are pinned, and the second matters more than the first:

1.  A published posting is readable by somebody holding no account at all.
2.  **Nothing else is.** A draft, a closed posting and a posting that never existed
    are one answer with one body, and the payload carries no field that belongs to
    the company rather than to the advertisement. These routes are the first in the
    system with no `CandidateDep` in front of them, so every one of their refusals
    is load-bearing in a way an authenticated route's is not.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import publish_job, register_as

POSTING = {
    "title": "Backend Engineer",
    "description": "Thai-language postings are the norm here.",
    "location": "Bangkok, Thailand",
    "requirements": [
        {"kind": "skill", "label": "Python", "must_have": True, "weight": 3.0},
        {"kind": "skill", "label": "PostgreSQL", "detail": "Schema design.", "weight": 2.0},
    ],
}


async def _draft(client: AsyncClient, *, email: str = "hirer@example.com") -> str:
    await register_as(client, email=email, role="recruiter")
    response = await client.post("/jobs", json=POSTING)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _published(client: AsyncClient, *, email: str = "hirer@example.com") -> str:
    job_id = await _draft(client, email=email)
    await publish_job(client, job_id=job_id, as_email=email)
    return job_id


class TestAStrangerMayReadWhatWasPublished:
    async def test_the_board_needs_no_account(self, client: AsyncClient):
        job_id = await _published(client)
        client.headers.pop("Authorization", None)

        response = await client.get("/careers/postings")
        assert response.status_code == 200, response.text
        assert [posting["id"] for posting in response.json()] == [job_id]

    async def test_one_posting_needs_no_account(self, client: AsyncClient):
        job_id = await _published(client)
        client.headers.pop("Authorization", None)

        response = await client.get(f"/careers/postings/{job_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == POSTING["title"]
        assert body["location"] == POSTING["location"]
        assert [item["label"] for item in body["requirements"]] == ["Python", "PostgreSQL"]

    async def test_the_board_is_newest_first(self, client: AsyncClient):
        first = await _published(client)
        second = await _published(client, email="hirer2@example.com")
        client.headers.pop("Authorization", None)

        listed = [posting["id"] for posting in (await client.get("/careers/postings")).json()]
        assert listed == [second, first]


class TestWhatItRefusesToSay:
    async def test_a_draft_is_not_listed_and_not_readable(self, client: AsyncClient):
        job_id = await _draft(client)
        client.headers.pop("Authorization", None)

        assert (await client.get("/careers/postings")).json() == []
        assert (await client.get(f"/careers/postings/{job_id}")).status_code == 404

    async def test_a_draft_and_a_fiction_are_indistinguishable(self, client: AsyncClient):
        """Any difference here turns the route into a way to count the company's
        unfinished work — the same reason `_owned_job` answers 404 rather than 403."""
        job_id = await _draft(client)
        client.headers.pop("Authorization", None)

        draft = await client.get(f"/careers/postings/{job_id}")
        fiction = await client.get("/careers/postings/00000000-0000-0000-0000-000000000000")
        assert draft.status_code == fiction.status_code == 404
        assert draft.json() == fiction.json()

    async def test_a_closed_posting_leaves_the_board(self, client: AsyncClient):
        job_id = await _published(client)
        closed = await client.post(f"/jobs/{job_id}/publication", json={"status": "closed"})
        assert closed.status_code == 200, closed.text
        client.headers.pop("Authorization", None)

        assert (await client.get("/careers/postings")).json() == []
        assert (await client.get(f"/careers/postings/{job_id}")).status_code == 404

    async def test_nothing_about_the_company_leaks_into_the_advertisement(
        self, client: AsyncClient
    ):
        """`owner_id` names which employee typed it; `weight` is how to game the
        screening; `status` is a security property a client should never branch on."""
        job_id = await _published(client)
        client.headers.pop("Authorization", None)

        body = (await client.get(f"/careers/postings/{job_id}")).json()
        assert "owner_id" not in body
        assert "status" not in body
        for requirement in body["requirements"]:
            assert "weight" not in requirement
            assert "id" not in requirement
            assert requirement["must_have"] in (True, False), (
                "what you are measured on is not a secret — hiding it while screening "
                "on it is the behaviour this project exists to refuse"
            )

    async def test_it_serves_reads_and_nothing_else(self, client: AsyncClient):
        """Read-only is a boundary, not a phase. A write here would be a write with
        no account behind it."""
        job_id = await _published(client)
        client.headers.pop("Authorization", None)

        for method in (client.post, client.patch, client.delete):
            response = await method(f"/careers/postings/{job_id}")
            assert response.status_code == 405, f"{method.__name__} reached a handler"
