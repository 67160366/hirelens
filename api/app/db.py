"""Async engine and session wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return build_engine(settings)


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        # Verify a connection before handing it out: a container restart otherwise
        # surfaces as a stale-connection error on the next request.
        pool_pre_ping=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return build_sessionmaker(get_engine())


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        # Committed ORM objects stay usable after the request's session closes,
        # which is what lets a handler return them directly.
        autoflush=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error."""
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
