"""The Postgres half of `JSON_VARIANT`, which the rest of the suite never runs.

Every other test uses in-memory SQLite, where `JSON_VARIANT` renders as plain JSON
and a "JSONB column" is really a TEXT column holding serialized JSON. That keeps
the suite and CI free of a database server, but it means the dialect the project
actually deploys on — JSONB, native uuid, timestamptz — has no coverage at all.

This module fills that gap and is skipped unless `TEST_DATABASE_URL` is set, so
the DB-free property of `pytest -q` is preserved:

    TEST_DATABASE_URL=postgresql+asyncpg://hirelens:hirelens@localhost:5432/hirelens \
        pytest tests/test_postgres.py -q

It creates and drops its own schema, so it must point at a throwaway database.
Create one once with:

    docker compose exec postgres createdb -U hirelens hirelens_test

Pointing it at the development database is refused outright — `drop_all` would
take the dev data with it.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.jobs import JobContext
from app.llm.fake import FakeExtractor, FakeMode
from app.models import Base, Candidate, ExtractedProfileRow, LLMCallLog, Resume, ResumeStatus
from app.models.base import JSON_VARIANT
from app.pipeline.parse import parse_document_bytes
from app.queue import InlineQueue
from app.services import resume_service
from app.storage import LocalStorage
from tests.conftest import FIXTURES

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set TEST_DATABASE_URL to a throwaway Postgres database to run these.",
)


def _throwaway_database_url() -> str:
    """The test URL, refused if it is the developer's own database.

    These tests drop every table before and after each one. Reading the real
    `.env` here is deliberate — this is the one place in the suite that must not
    be hermetic, because the value it guards against lives there.
    """
    if get_settings().database_url == TEST_DATABASE_URL:
        pytest.fail(
            "TEST_DATABASE_URL points at the database DATABASE_URL uses. These "
            "tests drop every table; use a throwaway database instead "
            "(docker compose exec postgres createdb -U hirelens hirelens_test)."
        )
    return TEST_DATABASE_URL


@pytest.fixture
async def pg_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A freshly created schema per test, dropped afterwards."""
    engine = create_async_engine(_throwaway_database_url())
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _inline_queue(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> InlineQueue:
    """Run the job in-process, so one call covers ingest and extraction."""
    return InlineQueue(
        JobContext(
            sessionmaker=sessionmaker,
            storage=LocalStorage(settings.storage_path),
            extractor=FakeExtractor(FakeMode.FAITHFUL),
            settings=settings,
        )
    )


def _every_evidence(profile: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every evidence reference in a stored profile, whatever field it hangs off."""
    for field in ("full_name", "headline", "years_experience"):
        claim = profile.get(field)
        if claim is not None:
            yield claim["evidence"]
    if profile.get("seniority_evidence") is not None:
        yield profile["seniority_evidence"]
    for group in ("skills", "experiences", "education"):
        for item in profile[group]:
            yield item["evidence"]


def test_json_variant_compiles_to_jsonb() -> None:
    """The reason this module exists: on SQLite this assertion cannot be made."""
    assert JSON_VARIANT.compile(dialect=postgresql.dialect()) == "JSONB"


class TestProfileRoundTrip:
    """A stored profile must come back byte-identical, Thai text included.

    asyncpg, JSONB normalization and the client encoding all sit between
    `model_dump(mode="json")` and what a later request serves. Evidence offsets
    index into `document_text`, so any of them mangling a character would shift
    citations that were verified as correct at extraction time.
    """

    async def test_real_ingest_persists_and_reloads_intact(
        self,
        pg_sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        data = (FIXTURES / "resume_th.pdf").read_bytes()
        # What the parser produced, computed here rather than read back, so the
        # comparison below is against the pipeline's output and not against
        # Postgres agreeing with itself.
        expected_text = parse_document_bytes(data, filename="resume_th.pdf").text

        async with pg_sessionmaker() as session:
            candidate = Candidate(email="postgres@example.com")
            session.add(candidate)
            await session.commit()

            result = await resume_service.ingest_resume(
                session,
                candidate=candidate,
                filename="resume_th.pdf",
                data=data,
                storage=LocalStorage(settings.storage_path),
                queue=_inline_queue(pg_sessionmaker, settings),
            )
            assert result.created
            resume_id = result.resume.id

        # A separate session, so this reads what Postgres stored rather than what
        # the identity map still holds.
        async with pg_sessionmaker() as session:
            resume = (
                await session.execute(select(Resume).where(Resume.id == resume_id))
            ).scalar_one()
            row = (
                await session.execute(
                    select(ExtractedProfileRow).where(ExtractedProfileRow.resume_id == resume_id)
                )
            ).scalar_one()

            assert resume.status is ResumeStatus.EXTRACTED
            assert resume.document_text == expected_text

            # The fixture is Thai. Mangled encoding or any normalization in the
            # JSONB round trip would shift these offsets off their quotes, which
            # is the failure mode that would break citations already shown to a
            # user — so check every claim, not a sample.
            for span in _every_evidence(row.profile):
                text = resume.document_text
                assert text is not None
                assert text[span["char_start"] : span["char_end"]] == span["quote"]

            # JSON list column on a native-JSONB dialect: a list, not a string.
            assert isinstance(resume.pages_without_text, list)

            # The usage log is written in the same transaction as the profile.
            logs = (
                (await session.execute(select(LLMCallLog).where(LLMCallLog.resume_id == resume_id)))
                .scalars()
                .all()
            )
            assert len(logs) >= 1

    async def test_jsonb_operators_query_inside_the_document(
        self,
        pg_sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        """Querying into the JSON column is why it is JSONB and not TEXT.

        M3 ranks candidates from requirement-level results, which means reaching
        into the stored profile from SQL. This pins that it works.
        """
        data = (FIXTURES / "resume_en.pdf").read_bytes()

        async with pg_sessionmaker() as session:
            candidate = Candidate(email="jsonb@example.com")
            session.add(candidate)
            await session.commit()

            result = await resume_service.ingest_resume(
                session,
                candidate=candidate,
                filename="resume_en.pdf",
                data=data,
                storage=LocalStorage(settings.storage_path),
                queue=_inline_queue(pg_sessionmaker, settings),
            )
            verified = (
                await session.execute(
                    select(ExtractedProfileRow.claims_verified).where(
                        ExtractedProfileRow.resume_id == result.resume.id
                    )
                )
            ).scalar_one()
            assert verified > 0

        async with pg_sessionmaker() as session:
            # The lifted-out counter column and the same number read from inside
            # the JSON document must agree — the invariant `_record_profile` keeps.
            from_json = (
                await session.execute(
                    select(ExtractedProfileRow.profile["stats"]["verified"].as_integer())
                )
            ).scalar_one()
            assert from_json == verified
