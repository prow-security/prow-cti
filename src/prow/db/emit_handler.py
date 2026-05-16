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
# See the License for the specific governing permissions and
# limitations under the License.

"""DB-backed STIX bundle emit handlers for runtime / dev wiring.

Callers (CLI, supervisor glue, tests) own :class:`~sqlalchemy.ext.asyncio.AsyncEngine`
lifecycle and pass an ``async_sessionmaker`` here. Nothing in this module creates a
global engine at import time.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prow.connector.protocol.messages import EmitAckPayload
from prow.db.ingest import ingest_stix_bundle
from prow.db.session import session_scope

EmitHandler = Callable[[str, dict[str, Any]], Awaitable[EmitAckPayload]]
InProcessEmitHandler = Callable[[dict[str, Any]], Awaitable[EmitAckPayload]]


def create_db_emit_handler(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    allow_custom_types_by_instance: dict[str, bool] | None = None,
) -> EmitHandler:
    """Return ``(instance_id, bundle) -> EmitAckPayload`` using :func:`ingest_stix_bundle`."""

    custom_types_lookup = allow_custom_types_by_instance or {}

    async def emit_handler(instance_id: str, bundle: dict[str, Any]) -> EmitAckPayload:
        async with session_scope(session_factory) as session:
            return await ingest_stix_bundle(
                session,
                bundle,
                source_connector_instance_id=instance_id,
                allow_custom_types=custom_types_lookup.get(instance_id, False),
            )

    return emit_handler


def create_inprocess_db_emit_handler(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    connector_instance_id: str,
    allow_custom_types: bool = False,
) -> InProcessEmitHandler:
    """Emit handler with signature expected by in-process transport."""

    inner = create_db_emit_handler(
        session_factory,
        allow_custom_types_by_instance={connector_instance_id: allow_custom_types},
    )

    async def emit_bundle(bundle: dict[str, Any]) -> EmitAckPayload:
        return await inner(connector_instance_id, bundle)

    return emit_bundle
