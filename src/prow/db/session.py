# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Async SQLAlchemy engine and session factories."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from prow.db.config import DatabaseSettings, load_database_settings


def create_async_engine_from_settings(
    settings: DatabaseSettings | None = None,
    *,
    echo: bool = False,
) -> AsyncEngine:
    """Create a new async engine (callers own lifecycle; no import-time singleton)."""

    cfg = settings or load_database_settings()
    return create_async_engine(
        cfg.database_url,
        echo=echo,
        pool_size=cfg.database_pool_size,
        max_overflow=cfg.database_pool_max_overflow,
        pool_timeout=cfg.database_pool_timeout_seconds,
    )


def create_async_sessionmaker(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Session factory bound to ``engine`` (``expire_on_commit=False`` for JSON reads)."""

    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def check_database(engine: AsyncEngine) -> bool:
    """Return ``True`` if ``SELECT 1`` succeeds."""

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def dispose_engine(engine: AsyncEngine) -> None:
    """Dispose ``engine`` pools (tests / shutdown)."""

    await engine.dispose()


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a session and always close it (transaction is caller-owned)."""

    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
