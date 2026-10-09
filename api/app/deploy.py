"""Create the private application schema before running hosted migrations."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.config import get_settings
from app.db import build_engine


async def prepare_schema() -> None:
    settings = get_settings()
    if not settings.database_schema:
        raise ValueError("Hosted deployment requires DATABASE_SCHEMA")
    # build_engine validates the identifier before it is used in SQL below.
    engine = build_engine(settings)
    try:
        async with engine.begin() as connection:
            schema = settings.database_schema
            await connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            await connection.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC'))
            # Application auth owns access; Supabase's Data API must not bypass it.
            for role in ("anon", "authenticated"):
                exists = await connection.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
                )
                if exists:
                    await connection.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM {role}'))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(prepare_schema())
