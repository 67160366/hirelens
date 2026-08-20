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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_candidate, get_extractor, get_queue, get_storage
from app.config import Settings, get_settings
from app.db import enforce_foreign_keys, get_session
from app.jobs import JobContext
from app.llm.fake import FakeExtractor, FakeMode
from app.main import create_app
from app.models import Base, Candidate, Role
from app.pipeline.retrieval import build_retriever
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
    # The same pragma `build_engine` applies. Without it SQLite ignores every
    # `ON DELETE` clause, so a cascade that works on Postgres would silently do
    # nothing here — and the suite, which runs only here, could not tell.
    enforce_foreign_keys(engine)

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
    # Lexical, which is the default and needs no server — retrieval must not become
    # a reason the suite wants one.
    app.state.retriever = build_retriever(settings)
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


async def register_as(client: AsyncClient, *, email: str, role: str = "candidate") -> AsyncClient:
    """Register an account, put its token on the client, and hand the client back.

    `role` is a registration field because there is no other way to become a
    recruiter — see `SelfServiceRole` in `app/api/routes/auth.py` for why that is a
    recorded limitation rather than a claim that employers need no verification.
    """
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "correct horse battery", "role": role},
    )
    assert response.status_code == 201, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


async def set_role(sessionmaker: async_sessionmaker[AsyncSession], email: str, role: Role) -> None:
    """Change an account's role out of band, the way an operator would.

    There is no endpoint for this on purpose — `admin` in particular is not
    self-selectable (`SelfServiceRole`), so a SQL statement is how it is granted. It
    lives here rather than in one test module because four of them now need it.
    """
    async with sessionmaker() as session:
        account = (
            await session.execute(select(Candidate).where(Candidate.email == email))
        ).scalar_one()
        account.role = role
        await session.commit()


async def publish_job(client: AsyncClient, *, job_id: str, as_email: str) -> None:
    """Put a posting on the public site, which takes an admin and nothing less.

    Promotes whichever account the client is currently signed in as, publishes, and
    puts that account's role back. The round trip is the point rather than an
    inconvenience: a helper that could publish without it would be exercising a
    system where anyone who registers can publish, which is exactly what
    `app/publication.py` exists to prevent. It promotes the **caller** rather than the
    owner because that is what really happens — an administrator publishes somebody
    else's posting, and publishing requires no ownership at all.

    The sessionmaker comes off the client rather than through a fixture parameter.
    `client` already carries its app and the app already carries the factory, so
    reaching it here keeps ~a dozen call sites from having to grow an argument that
    is not about what they are testing.
    """
    sessionmaker = client.app.state.sessionmaker  # type: ignore[attr-defined]
    previous = await _role_of(sessionmaker, as_email)
    await set_role(sessionmaker, as_email, Role.ADMIN)
    response = await client.post(f"/jobs/{job_id}/publication", json={"status": "published"})
    assert response.status_code == 200, response.text
    await set_role(sessionmaker, as_email, previous)


async def _role_of(sessionmaker: async_sessionmaker[AsyncSession], email: str) -> Role:
    async with sessionmaker() as session:
        account = (
            await session.execute(select(Candidate).where(Candidate.email == email))
        ).scalar_one()
        return account.role


@pytest.fixture
async def authed_client(client: AsyncClient) -> AsyncClient:
    """A client carrying a bearer token for a freshly registered **candidate**.

    The default role, because most of the suite is the candidate journey. A module
    about the recruiter side overrides this fixture with `recruiter_client` — see
    `tests/test_jobs.py` — which keeps every test body unchanged.
    """
    return await register_as(client, email="candidate@example.com")


@pytest.fixture
async def recruiter_client(client: AsyncClient) -> AsyncClient:
    """The same, for an account that may author job postings."""
    return await register_as(client, email="recruiter@example.com", role="recruiter")


CONSENT = {"consent": "true"}
"""The form field every upload needs since M4 slice 4. Spelled out for the few
tests that hand-build a payload to aim at the file gates — without it they stop
at schema validation with a 422 and never reach the gate they are named for."""

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def resume_upload(name: str = "resume_en.pdf", *, consent: bool = True) -> dict[str, Any]:
    """A whole multipart upload for one of the fixtures — spread it with `**`.

    Returns `files` *and* `data` rather than just the file, because since M4 slice 4
    an upload without `consent` is a 422. Spreading keeps the consent field out of
    sixty-eight call sites that are not about consent, while
    `resume_upload(consent=False)` still lets `tests/test_pdpa.py` aim at it.

    The content type follows the extension. The upload gate does not read it — it
    trusts the magic bytes instead — but a test that announced every file as a PDF
    would misdescribe what a browser actually sends.
    """
    data = (FIXTURES / name).read_bytes()
    suffix = Path(name).suffix.lower()
    return {
        "files": {"file": (name, data, CONTENT_TYPES.get(suffix, "application/octet-stream"))},
        "data": {"consent": "true" if consent else "false"},
    }


async def upload_and_read(client: AsyncClient, name: str = "resume_en.pdf") -> dict[str, Any]:
    """Upload a fixture and read the result back.

    The client contract since processing moved off the request: upload accepts the
    file and answers `pending`, and the outcome is read from `GET /resumes/{id}`.
    No polling is needed here because the tests run on the inline queue.
    """
    uploaded = await client.post("/resumes", **resume_upload(name))
    assert uploaded.status_code in (200, 201), uploaded.text
    response = await client.get(f"/resumes/{uploaded.json()['id']}")
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


__all__ = [
    "CONSENT",
    "get_current_candidate",
    "publish_job",
    "resume_upload",
    "set_role",
    "upload_and_read",
]
