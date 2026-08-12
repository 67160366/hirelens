"""The progress stream: what a client watching an upload actually sees.

`GET /resumes/{id}/events` replaced a polling loop, so what matters here is the
thing polling could not do — report each state as it lands, including the ones a
700 ms poll flew past — plus the ways a long-lived connection goes wrong: a
resume that never settles, a row deleted underneath it, and a proxy that drops a
stream which has gone quiet.

Two levels, because httpx's ASGI transport buffers a response until the app is
done with it. The endpoint's wiring is tested over HTTP, where every stream ends
on its own; the *sequence* of frames is tested by driving `_resume_events`
directly. The second is not a workaround for the transport — it is what makes the
sequence a fact instead of a race, since the job runs to completion between two
`anext` calls rather than alongside the stream.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.types import Message

from app.api.routes.resumes import _resume_events
from app.config import Settings
from app.jobs import JobContext, run_resume_job
from app.llm.fake import FakeExtractor, FakeMode
from app.models import Resume, ResumeStatus
from app.storage import LocalStorage
from tests.conftest import resume_upload
from tests.test_worker import RecordingQueue


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """The stream's three timings, in milliseconds rather than seconds.

    Every test in this module waits on one of them, so the defaults would make it
    take minutes.
    """
    return settings.model_copy(
        update={
            "sse_poll_seconds": 0.01,
            "sse_heartbeat_seconds": 0.05,
            "sse_max_stream_seconds": 5.0,
        }
    )


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


def _frames(raw: str) -> list[tuple[str, str]]:
    """Parse the wire format back into pairs, the way a client does.

    Keep-alives come back as `("comment", …)` so a test can assert they were sent;
    a real client discards them.
    """
    parsed: list[tuple[str, str]] = []
    event = ""
    data = ""
    for line in raw.split("\n"):
        if line.startswith(":"):
            parsed.append(("comment", line[1:].strip()))
        elif line == "":
            if event:
                parsed.append((event, data))
            event = data = ""
        elif line.startswith("event:"):
            event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data = line.removeprefix("data:").strip()
    return parsed


def _events(raw: str) -> list[tuple[str, str]]:
    """The frames a client would act on. Heartbeats are transport, not signal."""
    return [frame for frame in _frames(raw) if frame[0] != "comment"]


def _still_connected() -> Request:
    """A request whose client has not hung up.

    `is_disconnected` reads the ASGI channel inside an immediately-cancelled
    scope, so a receive that never returns is exactly what a live connection with
    nothing to say looks like.
    """

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("unreachable: the event is never set")

    return Request({"type": "http", "method": "GET", "path": "/", "headers": []}, receive)


class TestReachingTheStream:
    async def test_it_needs_a_token(self, client: AsyncClient):
        response = await client.get(f"/resumes/{uuid.uuid4()}/events")

        assert response.status_code == 401

    async def test_another_candidates_resume_is_a_404_not_a_stream(
        self, authed_client: AsyncClient
    ):
        """Ownership has to be settled before the response starts. Once a stream is
        open the status line is already 200, and a refusal can only be an event the
        client is trusted to interpret."""
        uploaded = await authed_client.post("/resumes", **resume_upload())
        resume_id = uploaded.json()["id"]
        intruder = await authed_client.post(
            "/auth/register",
            json={"email": "someone.else@example.com", "password": "correct horse battery"},
        )
        authed_client.headers["Authorization"] = f"Bearer {intruder.json()['access_token']}"

        response = await authed_client.get(f"/resumes/{resume_id}/events")

        assert response.status_code == 404


class TestAResumeThatIsAlreadyFinished:
    """On the inline queue the work is done before the upload responds, so this is
    also the no-server path: connect, learn the answer, close."""

    async def test_the_stream_reports_the_result_and_ends(self, authed_client: AsyncClient):
        uploaded = await authed_client.post("/resumes", **resume_upload())

        response = await authed_client.get(f"/resumes/{uploaded.json()['id']}/events")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        events = _events(response.text)
        assert [name for name, _ in events] == ["status", "done"]
        assert json.loads(events[0][1])["status"] == ResumeStatus.EXTRACTED

    async def test_the_stream_carries_the_resume_and_nothing_else(self, authed_client: AsyncClient):
        """The profile and `document_text` stay behind `GET /resumes/{id}`, which
        the client calls once. Frames stay small, and resume text is not repeated
        down a connection that stays open."""
        uploaded = await authed_client.post("/resumes", **resume_upload())

        response = await authed_client.get(f"/resumes/{uploaded.json()['id']}/events")

        streamed = json.loads(_events(response.text)[0][1])
        listed = (await authed_client.get("/resumes")).json()[0]
        assert streamed == listed
        assert "document_text" not in streamed
        assert "profile" not in streamed


class TestFollowingAResumeThroughTheWork:
    @pytest.fixture
    def queue(self) -> RecordingQueue:
        """Holds the work back, so the resume is still in flight when the stream
        opens and a test decides when each change happens."""
        return RecordingQueue()

    async def test_every_change_reaches_the_client(
        self,
        authed_client: AsyncClient,
        context: JobContext,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
    ):
        uploaded = await authed_client.post("/resumes", **resume_upload())
        resume_id = uuid.UUID(uploaded.json()["id"])
        stream = _resume_events(sessionmaker_for_tests, settings, _still_connected(), resume_id)

        queued = _frames(await anext(stream))
        await run_resume_job(context, resume_id)
        rest = [frame async for chunk in stream for frame in _frames(chunk)]

        assert [name for name, _ in queued] == ["status"]
        assert json.loads(queued[0][1])["status"] == ResumeStatus.PENDING
        events = [frame for frame in rest if frame[0] != "comment"]
        assert [name for name, _ in events] == ["status", "done"]
        finished = json.loads(events[-1][1])
        assert finished["status"] == ResumeStatus.EXTRACTED
        assert finished["attempts"] == 1

    async def test_a_failed_attempt_streams_the_reason_it_is_still_waiting(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
    ):
        """The state polling was worst at. A retryable failure puts the resume back
        to `pending`, which is where it already was — only `failure_reason` and
        `attempts` moved, and only for as long as the backoff lasts."""
        uploaded = await authed_client.post("/resumes", **resume_upload())
        resume_id = uuid.UUID(uploaded.json()["id"])
        provider_down = JobContext(
            sessionmaker=sessionmaker_for_tests,
            storage=LocalStorage(settings.storage_path),
            extractor=FakeExtractor(FakeMode.UNAVAILABLE),
            settings=settings,
        )
        stream = _resume_events(sessionmaker_for_tests, settings, _still_connected(), resume_id)

        await anext(stream)
        outcome = await run_resume_job(provider_down, resume_id)
        after = _frames(await anext(stream))
        await stream.aclose()

        assert outcome.should_retry
        payload = json.loads(after[0][1])
        assert payload["status"] == ResumeStatus.PENDING
        assert payload["attempts"] == 1
        assert "Attempt 1 failed" in payload["failure_reason"]

    async def test_a_resume_deleted_mid_stream_ends_the_stream(
        self,
        authed_client: AsyncClient,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
    ):
        """Rather than repeating the last state it saw until the cap runs out."""
        uploaded = await authed_client.post("/resumes", **resume_upload())
        resume_id = uuid.UUID(uploaded.json()["id"])
        stream = _resume_events(sessionmaker_for_tests, settings, _still_connected(), resume_id)
        await anext(stream)

        async with sessionmaker_for_tests() as session:
            resume = await session.get(Resume, resume_id)
            assert resume is not None
            await session.delete(resume)
            await session.commit()

        assert _frames(await anext(stream)) == [("gone", "{}")]


class TestAStreamThatWouldOtherwiseNeverEnd:
    @pytest.fixture
    def queue(self) -> RecordingQueue:
        return RecordingQueue()

    @pytest.fixture
    def settings(self, settings: Settings) -> Settings:
        return settings.model_copy(update={"sse_max_stream_seconds": 0.05})

    async def test_it_is_closed_at_the_cap(self, authed_client: AsyncClient):
        """A resume stranded at `processing` by a worker that died is never swept
        back to `pending` (`docs/HANDOFF.md` §7), so without a cap this connection
        would outlive the problem it is reporting. The client falls back to
        polling."""
        uploaded = await authed_client.post("/resumes", **resume_upload())

        response = await authed_client.get(f"/resumes/{uploaded.json()['id']}/events")

        events = _events(response.text)
        assert [name for name, _ in events] == ["status", "timeout"]
        assert json.loads(events[0][1])["status"] == ResumeStatus.PENDING


class TestAStreamWithNothingToSay:
    @pytest.fixture
    def queue(self) -> RecordingQueue:
        return RecordingQueue()

    @pytest.fixture
    def settings(self, settings: Settings) -> Settings:
        return settings.model_copy(update={"sse_max_stream_seconds": 0.3})

    async def test_it_sends_keep_alives_so_a_proxy_does_not_drop_it(
        self, authed_client: AsyncClient
    ):
        """Nothing about a resume changes while it waits out a backoff, and an idle
        connection is what proxies and load balancers close."""
        uploaded = await authed_client.post("/resumes", **resume_upload())

        response = await authed_client.get(f"/resumes/{uploaded.json()['id']}/events")

        assert any(name == "comment" for name, _ in _frames(response.text))
