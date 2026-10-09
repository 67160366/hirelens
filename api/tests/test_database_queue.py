"""Restart recovery and retries of the hosting profile, through real jobs."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.database_queue import DatabaseQueue
from app.jobs import JobContext, reclaim_stalled
from app.llm.fake import FakeExtractor, FakeMode
from app.models import Resume, ResumeStatus
from app.models.base import utcnow
from app.storage import LocalStorage
from tests.conftest import resume_upload
from tests.test_screening import JOB_PAYLOAD


@pytest.fixture
def context(sessionmaker_for_tests, settings) -> JobContext:
    return JobContext(
        sessionmaker=sessionmaker_for_tests,
        settings=settings,
        storage=LocalStorage(settings.storage_path),
        extractor=FakeExtractor(),
    )


@pytest.fixture
def queue(context) -> DatabaseQueue:
    # No automatic consumer here, so each crash and retry has a clear boundary.
    return DatabaseQueue(context)


async def test_restart_discovers_committed_work_without_enqueue(
    authed_client: AsyncClient, context: JobContext
):
    uploaded = await authed_client.post("/resumes", **resume_upload())
    resume_id = uploaded.json()["id"]
    restarted = DatabaseQueue(context)
    assert await restarted.run_once()
    result = await authed_client.get(f"/resumes/{resume_id}")
    assert result.json()["resume"]["status"] == "extracted"
    assert result.json()["profile"]["full_name"]["value"] == "Somchai Jaidee"
    assert not await restarted.run_once()  # Never re-extract finished work.


async def test_retry_backoff_and_dead_letter_survive_restarts(
    authed_client: AsyncClient,
    context: JobContext,
    sessionmaker_for_tests: async_sessionmaker[AsyncSession],
):
    context.extractor = FakeExtractor(FakeMode.UNAVAILABLE)
    uploaded = await authed_client.post("/resumes", **resume_upload())
    resume_id = uuid.UUID(uploaded.json()["id"])
    assert await DatabaseQueue(context).run_once()
    for failures in range(1, context.settings.job_max_attempts):
        async with sessionmaker_for_tests() as session:
            resume = await session.get(Resume, resume_id)
            assert resume is not None and resume.last_attempt_at is not None
            assert resume.failed_attempts == failures
            retry_at = resume.last_attempt_at + timedelta(
                seconds=context.settings.job_retry_base_seconds * 2 ** (failures - 1)
            )
        restarted = DatabaseQueue(context)
        assert not await restarted.run_once(now=retry_at - timedelta(milliseconds=1))
        assert await restarted.run_once(now=retry_at + timedelta(milliseconds=1))
    result = await authed_client.get(f"/resumes/{resume_id}")
    assert result.json()["resume"]["status"] == "dead_lettered"
    assert not await DatabaseQueue(context).run_once(now=utcnow() + timedelta(days=1))


async def test_interrupted_job_is_reclaimed_then_processed(
    authed_client: AsyncClient,
    context: JobContext,
    queue: DatabaseQueue,
    sessionmaker_for_tests: async_sessionmaker[AsyncSession],
):
    uploaded = await authed_client.post("/resumes", **resume_upload())
    resume_id = uuid.UUID(uploaded.json()["id"])
    async with sessionmaker_for_tests() as session:
        resume = await session.get(Resume, resume_id)
        assert resume is not None
        resume.status = ResumeStatus.PROCESSING
        resume.attempts = 1
        resume.last_attempt_at = utcnow() - timedelta(hours=1)
        await session.commit()
    assert await reclaim_stalled(context) == 1
    assert await queue.run_once(now=utcnow() + timedelta(minutes=1))
    result = await authed_client.get(f"/resumes/{resume_id}")
    assert result.json()["resume"]["status"] == "extracted"


async def test_screening_uses_the_same_durable_consumer(
    recruiter_client: AsyncClient, queue: DatabaseQueue
):
    job = await recruiter_client.post("/jobs", json=JOB_PAYLOAD)
    uploaded = await recruiter_client.post("/resumes", **resume_upload())
    assert await queue.run_once()
    screening = await recruiter_client.post(
        f"/jobs/{job.json()['id']}/screenings", json={"resume_id": uploaded.json()["id"]}
    )
    assert screening.status_code == 202, screening.text
    assert await queue.run_once()
    result = await recruiter_client.get(f"/screenings/{screening.json()['id']}")
    assert result.json()["screening"]["status"] == "completed"


def test_database_settings_require_safe_schema_and_verified_tls():
    import ssl

    from app.db import database_connect_args

    args = database_connect_args(
        Settings(_env_file=None, database_ssl=True, database_schema="hirelens")
    )
    assert args["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert args["ssl"].check_hostname
    assert args["server_settings"] == {"search_path": "hirelens"}
    with pytest.raises(ValueError, match="identifier"):
        database_connect_args(
            Settings(_env_file=None, database_schema='hirelens"; DROP SCHEMA public')
        )
