"""Async engine and session wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from sqlalchemy import event
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
    engine = create_async_engine(
        settings.database_url,
        # Verify a connection before handing it out: a container restart otherwise
        # surfaces as a stale-connection error on the next request.
        pool_pre_ping=True,
    )
    enforce_foreign_keys(engine)
    return engine


def enforce_foreign_keys(engine: AsyncEngine) -> None:
    """Make SQLite honour foreign keys, which it ignores by default.

    Without this, `ON DELETE CASCADE` and `ON DELETE SET NULL` are inert on SQLite
    and enforced on Postgres — so deleting an account would clear its rows in
    production and leave them behind in dev, and **the entire test suite would be
    blind to the difference**, because it runs on SQLite. That is the same class of
    gap as SQLite happily storing the NUL that Postgres refused (`docs/HANDOFF.md`
    §11), and it was found the same way: by writing the test that needed the
    behaviour and watching it fail for the wrong reason.

    A no-op on Postgres, which has never needed asking.
    """
    if not engine.dialect.name.startswith("sqlite"):
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


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
