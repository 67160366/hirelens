"""Shared test fixtures.

The API tests run against in-memory SQLite and the fake extraction backend, so the
suite needs neither Postgres nor an API key. `JSON_VARIANT` in the models is what
makes that work — the same tables render on both dialects.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_candidate, get_extractor, get_storage
from app.config import Settings, get_settings
from app.db import get_session
from app.llm.fake import FakeExtractor, FakeMode
from app.main import create_app
from app.models import Base
from app.storage import LocalStorage

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
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
async def client(
    settings: Settings,
    sessionmaker_for_tests: async_sessionmaker[AsyncSession],
    fake_mode: FakeMode,
) -> AsyncIterator[AsyncClient]:
    app = create_app()
    storage = LocalStorage(settings.storage_path)
    extractor = FakeExtractor(fake_mode)

    # Lifespan is skipped, so app.state is populated directly.
    app.state.settings = settings
    app.state.storage = storage
    app.state.extractor = extractor

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker_for_tests() as session:
            yield session

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_extractor] = lambda: extractor

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


def resume_upload(name: str = "resume_en.pdf") -> dict[str, tuple[str, bytes, str]]:
    """A multipart payload for one of the PDF fixtures."""
    data = (FIXTURES / name).read_bytes()
    return {"file": (name, data, "application/pdf")}


__all__ = ["get_current_candidate", "resume_upload"]
