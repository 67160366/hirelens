"""Shared test fixtures.

The API tests run against in-memory SQLite and the fake extraction backend, so the
suite needs neither Postgres nor an API key. `JSON_VARIANT` in the models is what
makes that work — the same tables render on both dialects.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_candidate, get_extractor, get_queue, get_storage
from app.config import Settings, get_settings
from app.db import get_session
from app.jobs import JobContext
from app.llm.fake import FakeExtractor, FakeMode
from app.main import create_app
from app.models import Base
from app.queue import InlineQueue, JobQueue
from app.storage import LocalStorage

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # _env_file=None keeps the suite hermetic: whatever provider or key the
    # developer's .env selects must not change what the tests exercise.
    return Settings(
        _env_file=None,
        jwt_secret="test-secret-not-used-anywhere-real",
        storage_dir=tmp_path / "uploads",
        extraction_max_attempts=2,
    )


@pytest.fixture
async def sessionmaker_for_tests() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A fresh in-memory database per test.

    StaticPool keeps every session on the same connection; without it each session
    would get its own blank `:memory:` database.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    await engine.dispose()


@pytest.fixture
def fake_mode() -> FakeMode:
    """Override in a test to change how the stand-in model behaves."""
    return FakeMode.FAITHFUL


@pytest.fixture
def queue(
    settings: Settings,
    sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    fake_mode: FakeMode,
) -> JobQueue:
    """The inline queue, so most tests see an upload through to a profile.

    Override this with `RecordingQueue` (see `test_worker.py`) to test the
    asynchronous path, where upload returns `pending` and a worker does the work.
    """
    return InlineQueue(
        JobContext(
            sessionmaker=sessionmaker_for_tests,
            storage=LocalStorage(settings.storage_path),
            extractor=FakeExtractor(fake_mode),
            settings=settings,
        )
    )


@pytest.fixture
async def client(
    settings: Settings,
    sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    fake_mode: FakeMode,
    queue: JobQueue,
) -> AsyncIterator[AsyncClient]:
    app = create_app()
    storage = LocalStorage(settings.storage_path)
    extractor = FakeExtractor(fake_mode)

    # Lifespan is skipped, so app.state is populated directly.
    app.state.settings = settings
    app.state.storage = storage
    app.state.extractor = extractor
    app.state.queue = queue
    # The progress stream opens its own sessions, so it needs the factory rather
    # than the `get_session` override below.
    app.state.sessionmaker = sessionmaker_for_tests

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker_for_tests() as session:
            yield session

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_extractor] = lambda: extractor
    app.dependency_overrides[get_queue] = lambda: queue

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        http_client.app = app  # type: ignore[attr-defined]
        yield http_client


@pytest.fixture
async def authed_client(client: AsyncClient) -> AsyncClient:
    """A client carrying a bearer token for a freshly registered candidate."""
    response = await client.post(
        "/auth/register",
        json={"email": "candidate@example.com", "password": "correct horse battery"},
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def resume_upload(name: str = "resume_en.pdf") -> dict[str, tuple[str, bytes, str]]:
    """A multipart payload for one of the fixtures.

    The content type follows the extension. The upload gate does not read it — it
    trusts the magic bytes instead — but a test that announced every file as a PDF
    would misdescribe what a browser actually sends.
    """
    data = (FIXTURES / name).read_bytes()
    suffix = Path(name).suffix.lower()
    return {"file": (name, data, CONTENT_TYPES.get(suffix, "application/octet-stream"))}


async def upload_and_read(client: AsyncClient, name: str = "resume_en.pdf") -> dict[str, Any]:
    """Upload a fixture and read the result back.

    The client contract since processing moved off the request: upload accepts the
    file and answers `pending`, and the outcome is read from `GET /resumes/{id}`.
    No polling is needed here because the tests run on the inline queue.
    """
    uploaded = await client.post("/resumes", files=resume_upload(name))
    assert uploaded.status_code in (200, 201), uploaded.text
    response = await client.get(f"/resumes/{uploaded.json()['id']}")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


__all__ = ["get_current_candidate", "resume_upload", "upload_and_read"]
