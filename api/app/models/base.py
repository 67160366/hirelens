"""Declarative base and column conventions.

`JSON_VARIANT` renders as JSONB on Postgres (the deployment target) and plain JSON
on SQLite (the test database), so the same models run in both without a
Postgres-only test dependency.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, MetaData, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")

# Explicit constraint naming so Alembic autogenerate produces stable, readable
# migration names instead of database-assigned ones.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDPrimaryKey:
    """UUID primary keys, generated client-side.

    Client-side generation means a caller holds the id before the insert commits,
    which keeps the upload endpoint from needing a round trip mid-request.
    """

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
