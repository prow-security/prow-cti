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

"""DB-backed connector state get/set for dev / runtime wiring.

Callers own :class:`~sqlalchemy.ext.asyncio.AsyncEngine` lifecycle and pass an
``async_sessionmaker``. Nothing in this module creates a global engine at import time.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prow.db.repositories import SqlAlchemyConnectorStateRepository
from prow.db.session import session_scope

StateGetHandler = Callable[[str, str], Awaitable[Any | None]]
StateSetHandler = Callable[[str, str, Any], Awaitable[None]]


def create_db_state_getter(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    connector_instance_id: str | None = None,
) -> StateGetHandler:
    """Return ``(instance_id, key) -> value | None`` using the SQLAlchemy state repo.

    When ``connector_instance_id`` is set, that id is used for every call and the
    ``instance_id`` argument is ignored (same pattern as ``create_inprocess_db_emit_handler``).
    """

    async def get_state(instance_id: str, key: str) -> Any | None:
        iid = connector_instance_id if connector_instance_id is not None else instance_id
        async with session_scope(session_factory) as session:
            repo = SqlAlchemyConnectorStateRepository(session)
            return await repo.get(iid, key)

    return get_state


def create_db_state_setter(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    connector_instance_id: str | None = None,
) -> StateSetHandler:
    """Return ``(instance_id, key, value) -> None``; commits via ``session.begin()``."""

    async def set_state(instance_id: str, key: str, value: Any) -> None:
        iid = connector_instance_id if connector_instance_id is not None else instance_id
        async with session_scope(session_factory) as session:
            async with session.begin():
                repo = SqlAlchemyConnectorStateRepository(session)
                await repo.set(iid, key, value)

    return set_state
