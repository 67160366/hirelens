"""The asynchronous path: upload enqueues, a worker does the work.

The rest of the suite runs on `InlineQueue`, where the job finishes before the
upload responds. That is convenient but it hides the split this milestone is
about, so these tests use a queue that only records what it was handed and then
drive `run_resume_job` themselves — the same function the ARQ worker calls.

No Redis is involved. `app/worker.py` is only the adapter between arq's calling
convention and `run_resume_job`; the work being correct is what matters here.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.jobs import JobContext, run_resume_job
from app.llm.fake import FakeExtractor, FakeMode
from app.models import Resume, ResumeStatus
from app.queue import JobQueue
from app.storage import LocalStorage
from tests.conftest import resume_upload


class RecordingQueue(JobQueue):
    """Accepts work and does nothing with it, so a test can run it deliberately."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue_resume(self, resume_id: uuid.UUID) -> None:
        self.enqueued.append(resume_id)


@pytest.fixture
def queue() -> RecordingQueue:
    """Replaces the inline queue from conftest for every test in this module."""
    return RecordingQueue()


@pytest.fixture
def context(
    sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    settings: Settings,
    fake_mode: FakeMode,
) -> JobContext:
    return JobContext(
        sessionmaker=sessionmaker_for_tests,
        storage=LocalStorage(settings.storage_path),
        extractor=FakeExtractor(fake_mode),
        settings=settings,
    )


class TestUploadEnqueues:
    async def test_upload_stores_the_file_and_queues_the_work(
        self, authed_client: AsyncClient, queue: RecordingQueue
    ):
        response = await authed_client.post("/resumes", files=resume_upload())

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == ResumeStatus.PENDING
        assert queue.enqueued == [uuid.UUID(body["id"])]

    async def test_the_resume_stays_pending_until_the_worker_runs(
        self, authed_client: AsyncClient, queue: RecordingQueue, context: JobContext
    ):
        """The whole point of the split: the request does not wait for the model."""
        uploaded = await authed_client.post("/resumes", files=resume_upload())
        resume_id = uploaded.json()["id"]

        before = await authed_client.get(f"/resumes/{resume_id}")
        assert before.json()["resume"]["status"] == ResumeStatus.PENDING
        assert before.json()["profile"] is None

        await run_resume_job(context, queue.enqueued[0])

        after = await authed_client.get(f"/resumes/{resume_id}")
        assert after.json()["resume"]["status"] == ResumeStatus.EXTRACTED
        assert after.json()["profile"]["full_name"]["value"] == "Somchai Jaidee"

    async def test_a_duplicate_upload_of_a_pending_resume_is_requeued(
        self, authed_client: AsyncClient, queue: RecordingQueue
    ):
        """Re-uploading is the obvious thing to do when nothing seems to happen.

        It must not dedupe to a row that is stuck at `pending` and then do nothing.
        """
        first = await authed_client.post("/resumes", files=resume_upload())
        second = await authed_client.post("/resumes", files=resume_upload())

        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert queue.enqueued == [uuid.UUID(first.json()["id"])] * 2

    async def test_a_duplicate_upload_of_a_finished_resume_is_not_requeued(
        self, authed_client: AsyncClient, queue: RecordingQueue, context: JobContext
    ):
        """Extraction costs money; a finished resume must not be redone."""
        await authed_client.post("/resumes", files=resume_upload())
        await run_resume_job(context, queue.enqueued[0])
        queue.enqueued.clear()

        again = await authed_client.post("/resumes", files=resume_upload())

        assert again.status_code == 200
        assert again.json()["status"] == ResumeStatus.EXTRACTED
        assert queue.enqueued == []


async def _load_with_results(session: AsyncSession, resume_id: uuid.UUID) -> Resume:
    """A resume with its profile and call log eagerly loaded, so assertions about
    them do not emit lazy IO outside the async context."""
    result = await session.execute(
        select(Resume)
        .where(Resume.id == resume_id)
        .options(selectinload(Resume.profile), selectinload(Resume.llm_calls))
    )
    return result.scalar_one()


class TestJob:
    async def test_running_twice_does_not_extract_twice(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """A retry (M2 #2) can deliver the same id twice. The second run is a no-op."""
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]

        await run_resume_job(context, resume_id)
        async with sessionmaker_for_tests() as session:
            first = await _load_with_results(session, resume_id)
            assert first.profile is not None
            profile_id = first.profile.id
            calls = len(first.llm_calls)

        await run_resume_job(context, resume_id)
        async with sessionmaker_for_tests() as session:
            second = await _load_with_results(session, resume_id)
            assert second.profile is not None
            # A second profile row, or a second billed call, would mean the job
            # re-ran the model over a document it had already processed.
            assert second.profile.id == profile_id
            assert len(second.llm_calls) == calls

    async def test_a_resume_deleted_before_pickup_is_not_an_error(self, context: JobContext):
        """Failing the job would only queue work that can never succeed."""
        await run_resume_job(context, uuid.uuid4())

    async def test_a_missing_stored_object_fails_the_resume_with_a_reason(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        settings: Settings,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """A resume left at `pending` with no explanation is the silent failure
        the journey's requirements rule out."""
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]

        LocalStorage(settings.storage_path).clear()
        await run_resume_job(context, resume_id)

        async with sessionmaker_for_tests() as session:
            resume = (
                await session.execute(select(Resume).where(Resume.id == resume_id))
            ).scalar_one()
            assert resume.status is ResumeStatus.FAILED
            assert resume.failure_reason == "The stored file is missing."


class TestWorkerWiring:
    async def test_the_task_name_matches_what_the_api_enqueues(self):
        """A rename on one side and not the other would be a silent dead queue."""
        from arq.worker import Function

        from app.queue import PROCESS_RESUME_TASK
        from app.worker import WorkerSettings

        registered = {
            item.name if isinstance(item, Function) else item.__name__
            for item in WorkerSettings.functions
        }
        assert PROCESS_RESUME_TASK in registered

    async def test_the_task_parses_the_id_and_runs_the_job(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """Ids cross Redis as strings; the adapter has to turn one back into a UUID."""
        from app.worker import CONTEXT_KEY, process_resume

        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]

        await process_resume({CONTEXT_KEY: context}, str(resume_id))

        async with sessionmaker_for_tests() as session:
            resume = (
                await session.execute(select(Resume).where(Resume.id == resume_id))
            ).scalar_one()
            assert resume.status is ResumeStatus.EXTRACTED
