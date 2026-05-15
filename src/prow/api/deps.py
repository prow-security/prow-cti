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

"""FastAPI dependency injection helpers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from prow.connector.supervisor import Supervisor
from prow.db.repositories import (
    RelationshipRepository,
    SqlAlchemyRelationshipRepository,
    SqlAlchemyStixObjectRepository,
    StixObjectRepository,
)

# Global instances initialized at startup
_session_factory: Any = None
_supervisor: Supervisor | None = None


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session."""
    if _session_factory is None:
        raise RuntimeError("Database session factory not initialized")

    session = _session_factory()
    try:
        yield session
    finally:
        await session.close()


async def get_stix_object_repo(
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> StixObjectRepository:
    """Return a StixObjectRepository."""
    return SqlAlchemyStixObjectRepository(session)


async def get_relationship_repo(
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> RelationshipRepository:
    """Return a RelationshipRepository."""
    return SqlAlchemyRelationshipRepository(session)


async def get_supervisor() -> Supervisor:
    """Return the global Supervisor instance."""
    if _supervisor is None:
        raise RuntimeError("Supervisor not initialized")
    return _supervisor
