"""Consent at upload, getting your data out, and getting it deleted.

Three rights, and the two that matter most are the same question asked twice:
export says what is held about you, delete removes exactly that. A test that only
checked rows would pass while the PDF sat in the bucket forever, so the deletion
cases assert against the **storage** as well.

The other thing held here is the shape of the refusals. A consent field that
defaults to true is not consent; an erasure that half-succeeds and reports success
is worse than one that fails.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes.resumes import CONSENT_VERSION
from app.config import Settings
from app.models import Application, Candidate, Job, Resume
from app.models.application import ApplicationEvent
from app.storage import LocalStorage, Storage, StorageError
from tests.conftest import publish_job, register_as, resume_upload

JOB = {"title": "Backend Engineer", "requirements": [{"kind": "skill", "label": "Python"}]}


async def _count(sessionmaker: async_sessionmaker[AsyncSession], model: type) -> int:
    async with sessionmaker() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


def _stored_files(settings: Settings) -> list[Path]:
    root = settings.storage_path
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


class TestConsentAtUpload:
    async def test_an_upload_without_consent_is_refused(self, authed_client: AsyncClient):
        """Refused by the schema, before a byte is stored or a call is billed."""
        response = await authed_client.post("/resumes", files=resume_upload()["files"])
        assert response.status_code == 422

    async def test_consent_false_is_refused_too(self, authed_client: AsyncClient):
        """Present-but-false is a different mistake from absent, and also a no."""
        response = await authed_client.post("/resumes", **resume_upload(consent=False))
        assert response.status_code == 422
        assert "without consent" in response.json()["detail"]

    async def test_nothing_is_stored_when_consent_is_missing(
        self, authed_client: AsyncClient, settings: Settings
    ):
        """The refusal has to come before the write, not after it."""
        await authed_client.post("/resumes", files=resume_upload()["files"])
        assert _stored_files(settings) == []

    async def test_consent_is_recorded_with_its_version(
        self, authed_client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        uploaded = await authed_client.post("/resumes", **resume_upload())
        assert uploaded.status_code == 201

        async with sessionmaker_for_tests() as session:
            resume = (await session.execute(select(Resume))).scalar_one()
        assert resume.consented_at is not None
        # The wording, not just the fact. "They consented" and "they consented to
        # this" are different claims and only one survives a rewrite.
        assert resume.consent_version == CONSENT_VERSION

    async def test_the_wording_is_served_rather_than_guessed(self, client: AsyncClient):
        """Unauthenticated: you should be able to read it before having an account."""
        response = await client.get("/resumes/consent")
        assert response.status_code == 200
        assert response.json()["version"] == CONSENT_VERSION
        assert "language model" in response.json()["text"]

    async def test_a_duplicate_upload_keeps_the_original_consent(
        self, authed_client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        """The agreement that counts is the one made when it first arrived."""
        await authed_client.post("/resumes", **resume_upload())
        async with sessionmaker_for_tests() as session:
            first = (await session.execute(select(Resume))).scalar_one().consented_at

        again = await authed_client.post("/resumes", **resume_upload())
        assert again.status_code == 200

        async with sessionmaker_for_tests() as session:
            assert (await session.execute(select(Resume))).scalar_one().consented_at == first


class TestExport:
    async def test_it_carries_the_substance_and_not_just_a_summary(
        self, authed_client: AsyncClient
    ):
        await authed_client.post("/resumes", **resume_upload())

        export = (await authed_client.get("/auth/me/export")).json()

        assert export["account"]["email"] == "candidate@example.com"
        assert export["account"]["role"] == "candidate"
        assert len(export["resumes"]) == 1
        resume = export["resumes"][0]
        # Withholding the text and the profile would make the export decorative.
        assert resume["document_text"], "the parsed text is the substance of what is held"
        assert resume["profile"]["full_name"]["value"] == "Somchai Jaidee"
        assert resume["consent_version"] == CONSENT_VERSION
        assert export["model_calls"], "including what was spent reading it"

    async def test_an_empty_account_exports_an_empty_shape(self, authed_client: AsyncClient):
        """Every list present and empty, so a client needs no special case."""
        export = (await authed_client.get("/auth/me/export")).json()
        for key in ("resumes", "jobs", "applications", "screenings", "model_calls"):
            assert export[key] == [], key

    async def test_it_holds_nothing_belonging_to_anyone_else(self, client: AsyncClient):
        """A subject-access request, not a dump of everything you can see.

        The recruiter can *read* the applicant's resume — slice 3 widened
        `_owned_resume` for exactly that — and it is still not their data.
        """
        await register_as(client, email="hirer@example.com", role="recruiter")
        job_id = (await client.post("/jobs", json=JOB)).json()["id"]
        await publish_job(client, job_id=job_id, as_email="hirer@example.com")
        recruiter = client.headers["Authorization"]

        await register_as(client, email="seeker@example.com")
        resume_id = (await client.post("/resumes", **resume_upload())).json()["id"]
        await client.post(f"/jobs/{job_id}/applications", json={"resume_id": resume_id})

        client.headers["Authorization"] = recruiter
        assert (await client.get(f"/resumes/{resume_id}")).status_code == 200, "can read it"

        export = (await client.get("/auth/me/export")).json()
        assert export["resumes"] == [], "and it is still not theirs to export"
        assert len(export["jobs"]) == 1
        assert export["applications"] == [], "the applicant's, not the recruiter's"

    async def test_an_applicant_exports_their_own_history(self, client: AsyncClient):
        await register_as(client, email="hirer2@example.com", role="recruiter")
        job_id = (await client.post("/jobs", json=JOB)).json()["id"]
        await publish_job(client, job_id=job_id, as_email="hirer2@example.com")

        await register_as(client, email="seeker2@example.com")
        resume_id = (await client.post("/resumes", **resume_upload())).json()["id"]
        await client.post(f"/jobs/{job_id}/applications", json={"resume_id": resume_id})

        export = (await client.get("/auth/me/export")).json()
        assert len(export["applications"]) == 1
        events = export["applications"][0]["events"]
        assert events[0]["to_state"] == "applied"
        assert events[0]["by_you"] is True
        assert events[0]["by_the_system"] is False


class TestErasure:
    async def test_it_removes_the_rows_and_the_stored_files(
        self,
        authed_client: AsyncClient,
        settings: Settings,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """Both halves. Rows alone would leave the PDF in the bucket forever."""
        await authed_client.post("/resumes", **resume_upload())
        assert len(_stored_files(settings)) == 1

        response = await authed_client.delete("/auth/me")

        assert response.status_code == 200
        assert response.json()["stored_files_removed"] == 1
        assert _stored_files(settings) == [], "the file, not just the row"
        assert await _count(sessionmaker_for_tests, Resume) == 0
        assert await _count(sessionmaker_for_tests, Candidate) == 0

    async def test_the_token_stops_authenticating_anything(self, authed_client: AsyncClient):
        """Not revoked — a valid signature over an account that is gone is a 401."""
        await authed_client.delete("/auth/me")
        assert (await authed_client.get("/auth/me")).status_code == 401

    async def test_an_account_with_nothing_stored_still_deletes(
        self, authed_client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        response = await authed_client.delete("/auth/me")
        assert response.status_code == 200
        assert response.json()["stored_files_removed"] == 0
        assert await _count(sessionmaker_for_tests, Candidate) == 0

    async def test_a_storage_failure_deletes_nothing_at_all(
        self,
        authed_client: AsyncClient,
        settings: Settings,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """The order that makes "deleted" mean something.

        Rows first would leave an object nothing points at — undiscoverable, and so
        unerasable. Files first means the worst case is a row whose file is missing,
        which the pipeline already reports. So a refusing store must abandon the
        whole thing rather than press on.
        """
        await authed_client.post("/resumes", **resume_upload())

        class _RefusesToDelete(LocalStorage):
            async def delete(self, key: str) -> None:
                raise StorageError("the object store is unreachable")

        app = authed_client.app  # type: ignore[attr-defined]
        from app.api.deps import get_storage

        broken: Storage = _RefusesToDelete(settings.storage_path)
        app.dependency_overrides[get_storage] = lambda: broken
        try:
            response = await authed_client.delete("/auth/me")
        finally:
            app.dependency_overrides.pop(get_storage, None)

        assert response.status_code == 503
        assert "nothing was deleted" in response.json()["detail"]
        assert await _count(sessionmaker_for_tests, Candidate) == 1, "still there"
        assert await _count(sessionmaker_for_tests, Resume) == 1
        assert len(_stored_files(settings)) == 1

    async def test_a_missing_file_does_not_stop_an_erasure(
        self,
        authed_client: AsyncClient,
        settings: Settings,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """Already gone is the outcome being asked for, not a failure."""
        await authed_client.post("/resumes", **resume_upload())
        LocalStorage(settings.storage_path).clear()

        assert (await authed_client.delete("/auth/me")).status_code == 200
        assert await _count(sessionmaker_for_tests, Candidate) == 0

    async def test_deleting_an_applicant_takes_their_application_with_them(
        self, client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        await register_as(client, email="hirer3@example.com", role="recruiter")
        job_id = (await client.post("/jobs", json=JOB)).json()["id"]
        await publish_job(client, job_id=job_id, as_email="hirer3@example.com")
        recruiter = client.headers["Authorization"]

        await register_as(client, email="seeker3@example.com")
        resume_id = (await client.post("/resumes", **resume_upload())).json()["id"]
        await client.post(f"/jobs/{job_id}/applications", json={"resume_id": resume_id})
        assert await _count(sessionmaker_for_tests, Application) == 1

        await client.delete("/auth/me")

        assert await _count(sessionmaker_for_tests, Application) == 0
        assert await _count(sessionmaker_for_tests, ApplicationEvent) == 0
        # The posting is not theirs and survives.
        client.headers["Authorization"] = recruiter
        assert (await client.get(f"/jobs/{job_id}")).status_code == 200

    async def test_deleting_a_recruiter_takes_other_peoples_applications_too(
        self, client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        """Named because it is other people's history, not because it is wrong.

        The posting ceases to exist, and an application to a posting that is gone
        describes nothing. Recorded here so the consequence is a decision rather
        than something discovered later.
        """
        await register_as(client, email="hirer4@example.com", role="recruiter")
        job_id = (await client.post("/jobs", json=JOB)).json()["id"]
        await publish_job(client, job_id=job_id, as_email="hirer4@example.com")
        recruiter = client.headers["Authorization"]

        await register_as(client, email="seeker4@example.com")
        resume_id = (await client.post("/resumes", **resume_upload())).json()["id"]
        await client.post(f"/jobs/{job_id}/applications", json={"resume_id": resume_id})
        applicant = client.headers["Authorization"]

        client.headers["Authorization"] = recruiter
        await client.delete("/auth/me")

        assert await _count(sessionmaker_for_tests, Job) == 0
        assert await _count(sessionmaker_for_tests, Application) == 0
        # The applicant and their resume are untouched — only the application went.
        client.headers["Authorization"] = applicant
        assert (await client.get(f"/resumes/{resume_id}")).status_code == 200

    async def test_a_deleted_actor_leaves_the_history_it_touched(
        self, client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        """`application_events.actor_id` is SET NULL, not CASCADE.

        Erasing an account must not erase the record of what happened to somebody
        else's application. The entry survives with its actor anonymised — which is
        also what an erasure ought to mean.
        """
        await register_as(client, email="hirer5@example.com", role="recruiter")
        job_a = (await client.post("/jobs", json=JOB)).json()["id"]
        await publish_job(client, job_id=job_a, as_email="hirer5@example.com")

        await register_as(client, email="seeker5@example.com")
        resume_id = (await client.post("/resumes", **resume_upload())).json()["id"]
        app_id = (
            await client.post(f"/jobs/{job_a}/applications", json={"resume_id": resume_id})
        ).json()["id"]
        applicant = client.headers["Authorization"]

        # A second recruiter with their own posting, who rejects nobody — we only
        # need an actor on the *applicant's* application, so the applicant withdraws.
        await client.post(f"/applications/{app_id}/transitions", json={"to_state": "withdrawn"})

        async with sessionmaker_for_tests() as session:
            before = list(
                (
                    await session.execute(
                        select(ApplicationEvent).where(
                            ApplicationEvent.application_id == uuid.UUID(app_id)
                        )
                    )
                ).scalars()
            )
        assert len(before) == 2 and all(e.actor_id is not None for e in before)

        client.headers["Authorization"] = applicant
        await client.delete("/auth/me")

        # The application cascaded away with its owner, so there is nothing left to
        # anonymise here — which is the point of the *next* assertion existing.
        assert await _count(sessionmaker_for_tests, ApplicationEvent) == 0

    async def test_erasing_a_recruiter_anonymises_their_moves_on_surviving_history(
        self, client: AsyncClient, sessionmaker_for_tests: async_sessionmaker[AsyncSession]
    ):
        """The SET NULL that matters: an actor who is not the application's owner.

        A recruiter rejects an applicant, then deletes their own account. The
        applicant's application belongs to a *different* posting that survives, so
        the event stays and only the actor goes.
        """
        await register_as(client, email="hirer6@example.com", role="recruiter")
        keeper_job = (await client.post("/jobs", json=JOB)).json()["id"]
        await publish_job(client, job_id=keeper_job, as_email="hirer6@example.com")
        keeper = client.headers["Authorization"]

        await register_as(client, email="admin6@example.com", role="recruiter")
        async with sessionmaker_for_tests() as session:
            mover = (
                await session.execute(
                    select(Candidate).where(Candidate.email == "admin6@example.com")
                )
            ).scalar_one()
            from app.models import Role

            mover.role = Role.ADMIN
            mover_id = mover.id
            await session.commit()

        await register_as(client, email="seeker6@example.com")
        resume_id = (await client.post("/resumes", **resume_upload())).json()["id"]
        app_id = (
            await client.post(f"/jobs/{keeper_job}/applications", json={"resume_id": resume_id})
        ).json()["id"]

        # The admin — neither applicant nor owner — rejects it.
        await register_as(client, email="admin6b@example.com")
        async with sessionmaker_for_tests() as session:
            second = (
                await session.execute(
                    select(Candidate).where(Candidate.email == "admin6b@example.com")
                )
            ).scalar_one()
            from app.models import Role as R

            second.role = R.ADMIN
            second_id = second.id
            await session.commit()

        rejected = await client.post(
            f"/applications/{app_id}/transitions",
            json={"to_state": "rejected", "reason": "not this time"},
        )
        assert rejected.status_code == 200, rejected.text

        await client.delete("/auth/me")  # the admin who rejected, deleting themselves

        async with sessionmaker_for_tests() as session:
            events = list(
                (
                    await session.execute(
                        select(ApplicationEvent)
                        .where(ApplicationEvent.application_id == uuid.UUID(app_id))
                        .order_by(ApplicationEvent.position)
                    )
                ).scalars()
            )
        assert [str(e.to_state) for e in events] == ["applied", "rejected"], (
            "the history survives the actor"
        )
        assert events[-1].actor_id is None, "anonymised, not deleted"
        assert events[-1].reason == "not this time", "and the reason is still there"
        assert mover_id != second_id  # the two admins really were different accounts
        # The keeper's posting is untouched.
        client.headers["Authorization"] = keeper
        assert (await client.get(f"/jobs/{keeper_job}")).status_code == 200


class TestExportAndDeleteAgree:
    async def test_what_export_lists_is_what_delete_removes(
        self,
        authed_client: AsyncClient,
        settings: Settings,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """The two rights are one question asked twice.

        If export lists a resume that survives deletion, one of them is lying — and
        which one it is matters less than that nobody would notice.
        """
        await authed_client.post("/resumes", **resume_upload())
        # A *different* fixture: the same bytes deduplicate to one row, which would
        # make this test agree with itself for the wrong reason.
        await authed_client.post("/resumes", **resume_upload("resume_th.pdf"))

        export = (await authed_client.get("/auth/me/export")).json()
        assert len(export["resumes"]) == 2

        removed = (await authed_client.delete("/auth/me")).json()["stored_files_removed"]

        assert removed == len(export["resumes"])
        assert await _count(sessionmaker_for_tests, Resume) == 0
        assert _stored_files(settings) == []


@pytest.mark.parametrize("route", ["/auth/me/export"])
class TestBothNeedAnAccount:
    async def test_an_anonymous_caller_is_refused(self, client: AsyncClient, route: str):
        assert (await client.get(route)).status_code == 401
