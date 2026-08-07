"""Retry, backoff and the dead-letter queue.

The policy lives in `app/jobs.py` and returns a decision rather than raising arq's
`Retry`, so all of it is exercised here without Redis. `tests/test_worker.py`
covers the adapter that turns that decision into a real deferred job.

The distinction being pinned throughout: a failure that says something about the
document (`failed`) versus one that might not happen again (`dead_lettered` once
the budget is spent). Only the second is worth replaying, which is why they are
different statuses rather than one `failed` with a comment.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.jobs import JobContext, backoff_seconds, is_retryable, run_resume_job
from app.llm.base import LLMConfigError, LLMResponseError, LLMUnavailableError
from app.llm.fake import FakeExtractor, FakeMode
from app.models import Resume, ResumeStatus
from app.pipeline.parse import CorruptDocumentError
from app.storage import LocalStorage, ObjectNotFoundError
from tests.conftest import resume_upload
from tests.test_worker import RecordingQueue


@pytest.fixture
def queue() -> RecordingQueue:
    """Replaces the inline queue, so the job runs only when a test says so."""
    return RecordingQueue()


@pytest.fixture
def fake_mode() -> FakeMode:
    """The whole module is about failure, so the backend is down by default."""
    return FakeMode.UNAVAILABLE


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


async def _load(session_factory: async_sessionmaker[AsyncSession], resume_id: uuid.UUID) -> Resume:
    async with session_factory() as session:
        return (await session.execute(select(Resume).where(Resume.id == resume_id))).scalar_one()


class TestClassification:
    """Which failures are worth trying again."""

    @pytest.mark.parametrize(
        "error",
        [
            LLMUnavailableError("the provider is down"),
            LLMResponseError("the reply did not match the schema"),
            RuntimeError("something nobody predicted"),
        ],
    )
    def test_transient_failures_are_retried(self, error: Exception):
        assert is_retryable(error)

    @pytest.mark.parametrize(
        "error",
        [
            CorruptDocumentError("this is not a readable PDF"),
            ObjectNotFoundError("resumes/x/y.pdf"),
            LLMConfigError("GEMINI_API_KEY is not set"),
        ],
    )
    def test_permanent_failures_are_not(self, error: Exception):
        """A broken document, a missing file and a missing key do not heal."""
        assert not is_retryable(error)

    def test_the_backoff_doubles(self, settings: Settings):
        base = settings.job_retry_base_seconds
        assert [backoff_seconds(settings, failures=n) for n in (1, 2, 3)] == [
            base,
            base * 2,
            base * 4,
        ]


class TestRetryLoop:
    async def test_a_transient_failure_asks_to_be_retried(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
    ):
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]

        outcome = await run_resume_job(context, resume_id)

        assert outcome.should_retry
        assert outcome.retry_after_seconds == settings.job_retry_base_seconds

        resume = await _load(sessionmaker_for_tests, resume_id)
        # Back in the queue's waiting state, with the reason visible meanwhile.
        assert resume.status is ResumeStatus.PENDING
        assert resume.failed_attempts == 1
        assert resume.attempts == 1
        assert resume.last_attempt_at is not None
        assert "retrying" in (resume.failure_reason or "")

    async def test_the_budget_runs_out_into_the_dead_letter_queue(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
    ):
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]

        for _ in range(settings.job_max_attempts - 1):
            assert (await run_resume_job(context, resume_id)).should_retry

        final = await run_resume_job(context, resume_id)

        # Giving up is not a retry: the queue must stop redelivering this.
        assert not final.should_retry
        resume = await _load(sessionmaker_for_tests, resume_id)
        assert resume.status is ResumeStatus.DEAD_LETTERED
        assert resume.attempts == settings.job_max_attempts
        assert f"after {settings.job_max_attempts} attempts" in (resume.failure_reason or "")

    async def test_the_parsed_text_survives_a_failed_attempt(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """Extraction failing must not throw away the parse it already paid for."""
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]

        await run_resume_job(context, resume_id)

        resume = await _load(sessionmaker_for_tests, resume_id)
        assert resume.document_text
        assert resume.page_count == 1

    async def test_a_permanent_failure_is_not_retried(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
    ):
        """A file that is gone will still be gone in five seconds."""
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]
        LocalStorage(settings.storage_path).clear()

        outcome = await run_resume_job(context, resume_id)

        assert not outcome.should_retry
        resume = await _load(sessionmaker_for_tests, resume_id)
        assert resume.status is ResumeStatus.FAILED
        assert resume.failure_reason == "The stored file is missing."
        # The reason must not leak the storage key: it embeds the candidate id
        # and the file's content hash.
        assert resume.storage_key not in resume.failure_reason

    async def test_a_scanned_pdf_fails_without_spending_the_budget(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """A parse failure is a fact about the document, not a job failure."""
        await authed_client.post("/resumes", files=resume_upload("resume_scanned.pdf"))
        resume_id = queue.enqueued[0]

        outcome = await run_resume_job(context, resume_id)

        assert not outcome.should_retry
        resume = await _load(sessionmaker_for_tests, resume_id)
        assert resume.status is ResumeStatus.FAILED
        assert resume.failed_attempts == 0
        assert "OCR" in (resume.failure_reason or "")

    async def test_a_success_clears_the_budget(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
    ):
        """Two blips and a success must not leave one strike hanging over it."""
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]
        storage = LocalStorage(settings.storage_path)

        down = JobContext(
            sessionmaker=sessionmaker_for_tests,
            storage=storage,
            extractor=FakeExtractor(FakeMode.UNAVAILABLE),
            settings=settings,
        )
        await run_resume_job(down, resume_id)
        assert (await _load(sessionmaker_for_tests, resume_id)).failed_attempts == 1

        recovered = JobContext(
            sessionmaker=sessionmaker_for_tests,
            storage=storage,
            extractor=FakeExtractor(FakeMode.FAITHFUL),
            settings=settings,
        )
        await run_resume_job(recovered, resume_id)

        resume = await _load(sessionmaker_for_tests, resume_id)
        assert resume.status is ResumeStatus.EXTRACTED
        assert resume.failed_attempts == 0
        # `attempts` is the honest total and keeps each dispatch's queue job id
        # distinct, so it does not reset.
        assert resume.attempts == 2


class TestRetryEndpoint:
    """The replay half of the dead-letter queue."""

    async def _dead_letter(
        self,
        client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        settings: Settings,
    ) -> str:
        uploaded = await client.post("/resumes", files=resume_upload())
        for _ in range(settings.job_max_attempts):
            await run_resume_job(context, queue.enqueued[0])
        return str(uploaded.json()["id"])

    async def test_a_dead_letter_can_be_replayed(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        settings: Settings,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        resume_id = await self._dead_letter(authed_client, queue, context, settings)
        queue.dispatches.clear()

        response = await authed_client.post(f"/resumes/{resume_id}/retry")

        assert response.status_code == 200
        assert response.json()["status"] == ResumeStatus.PENDING
        resume = await _load(sessionmaker_for_tests, uuid.UUID(resume_id))
        assert resume.failed_attempts == 0
        assert resume.failure_reason is None

        # The replay must reach the queue under a dispatch id the failed run does
        # not own, or the queue would refuse it as a duplicate.
        assert queue.dispatches == [(uuid.UUID(resume_id), settings.job_max_attempts)]

    async def test_the_replayed_work_can_then_succeed(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        settings: Settings,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """The point of keeping dead letters: fix the cause, run them again."""
        resume_id = await self._dead_letter(authed_client, queue, context, settings)
        await authed_client.post(f"/resumes/{resume_id}/retry")

        recovered = JobContext(
            sessionmaker=sessionmaker_for_tests,
            storage=LocalStorage(settings.storage_path),
            extractor=FakeExtractor(FakeMode.FAITHFUL),
            settings=settings,
        )
        await run_resume_job(recovered, uuid.UUID(resume_id))

        response = await authed_client.get(f"/resumes/{resume_id}")
        assert response.json()["resume"]["status"] == ResumeStatus.EXTRACTED
        assert response.json()["profile"]["full_name"]["value"] == "Somchai Jaidee"

    async def test_an_extracted_resume_refuses_a_retry(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
    ):
        """Re-extracting would bill a second call to reproduce what we have."""
        uploaded = await authed_client.post("/resumes", files=resume_upload())
        working = JobContext(
            sessionmaker=sessionmaker_for_tests,
            storage=LocalStorage(settings.storage_path),
            extractor=FakeExtractor(FakeMode.FAITHFUL),
            settings=settings,
        )
        await run_resume_job(working, queue.enqueued[0])
        queue.dispatches.clear()

        response = await authed_client.post(f"/resumes/{uploaded.json()['id']}/retry")

        assert response.status_code == 409
        assert queue.dispatches == []

    async def test_a_queued_resume_refuses_a_retry(
        self, authed_client: AsyncClient, queue: RecordingQueue
    ):
        """It is already queued; a second dispatch would only race the first."""
        uploaded = await authed_client.post("/resumes", files=resume_upload())
        response = await authed_client.post(f"/resumes/{uploaded.json()['id']}/retry")
        assert response.status_code == 409

    async def test_another_candidates_resume_cannot_be_retried(
        self, client: AsyncClient, queue: RecordingQueue
    ):
        """404 rather than 403 — the response should not confirm the id exists."""
        owner = await client.post(
            "/auth/register", json={"email": "owner@example.com", "password": "a-good-password"}
        )
        client.headers["Authorization"] = f"Bearer {owner.json()['access_token']}"
        uploaded = await client.post("/resumes", files=resume_upload())

        intruder = await client.post(
            "/auth/register", json={"email": "other@example.com", "password": "a-good-password"}
        )
        client.headers["Authorization"] = f"Bearer {intruder.json()['access_token']}"

        response = await client.post(f"/resumes/{uploaded.json()['id']}/retry")
        assert response.status_code == 404


class _RefusesToPersistExtractions:
    """A sessionmaker whose sessions refuse the commit that persists a profile.

    Stands in for what Postgres did in the 2026-08-07 incident — accepting every
    statement until the success commit, then raising `DBAPIError` (there, over a
    NUL in `document_text`). The claim commit and the failure bookkeeping still
    go through, which is exactly the shape that used to strand the resume at
    `processing`. The error message deliberately embeds `secret` the way a real
    `DBAPIError` embeds the statement's parameters.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], secret: str) -> None:
        self._sessionmaker = sessionmaker
        self._secret = secret

    def __call__(self) -> AsyncSession:
        session = self._sessionmaker()
        real_commit = session.commit

        async def commit() -> None:
            if any(
                isinstance(obj, Resume) and obj.status is ResumeStatus.EXTRACTED
                for obj in session.dirty
            ):
                raise DBAPIError(
                    "INSERT INTO extracted_profiles (profile) VALUES ($1)",
                    {"document_text": self._secret},
                    Exception(f'invalid byte sequence for encoding "UTF8": {self._secret}'),
                )
            await real_commit()

        session.commit = commit  # type: ignore[method-assign]
        return session


class TestAFailingCommit:
    """The success commit is part of the job, not an epilogue (HANDOFF §11).

    A real PDF proved the commit itself can fail. That failure must go through
    the retry policy like any other unexpected error — escaping instead leaves
    the resume at `processing`, where redelivery, `POST /retry` and re-upload
    all refuse to touch it.
    """

    SECRET = "RESUME TEXT THAT MUST NEVER LEAK"

    @pytest.fixture
    def context(
        self,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> JobContext:
        return JobContext(
            sessionmaker=_RefusesToPersistExtractions(sessionmaker_for_tests, self.SECRET),
            storage=LocalStorage(settings.storage_path),
            extractor=FakeExtractor(FakeMode.FAITHFUL),
            settings=settings,
        )

    async def test_a_failing_commit_is_retried_not_stranded(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]

        outcome = await run_resume_job(context, resume_id)

        assert outcome.should_retry
        resume = await _load(sessionmaker_for_tests, resume_id)
        assert resume.status is ResumeStatus.PENDING
        assert resume.failed_attempts == 1

    async def test_the_budget_still_ends_at_the_dead_letter_queue(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
    ):
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]

        for _ in range(settings.job_max_attempts - 1):
            assert (await run_resume_job(context, resume_id)).should_retry
        assert not (await run_resume_job(context, resume_id)).should_retry

        resume = await _load(sessionmaker_for_tests, resume_id)
        assert resume.status is ResumeStatus.DEAD_LETTERED

    async def test_neither_the_reason_nor_the_log_quotes_the_statement(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        caplog: pytest.LogCaptureFixture,
    ):
        """A DBAPIError message embeds the statement's parameters — resume text
        included. Only the exception's type name may be recorded or logged."""
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]

        with caplog.at_level(logging.DEBUG):
            await run_resume_job(context, resume_id)

        resume = await _load(sessionmaker_for_tests, resume_id)
        assert "DBAPIError" in (resume.failure_reason or "")
        assert self.SECRET not in (resume.failure_reason or "")
        assert self.SECRET not in caplog.text


class TestConcurrentDelivery:
    async def test_a_second_delivery_will_not_run_alongside_the_first(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """A resume already claimed by a worker is left alone.

        Without this, a duplicate delivery would extract the same document twice
        and bill for it twice.
        """
        await authed_client.post("/resumes", files=resume_upload())
        resume_id = queue.enqueued[0]

        async with sessionmaker_for_tests() as session:
            claimed = (
                await session.execute(select(Resume).where(Resume.id == resume_id))
            ).scalar_one()
            claimed.status = ResumeStatus.PROCESSING
            await session.commit()

        outcome = await run_resume_job(context, resume_id)

        assert not outcome.should_retry
        resume = await _load(sessionmaker_for_tests, resume_id)
        assert resume.status is ResumeStatus.PROCESSING
        assert resume.attempts == 0
