"""Service-level hardening: the duplicate-upload race, blob cleanup, and logging."""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.llm.fake import FakeExtractor, FakeMode
from app.models import Candidate, Resume
from app.services import resume_service
from app.storage import LocalStorage, build_storage_key, content_hash
from tests.conftest import FIXTURES


@pytest.fixture
def storage(settings: Settings) -> LocalStorage:
    return LocalStorage(settings.storage_path)


@pytest.fixture
def extractor() -> FakeExtractor:
    return FakeExtractor(FakeMode.FAITHFUL)


async def _make_candidate(session: AsyncSession) -> Candidate:
    candidate = Candidate(email="service@example.com")
    session.add(candidate)
    await session.commit()
    return candidate


class TestDuplicateUploadRace:
    async def test_losing_the_race_returns_the_winner(
        self,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
        storage: LocalStorage,
        extractor: FakeExtractor,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Two identical uploads race: both pass the pre-insert lookup, the loser's
        INSERT hits the unique constraint and must resolve to the winner's row."""
        data = (FIXTURES / "resume_en.pdf").read_bytes()

        async with sessionmaker_for_tests() as session:
            candidate = await _make_candidate(session)
            winner = await resume_service.ingest_resume(
                session,
                candidate=candidate,
                filename="resume_en.pdf",
                data=data,
                storage=storage,
                extractor=extractor,
                settings=settings,
            )
            assert winner.created

        # Simulate the loser's view of the race: its pre-insert lookup ran before
        # the winner committed, so the first call sees nothing.
        real_lookup = resume_service.find_by_content
        calls = 0

        async def lookup_missing_once(
            session: AsyncSession, *, candidate_id: uuid.UUID, digest: str
        ) -> Resume | None:
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            return await real_lookup(session, candidate_id=candidate_id, digest=digest)

        monkeypatch.setattr(resume_service, "find_by_content", lookup_missing_once)

        async with sessionmaker_for_tests() as session:
            result = await resume_service.ingest_resume(
                session,
                candidate=candidate,
                filename="resume_en.pdf",
                data=data,
                storage=storage,
                extractor=extractor,
                settings=settings,
            )

        assert not result.created
        assert result.resume.id == winner.resume.id


class TestFailedIngestCleanup:
    async def test_a_crash_after_storing_removes_the_blob(
        self,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
        storage: LocalStorage,
        extractor: FakeExtractor,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """If the row rolls back, the object written before it must not survive."""
        data = (FIXTURES / "resume_en.pdf").read_bytes()

        async def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated crash mid-ingest")

        monkeypatch.setattr(resume_service, "process_resume", boom)

        async with sessionmaker_for_tests() as session:
            candidate = await _make_candidate(session)
            # Captured before the crash: the rollback expires the instance.
            candidate_id = candidate.id
            with pytest.raises(RuntimeError, match="simulated crash"):
                await resume_service.ingest_resume(
                    session,
                    candidate=candidate,
                    filename="resume_en.pdf",
                    data=data,
                    storage=storage,
                    extractor=extractor,
                    settings=settings,
                )

        digest = content_hash(data)
        key = build_storage_key(
            candidate_id=str(candidate_id), digest=digest, filename="resume_en.pdf"
        )
        assert not await storage.exists(key)

        async with sessionmaker_for_tests() as session:
            leftover = await resume_service.find_by_content(
                session, candidate_id=candidate_id, digest=digest
            )
            assert leftover is None


class TestLogging:
    async def test_ingest_logs_outcomes_but_never_document_text(
        self,
        sessionmaker_for_tests: async_sessionmaker[AsyncSession],
        settings: Settings,
        storage: LocalStorage,
        extractor: FakeExtractor,
        caplog: pytest.LogCaptureFixture,
    ):
        """Resumes are PII: ids and counters may be logged, the content may not."""
        caplog.set_level(logging.INFO, logger="app.services.resume_service")
        data = (FIXTURES / "resume_en.pdf").read_bytes()

        async with sessionmaker_for_tests() as session:
            candidate = await _make_candidate(session)
            await resume_service.ingest_resume(
                session,
                candidate=candidate,
                filename="resume_en.pdf",
                data=data,
                storage=storage,
                extractor=extractor,
                settings=settings,
            )

        assert "extracted" in caplog.text
        # The fixture's name appears throughout the document; none of it may leak.
        assert "Somchai" not in caplog.text
