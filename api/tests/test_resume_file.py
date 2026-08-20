"""Serving the original document, and the boxes drawn on it (M5 slice 4).

Two routes, one rule. `GET /resumes/{id}/file` is the only route in this system that
returns a document verbatim rather than something derived from it, and
`GET /resumes/{id}/geometry` says where each character of it sits. Both are read
through `_owned_resume(must_own=False)` — the predicate M4 slice 3 already widened —
so what this module mostly pins is that **nothing new was granted** and that the
refusal stays a 404.

The ownership matrix is the point. A recruiter reading a resume that was applied to
their posting is intended; a recruiter reading one off the street is the failure this
route would introduce if it authorized itself, and a **403** anywhere in here would
turn the id into an enumeration oracle.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_storage
from app.models import Candidate, Resume, Role
from app.storage import ObjectNotFoundError, Storage, StorageError
from tests.conftest import publish_job, register_as, resume_upload

JOB = {
    "title": "Backend Engineer",
    "requirements": [{"kind": "skill", "label": "Python"}],
}

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _own_resume(client: AsyncClient, name: str = "resume_en.pdf") -> str:
    uploaded = await client.post("/resumes", **resume_upload(name))
    assert uploaded.status_code in (200, 201), uploaded.text
    return str(uploaded.json()["id"])


async def _applied(client: AsyncClient) -> dict[str, str]:
    """A recruiter with a posting, a candidate who applied to it, and both tokens.

    The same shape as `tests/test_applications.py::_apply`, kept local because this
    module also needs the recruiter's token *before* the application exists — the
    404-then-200 pair is half of what it is checking.
    """
    await register_as(client, email="hirer@example.com", role="recruiter")
    job_id = (await client.post("/jobs", json=JOB)).json()["id"]
    await publish_job(client, job_id=job_id, as_email="hirer@example.com")
    recruiter = client.headers["Authorization"]

    await register_as(client, email="seeker@example.com")
    applicant = client.headers["Authorization"]
    resume_id = await _own_resume(client)

    return {
        "job": job_id,
        "resume": resume_id,
        "recruiter": recruiter,
        "applicant": applicant,
    }


async def _apply(client: AsyncClient, ids: dict[str, str]) -> str:
    client.headers["Authorization"] = ids["applicant"]
    created = await client.post(
        f"/jobs/{ids['job']}/applications", json={"resume_id": ids["resume"]}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def _set_role(sessionmaker: async_sessionmaker[AsyncSession], email: str, role: Role) -> None:
    """Grant a role out of band, exactly as `tests/test_rbac.py` does."""
    async with sessionmaker() as session:
        account = (
            await session.execute(select(Candidate).where(Candidate.email == email))
        ).scalar_one()
        account.role = role
        await session.commit()


class _BrokenStorage(Storage):
    """A store that is up enough to be asked and not enough to answer.

    Its own class rather than a monkeypatch on `LocalStorage`: the route's two
    exception branches are the contract, and `_translate` in `app/storage.py` is what
    decides which one a real backend produces. Faking the fault at the seam keeps
    this test about the route.
    """

    def __init__(self, error: StorageError) -> None:
        self._error = error

    async def put(self, key: str, data: bytes) -> None:  # pragma: no cover - unused
        raise self._error

    async def get(self, key: str) -> bytes:
        raise self._error

    async def delete(self, key: str) -> None:  # pragma: no cover - unused
        raise self._error

    async def exists(self, key: str) -> bool:  # pragma: no cover - unused
        return True


def _serve_with(client: AsyncClient, storage: Storage) -> None:
    """Swap the storage this app answers from, for the two fault cases."""
    client.app.dependency_overrides[get_storage] = lambda: storage  # type: ignore[attr-defined]


class TestWhoMaySeeTheDocument:
    async def test_the_uploader_gets_the_bytes_back(self, authed_client: AsyncClient):
        resume_id = await _own_resume(authed_client)

        response = await authed_client.get(f"/resumes/{resume_id}/file")

        assert response.status_code == 200
        assert response.content.startswith(b"%PDF-"), "the stored file, not a re-render"
        assert response.headers["content-type"].startswith(PDF_TYPE)

    async def test_a_stranger_gets_404_rather_than_403(self, client: AsyncClient):
        """403 on an id confirms the id exists. The whole ownership story rests on
        this staying a 404 — see `require_role`'s docstring for the other half."""
        await register_as(client, email="owner@example.com")
        resume_id = await _own_resume(client)

        await register_as(client, email="stranger@example.com")
        for route in ("file", "geometry"):
            response = await client.get(f"/resumes/{resume_id}/{route}")
            assert response.status_code == 404, route

    async def test_a_recruiter_may_not_read_a_resume_off_the_street(self, client: AsyncClient):
        ids = await _applied(client)
        client.headers["Authorization"] = ids["recruiter"]

        response = await client.get(f"/resumes/{ids['resume']}/file")

        assert response.status_code == 404, (
            "no application yet, so nothing was put in front of them"
        )

    async def test_a_recruiter_may_read_one_that_was_applied_to_their_job(
        self, client: AsyncClient
    ):
        ids = await _applied(client)
        await _apply(client, ids)
        client.headers["Authorization"] = ids["recruiter"]

        assert (await client.get(f"/resumes/{ids['resume']}/file")).status_code == 200
        assert (await client.get(f"/resumes/{ids['resume']}/geometry")).status_code == 200

    @pytest.mark.parametrize("terminal", ["rejected", "withdrawn"])
    async def test_access_survives_a_terminal_application(self, client: AsyncClient, terminal: str):
        """Decided with the owner on 2026-08-15, and pinned here so it is a decision
        rather than something rediscovered as a surprise: a recruiter who rejected
        somebody may still have to account for it, and the audit log exists so those
        decisions stay reviewable. `_owned_resume`'s widening reads the *application*,
        not its state."""
        ids = await _applied(client)
        application_id = await _apply(client, ids)

        if terminal == "rejected":
            client.headers["Authorization"] = ids["recruiter"]
            payload = {"to_state": "rejected", "reason": "not enough Python"}
        else:
            payload = {"to_state": "withdrawn"}
        moved = await client.post(f"/applications/{application_id}/transitions", json=payload)
        assert moved.status_code == 200, moved.text

        client.headers["Authorization"] = ids["recruiter"]
        assert (await client.get(f"/resumes/{ids['resume']}/file")).status_code == 200

    async def test_an_admin_may_read_any_of_them(
        self, client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        await register_as(client, email="owner@example.com")
        resume_id = await _own_resume(client)

        await register_as(client, email="boss@example.com")
        await _set_role(sessionmaker_for_tests, "boss@example.com", Role.ADMIN)

        assert (await client.get(f"/resumes/{resume_id}/file")).status_code == 200

    async def test_an_unknown_id_is_404_for_everyone(self, authed_client: AsyncClient):
        missing = "00000000-0000-0000-0000-000000000000"
        assert (await authed_client.get(f"/resumes/{missing}/file")).status_code == 404
        assert (await authed_client.get(f"/resumes/{missing}/geometry")).status_code == 404


class TestWhatTheResponseSays:
    async def test_it_is_not_cached_and_not_sniffed(self, authed_client: AsyncClient):
        """A resume in a shared browser cache is the same leak as one in a log."""
        resume_id = await _own_resume(authed_client)

        response = await authed_client.get(f"/resumes/{resume_id}/file")

        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"

    async def test_the_disposition_carries_no_filename(self, authed_client: AsyncClient):
        """The filename is the candidate's. It would land in the download history of
        a recruiter who only ever asked to look at the page."""
        resume_id = await _own_resume(authed_client)

        response = await authed_client.get(f"/resumes/{resume_id}/file")

        assert response.headers["content-disposition"] == "inline"
        assert "resume_en" not in response.headers["content-disposition"]

    async def test_a_docx_is_served_as_a_docx(self, authed_client: AsyncClient):
        """From the same suffix map the upload gate trusts, so a document can only be
        served as a type it was allowed in as."""
        resume_id = await _own_resume(authed_client, "resume_th.docx")

        response = await authed_client.get(f"/resumes/{resume_id}/file")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith(DOCX_TYPE)


class TestWhenTheStoreWillNotAnswer:
    async def test_a_missing_object_is_404(self, authed_client: AsyncClient):
        """Already-gone is the state erasure treats as done, so it is not a fault."""
        resume_id = await _own_resume(authed_client)
        _serve_with(authed_client, _BrokenStorage(ObjectNotFoundError("gone")))

        response = await authed_client.get(f"/resumes/{resume_id}/file")

        assert response.status_code == 404

    async def test_any_other_storage_fault_is_503(self, authed_client: AsyncClient):
        """The same split `is_retryable` and `delete_account` make: the request was
        fine, the store was not, and retrying is the right next move. A 500 would
        say the opposite."""
        resume_id = await _own_resume(authed_client)
        _serve_with(authed_client, _BrokenStorage(StorageError("connection refused")))

        response = await authed_client.get(f"/resumes/{resume_id}/file")

        assert response.status_code == 503

    async def test_a_storage_fault_does_not_quote_the_key(self, authed_client: AsyncClient):
        """The key embeds the candidate id and the file's content hash (§10)."""
        resume_id = await _own_resume(authed_client)
        _serve_with(authed_client, _BrokenStorage(StorageError("no route to host")))

        detail = (await authed_client.get(f"/resumes/{resume_id}/file")).json()["detail"]

        assert "no route to host" not in detail


class TestTheGeometryRoute:
    async def test_it_serves_the_stored_shape(self, authed_client: AsyncClient):
        """Served as written rather than re-declared, so there is one vocabulary for
        the boxes — but pinned here, because an untyped payload is one nothing would
        fail to strip. `/screenings/{id}` was serving `dropped` by accident for two
        milestones for exactly this reason."""
        resume_id = await _own_resume(authed_client, "resume_th.pdf")

        body = (await authed_client.get(f"/resumes/{resume_id}/geometry")).json()

        assert body["measured"] is True
        assert body["pages"], "a text-layer PDF has geometry"
        page = body["pages"][0]
        assert set(page) == {"page_number", "width", "height", "runs"}
        assert page["runs"][0]["x"], "one (x0, x1) pair per character"
        assert set(page["runs"][0]) == {"char_start", "top", "bottom", "x"}

    async def test_a_row_from_before_the_migration_says_so_rather_than_404ing(
        self, authed_client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        """`page_geometry` is nullable and **not backfilled** (migration `0010`), so
        this is every resume uploaded before 2026-08-15. The resume is there and
        readable; "not measured" is an answer about it, not a missing resource — and
        the client needs the two cases apart to say *why* it is falling back."""
        resume_id = await _own_resume(authed_client)
        async with sessionmaker_for_tests() as session:
            resume = await session.get(Resume, uuid.UUID(resume_id))
            assert resume is not None
            resume.page_geometry = None
            await session.commit()

        body = (await authed_client.get(f"/resumes/{resume_id}/geometry")).json()

        assert body["measured"] is False
        assert body["pages"] == []

    async def test_measured_and_empty_are_different_answers(
        self, authed_client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        """A `.docx` has no glyph boxes at all, and a page whose textmap could not be
        proven consistent is dropped from the list. Both are measured-and-empty,
        which is not the same claim as never-measured."""
        resume_id = await _own_resume(authed_client)
        async with sessionmaker_for_tests() as session:
            resume = await session.get(Resume, uuid.UUID(resume_id))
            assert resume is not None
            resume.page_geometry = []
            await session.commit()

        body = (await authed_client.get(f"/resumes/{resume_id}/geometry")).json()

        assert body["measured"] is True
        assert body["pages"] == []

    async def test_it_names_the_ocr_pages_itself(self, authed_client: AsyncClient):
        """`/jobs/[id]` holds a `ScreeningDetail`, which carries no `ResumeOut` — so
        the route that says which pages have no geometry also has to say which ones
        came from OCR, or the screen cannot tell a reader why."""
        resume_id = await _own_resume(authed_client)

        body = (await authed_client.get(f"/resumes/{resume_id}/geometry")).json()

        assert body["pages_from_ocr"] == []

    async def test_it_spends_nothing(self, authed_client: AsyncClient):
        """Both routes report on rows that already exist. Neither may bill a call —
        the same rule the dashboard and the audit view are held to."""
        resume_id = await _own_resume(authed_client)
        before = len((await authed_client.get("/metrics/usage")).json()["by_group"])

        await authed_client.get(f"/resumes/{resume_id}/file")
        await authed_client.get(f"/resumes/{resume_id}/geometry")

        usage = (await authed_client.get("/metrics/usage")).json()
        assert len(usage["by_group"]) == before
        assert usage["totals"]["calls"] == 1, "the one extraction the upload paid for"
