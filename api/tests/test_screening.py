"""Screening a resume against a job, as a row on the background worker.

Three things are being pinned here, and they fail in different ways:

*   the **fingerprint**, which decides when a stored result stops answering the
    current question. Getting it too broad re-runs screenings nobody changed;
    getting it too narrow serves a stale verdict as though it were current.
*   the **shared retry policy**. `decide_retry` is now used by two job types, so it
    is tested directly rather than only through a resume.
*   the **job**, which has to record a judgment, its cost and its failures on a row
    without any of it looking like a resume's.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.jobs import JobContext, RetryVerdict, decide_retry, run_resume_job, run_screening_job
from app.llm.base import LLMConfigError, LLMUnavailableError
from app.llm.fake import FakeExtractor, FakeMode
from app.models import LLMCallLog, Resume, Screening, ScreeningStatus
from app.pipeline.judge import requirements_fingerprint
from app.pipeline.parse import ParseError
from app.pipeline.prompts import JUDGMENT_PROMPT_VERSION
from app.schemas.judgment import RequirementSpec, Verdict
from app.services.screening_service import NotScreenable
from app.storage import LocalStorage
from tests.conftest import resume_upload
from tests.test_worker import RecordingQueue

JOB_PAYLOAD = {
    "title": "Backend Engineer",
    "requirements": [
        {"kind": "skill", "label": "Python", "must_have": True},
        {"kind": "skill", "label": "PostgreSQL"},
        {"kind": "skill", "label": "Kubernetes"},
    ],
}


@pytest.fixture
def queue() -> RecordingQueue:
    """Replaces the inline queue so a test runs the screening job deliberately."""
    return RecordingQueue()


@pytest.fixture
def context(
    settings: Settings,
    sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    fake_mode: FakeMode,
) -> JobContext:
    return JobContext(
        sessionmaker=sessionmaker_for_tests,
        storage=LocalStorage(settings.storage_path),
        extractor=FakeExtractor(fake_mode),
        settings=settings,
    )


def spec(label: str, **overrides: object) -> RequirementSpec:
    fields: dict[str, object] = {"id": f"r-{label}", "label": label, "kind": "skill"}
    fields.update(overrides)
    return RequirementSpec(**fields)  # type: ignore[arg-type]


async def _job_and_resume(
    client: AsyncClient, context: JobContext, **job_overrides: object
) -> tuple[str, str]:
    """A job with requirements and a *parsed* resume, both owned by the caller.

    The resume job is run explicitly because these tests replace the inline queue
    with `RecordingQueue`: without it the upload only queues work, the resume has no
    `document_text`, and every screening is `NotScreenable` for the wrong reason.
    Parsing is enough — `process_resume` commits the text even when extraction
    fails, which is what lets the provider-down tests below share this helper.
    """
    payload = {**JOB_PAYLOAD, **job_overrides}
    job = await client.post("/jobs", json=payload)
    assert job.status_code == 201, job.text

    uploaded = await client.post("/resumes", files=resume_upload())
    assert uploaded.status_code in (200, 201), uploaded.text
    resume_id = uploaded.json()["id"]
    await run_resume_job(context, uuid.UUID(resume_id))
    return job.json()["id"], resume_id


class TestTheFingerprint:
    """What counts as "the same question", and what does not."""

    def test_the_same_requirements_fingerprint_the_same(self):
        one = [spec("Python"), spec("PostgreSQL")]
        two = [spec("Python"), spec("PostgreSQL")]
        assert requirements_fingerprint(one) == requirements_fingerprint(two)

    def test_reordering_is_a_different_question(self):
        """The model refers to requirements by position, so order is part of it."""
        forward = [spec("Python"), spec("PostgreSQL")]
        backward = [spec("PostgreSQL"), spec("Python")]
        assert requirements_fingerprint(forward) != requirements_fingerprint(backward)

    @pytest.mark.parametrize(
        ("field", "value"),
        [("label", "Python 3"), ("kind", "experience"), ("detail", "five years of it")],
    )
    def test_anything_the_prompt_carries_changes_it(self, field: str, value: str):
        before = [spec("Python")]
        after = [before[0].model_copy(update={field: value})]
        assert requirements_fingerprint(before) != requirements_fingerprint(after)

    @pytest.mark.parametrize(
        ("field", "value"), [("must_have", True), ("weight", 7.5), ("id", "different")]
    )
    def test_what_the_judge_never_sees_does_not_change_it(self, field: str, value: object):
        """`must_have` and `weight` are ranking's inputs and are not in the prompt,
        so a verdict cannot depend on them. Folding them in would re-run — and
        re-bill — every screening whenever someone nudged a weight."""
        before = [spec("Python")]
        after = [before[0].model_copy(update={field: value})]
        assert requirements_fingerprint(before) == requirements_fingerprint(after)

    def test_an_empty_list_still_fingerprints(self):
        assert requirements_fingerprint([])


class TestTheSharedRetryPolicy:
    """`decide_retry` drives both job types now, so it is pinned on its own."""

    def test_a_permanent_error_stops_immediately(self, settings: Settings):
        decision = decide_retry(ParseError("broken"), failed_attempts=1, settings=settings)
        assert decision.verdict is RetryVerdict.PERMANENT
        assert decision.outcome.should_retry is False

    def test_a_resume_with_no_text_is_permanent(self, settings: Settings):
        """Asking a model about an empty document spends a call to be told nothing."""
        decision = decide_retry(NotScreenable("no text"), failed_attempts=1, settings=settings)
        assert decision.verdict is RetryVerdict.PERMANENT

    def test_a_missing_key_is_permanent(self, settings: Settings):
        decision = decide_retry(LLMConfigError("no key"), failed_attempts=1, settings=settings)
        assert decision.verdict is RetryVerdict.PERMANENT

    @pytest.mark.parametrize(("failures", "delay"), [(1, 5.0), (2, 10.0)])
    def test_a_transient_error_backs_off_exponentially(
        self, settings: Settings, failures: int, delay: float
    ):
        decision = decide_retry(
            LLMUnavailableError("down"), failed_attempts=failures, settings=settings
        )
        assert decision.verdict is RetryVerdict.RETRY
        assert decision.outcome.retry_after_seconds == delay

    def test_the_budget_runs_out(self, settings: Settings):
        decision = decide_retry(
            LLMUnavailableError("down"),
            failed_attempts=settings.job_max_attempts,
            settings=settings,
        )
        assert decision.verdict is RetryVerdict.EXHAUSTED
        assert decision.outcome.should_retry is False

    def test_an_unrecognised_failure_is_retried_rather_than_written_off(self, settings: Settings):
        decision = decide_retry(RuntimeError("who knows"), failed_attempts=1, settings=settings)
        assert decision.verdict is RetryVerdict.RETRY

    def test_a_reason_never_quotes_an_unfamiliar_error(self, settings: Settings):
        """A DBAPIError's message embeds statement parameters — resume text included."""
        secret = "Somchai Jaidee, born 1994"
        decision = decide_retry(RuntimeError(secret), failed_attempts=1, settings=settings)
        assert secret not in decision.reason
        assert "RuntimeError" in decision.reason


class TestRequestingAScreening:
    async def test_creating_one_queues_the_work_and_answers_202(
        self, authed_client: AsyncClient, queue: RecordingQueue, context: JobContext
    ):
        job_id, resume_id = await _job_and_resume(authed_client, context)
        response = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )

        assert response.status_code == 202, response.text
        assert response.json()["status"] == "pending"
        assert len(queue.screenings) == 1

    async def test_asking_twice_before_it_runs_does_not_queue_twice(
        self, authed_client: AsyncClient, queue: RecordingQueue, context: JobContext
    ):
        job_id, resume_id = await _job_and_resume(authed_client, context)
        body = {"resume_id": resume_id}
        first = await authed_client.post(f"/jobs/{job_id}/screenings", json=body)
        second = await authed_client.post(f"/jobs/{job_id}/screenings", json=body)

        assert first.json()["id"] == second.json()["id"]
        # Still pending, so re-queueing it is right — but it is the same row.
        assert {item[0] for item in queue.screenings} == {uuid.UUID(first.json()["id"])}

    async def test_asking_again_for_a_current_result_spends_nothing(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
    ):
        """The idempotence that matters: a screening costs a model call."""
        job_id, resume_id = await _job_and_resume(authed_client, context)
        body = {"resume_id": resume_id}
        created = await authed_client.post(f"/jobs/{job_id}/screenings", json=body)
        await run_screening_job(context, uuid.UUID(created.json()["id"]))

        queue.screenings.clear()
        again = await authed_client.post(f"/jobs/{job_id}/screenings", json=body)

        assert again.status_code == 200, "200, not 202 — nothing was queued"
        assert again.json()["status"] == "completed"
        assert queue.screenings == []

    async def test_editing_a_requirement_makes_the_result_stale_and_re_queues(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
    ):
        job_id, resume_id = await _job_and_resume(authed_client, context)
        body = {"resume_id": resume_id}
        created = await authed_client.post(f"/jobs/{job_id}/screenings", json=body)
        await run_screening_job(context, uuid.UUID(created.json()["id"]))

        job = (await authed_client.get(f"/jobs/{job_id}")).json()
        requirement_id = job["requirements"][0]["id"]
        patched = await authed_client.patch(
            f"/jobs/{job_id}/requirements/{requirement_id}", json={"label": "Python 3.12"}
        )
        assert patched.status_code == 200, patched.text

        queue.screenings.clear()
        again = await authed_client.post(f"/jobs/{job_id}/screenings", json=body)

        assert again.status_code == 202
        assert len(queue.screenings) == 1

    async def test_changing_only_a_weight_does_not_re_queue(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
    ):
        """The other half of the fingerprint decision, end to end: a weight is
        ranking's input, so the verdicts it produced are still correct."""
        job_id, resume_id = await _job_and_resume(authed_client, context)
        body = {"resume_id": resume_id}
        created = await authed_client.post(f"/jobs/{job_id}/screenings", json=body)
        await run_screening_job(context, uuid.UUID(created.json()["id"]))

        job = (await authed_client.get(f"/jobs/{job_id}")).json()
        requirement_id = job["requirements"][0]["id"]
        await authed_client.patch(
            f"/jobs/{job_id}/requirements/{requirement_id}", json={"weight": 9.0}
        )

        queue.screenings.clear()
        again = await authed_client.post(f"/jobs/{job_id}/screenings", json=body)

        assert again.status_code == 200
        assert again.json()["is_stale"] is False
        assert queue.screenings == []

    async def test_a_stale_result_says_so_before_it_is_re_run(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
    ):
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        screening_id = created.json()["id"]
        await run_screening_job(context, uuid.UUID(screening_id))

        job = (await authed_client.get(f"/jobs/{job_id}")).json()
        await authed_client.delete(f"/jobs/{job_id}/requirements/{job['requirements'][0]['id']}")

        detail = await authed_client.get(f"/screenings/{screening_id}")
        assert detail.json()["screening"]["is_stale"] is True


class TestOwnership:
    async def test_another_candidates_job_is_not_found(
        self, client: AsyncClient, context: JobContext
    ):
        owner = await client.post(
            "/auth/register", json={"email": "owner@example.com", "password": "a-good-password"}
        )
        client.headers["Authorization"] = f"Bearer {owner.json()['access_token']}"
        job_id, _ = await _job_and_resume(client, context)

        intruder = await client.post(
            "/auth/register", json={"email": "other@example.com", "password": "a-good-password"}
        )
        client.headers["Authorization"] = f"Bearer {intruder.json()['access_token']}"
        their = await client.post("/resumes", files=resume_upload())

        response = await client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": their.json()["id"]}
        )
        assert response.status_code == 404

    async def test_another_candidates_resume_is_not_found(self, client: AsyncClient):
        stranger = await client.post(
            "/auth/register", json={"email": "stranger@example.com", "password": "a-good-password"}
        )
        client.headers["Authorization"] = f"Bearer {stranger.json()['access_token']}"
        theirs = await client.post("/resumes", files=resume_upload())
        their_resume_id = theirs.json()["id"]

        mine = await client.post(
            "/auth/register", json={"email": "mine@example.com", "password": "a-good-password"}
        )
        client.headers["Authorization"] = f"Bearer {mine.json()['access_token']}"
        job = await client.post("/jobs", json=JOB_PAYLOAD)

        response = await client.post(
            f"/jobs/{job.json()['id']}/screenings", json={"resume_id": their_resume_id}
        )
        assert response.status_code == 404

    async def test_reading_someone_elses_screening_is_not_found(
        self, client: AsyncClient, context: JobContext
    ):
        owner = await client.post(
            "/auth/register", json={"email": "owner2@example.com", "password": "a-good-password"}
        )
        client.headers["Authorization"] = f"Bearer {owner.json()['access_token']}"
        job_id, resume_id = await _job_and_resume(client, context)
        created = await client.post(f"/jobs/{job_id}/screenings", json={"resume_id": resume_id})
        screening_id = created.json()["id"]

        intruder = await client.post(
            "/auth/register", json={"email": "other2@example.com", "password": "a-good-password"}
        )
        client.headers["Authorization"] = f"Bearer {intruder.json()['access_token']}"

        assert (await client.get(f"/screenings/{screening_id}")).status_code == 404
        assert (await client.post(f"/screenings/{screening_id}/retry")).status_code == 404


class TestTheJob:
    async def test_a_completed_screening_carries_verdicts_and_citations(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
    ):
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        await run_screening_job(context, uuid.UUID(created.json()["id"]))

        detail = (await authed_client.get(f"/screenings/{created.json()['id']}")).json()
        judgment = detail["judgment"]

        assert detail["screening"]["status"] == "completed"
        verdicts = {item["label"]: item["verdict"] for item in judgment["requirements"]}
        assert verdicts["Python"] == Verdict.MET
        assert verdicts["Kubernetes"] == Verdict.NOT_EVIDENCED

    async def test_every_citation_indexes_into_the_returned_document_text(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
    ):
        """The contract the highlighting UI depends on, for judging this time."""
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        await run_screening_job(context, uuid.UUID(created.json()["id"]))

        detail = (await authed_client.get(f"/screenings/{created.json()['id']}")).json()
        text = detail["document_text"]
        assert text

        references = [
            reference
            for item in detail["judgment"]["requirements"]
            for reference in item["evidence"]
        ]
        assert references
        for reference in references:
            assert text[reference["char_start"] : reference["char_end"]] == reference["quote"]

    async def test_the_stats_are_lifted_onto_the_row(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """Cost and hallucination queries should be plain SQL, not a JSON walk."""
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        screening_id = uuid.UUID(created.json()["id"])
        await run_screening_job(context, screening_id)

        async with sessionmaker_for_tests() as session:
            screening = (
                await session.execute(select(Screening).where(Screening.id == screening_id))
            ).scalar_one()

            assert screening.requirements_total == 3
            assert screening.requirements_met == 2
            assert screening.claims_dropped == 0
            assert screening.hallucination_rate == 0.0
            assert screening.requirements_hash
            assert screening.prompt_version == JUDGMENT_PROMPT_VERSION

    async def test_the_calls_are_billed_to_the_screening_not_the_resume(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """Hanging a judging call off the resume would make "what did extracting
        this document cost" wrong, and leaving it off would make every cost figure
        quietly incomplete."""
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        screening_id = uuid.UUID(created.json()["id"])
        await run_screening_job(context, screening_id)

        async with sessionmaker_for_tests() as session:
            logs = (
                (
                    await session.execute(
                        select(LLMCallLog).where(LLMCallLog.screening_id == screening_id)
                    )
                )
                .scalars()
                .all()
            )

            assert logs
            for log in logs:
                assert log.resume_id is None
                # The judging prompt, not the extraction one — otherwise comparing
                # prompt revisions in the cost table is meaningless.
                assert log.prompt_version == JUDGMENT_PROMPT_VERSION

    async def test_a_resume_with_no_text_fails_permanently_with_a_usable_reason(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        job_id, resume_id = await _job_and_resume(authed_client, context)
        async with sessionmaker_for_tests() as session:
            resume = (
                await session.execute(select(Resume).where(Resume.id == uuid.UUID(resume_id)))
            ).scalar_one()
            resume.document_text = None
            await session.commit()

        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        outcome = await run_screening_job(context, uuid.UUID(created.json()["id"]))

        assert outcome.should_retry is False, "no retry can give a document text"
        body = (await authed_client.get(f"/screenings/{created.json()['id']}")).json()
        assert body["screening"]["status"] == "failed"
        assert "Process the resume first" in body["screening"]["failure_reason"]

    async def test_a_completed_screening_is_re_judged_rather_than_skipped(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        """The one place a screening job deliberately differs from a resume job.

        `run_resume_job` skips an `extracted` resume, because redoing it would bill
        a second call for a profile we already have. A completed screening is not
        skipped: its requirements can change, and re-running it against the new ones
        is the whole point. What stops the waste is one layer up — `request_screening`
        only queues the work when the fingerprint moved.
        """
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        screening_id = uuid.UUID(created.json()["id"])

        async def call_count() -> int:
            async with sessionmaker_for_tests() as session:
                logs = (
                    (
                        await session.execute(
                            select(LLMCallLog).where(LLMCallLog.screening_id == screening_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                return len(logs)

        await run_screening_job(context, screening_id)
        after_one = await call_count()
        assert after_one >= 1

        await run_screening_job(context, screening_id)
        assert await call_count() > after_one, "the job itself does not refuse to re-run"

        async with sessionmaker_for_tests() as session:
            screening = (
                await session.execute(select(Screening).where(Screening.id == screening_id))
            ).scalar_one()
            assert screening.status is ScreeningStatus.COMPLETED
            assert screening.attempts == 2

    async def test_a_screening_deleted_before_pickup_is_not_an_error(self, context: JobContext):
        await run_screening_job(context, uuid.uuid4())


class TestFailureAndReplay:
    @pytest.fixture
    def fake_mode(self) -> FakeMode:
        return FakeMode.UNAVAILABLE

    async def test_a_downed_provider_retries_then_dead_letters(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        settings: Settings,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        # `_job_and_resume` parsed it: extraction failed against the downed provider,
        # but the text was committed before that — which is exactly the state a
        # screening meets in production after a provider outage.
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        screening_id = uuid.UUID(created.json()["id"])

        delays = []
        for _ in range(settings.job_max_attempts):
            outcome = await run_screening_job(context, screening_id)
            delays.append(outcome.retry_after_seconds)

        assert delays[:-1] == [5.0, 10.0]
        assert delays[-1] is None, "the last attempt gives up rather than asking again"

        body = (await authed_client.get(f"/screenings/{screening_id}")).json()["screening"]
        assert body["status"] == "dead_lettered"
        assert body["can_retry"] is True
        assert "Gave up after" in body["failure_reason"]

    async def test_a_dead_letter_can_be_replayed(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
        settings: Settings,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    ):
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        screening_id = created.json()["id"]
        for _ in range(settings.job_max_attempts):
            await run_screening_job(context, uuid.UUID(screening_id))

        queue.screenings.clear()
        replay = await authed_client.post(f"/screenings/{screening_id}/retry")

        assert replay.status_code == 200, replay.text
        assert len(queue.screenings) == 1, "the replay has to actually queue work"
        async with sessionmaker_for_tests() as session:
            screening = (
                await session.execute(
                    select(Screening).where(Screening.id == uuid.UUID(screening_id))
                )
            ).scalar_one()
            assert screening.status is ScreeningStatus.PENDING
            assert screening.failed_attempts == 0, "the budget resets, the total does not"
            assert screening.attempts == settings.job_max_attempts


class TestRetryRefusals:
    async def test_a_completed_screening_refuses_a_retry(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
    ):
        """Re-running a current result would bill a call to reproduce it."""
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        await run_screening_job(context, uuid.UUID(created.json()["id"]))

        response = await authed_client.post(f"/screenings/{created.json()['id']}/retry")
        assert response.status_code == 409

    async def test_a_pending_screening_refuses_a_retry(
        self, authed_client: AsyncClient, queue: RecordingQueue, context: JobContext
    ):
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        response = await authed_client.post(f"/screenings/{created.json()['id']}/retry")
        assert response.status_code == 409


class TestListing:
    async def test_a_jobs_screenings_come_back_with_their_counts(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
    ):
        job_id, resume_id = await _job_and_resume(authed_client, context)
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        await run_screening_job(context, uuid.UUID(created.json()["id"]))

        listed = await authed_client.get(f"/jobs/{job_id}/screenings")
        assert listed.status_code == 200
        body = listed.json()
        assert len(body) == 1
        assert body[0]["requirements_met"] == 2
        assert body[0]["requirements_total"] == 3
        assert body[0]["is_stale"] is False

    async def test_a_job_with_no_screenings_lists_an_empty_list(self, authed_client: AsyncClient):
        """The empty case, on purpose."""
        job = await authed_client.post("/jobs", json=JOB_PAYLOAD)
        listed = await authed_client.get(f"/jobs/{job.json()['id']}/screenings")
        assert listed.status_code == 200
        assert listed.json() == []


class TestAJobWithNoRequirements:
    async def test_screening_against_nothing_completes_without_a_model_call(
        self,
        authed_client: AsyncClient,
        queue: RecordingQueue,
        context: JobContext,
    ):
        """The empty case again, one layer up: `judge_requirements` returns early,
        so this must reach `completed` rather than failing or hanging."""
        job_id, resume_id = await _job_and_resume(authed_client, context, requirements=[])
        created = await authed_client.post(
            f"/jobs/{job_id}/screenings", json={"resume_id": resume_id}
        )
        await run_screening_job(context, uuid.UUID(created.json()["id"]))

        body = (await authed_client.get(f"/screenings/{created.json()['id']}")).json()
        assert body["screening"]["status"] == "completed"
        assert body["screening"]["requirements_total"] == 0
        assert body["judgment"]["requirements"] == []
