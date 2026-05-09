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

"""Structural typing protocol for connector transports."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from prow.connector.protocol.messages import EmitAckPayload, HealthAckPayload, LogLevel


class ConnectorTransport(Protocol):
    """Interface :class:`~prow.connector.context.ConnectorContext` calls into.

    Production (:class:`~prow.connector.transport_stdio.StdioTransport`) and
    development (:class:`~prow.connector.transport_inprocess.InProcessTransport`)
    implementations satisfy this protocol structurally.
    """

    async def emit(self, bundle: dict[str, Any]) -> EmitAckPayload:
        """Emit a STIX bundle and await runtime acknowledgement."""

    async def set_state(self, key: str, value: Any) -> None:
        """Persist connector-owned state."""

    async def get_state(self, key: str) -> Any | None:
        """Load connector-owned state."""

    async def log(
        self,
        level: LogLevel,
        message: str,
        fields: dict[str, Any] | None = None,
        exception: str | None = None,
    ) -> None:
        """Forward a structured log record (fire-and-forget on the wire)."""

    async def metric(
        self,
        name: str,
        value: float,
        unit: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Record a metric observation (fire-and-forget on the wire)."""

    async def health(self) -> HealthAckPayload:
        """Return a health snapshot for the connector instance."""

    async def shutdown(self, grace_period_seconds: int = 30) -> None:
        """Request graceful shutdown of the connector transport session."""

    @property
    def cancelled(self) -> asyncio.Event:
        """Set when the transport session should abandon work."""

    @property
    def connector_instance_id(self) -> str:
        """Supervisor- or dev-runtime-assigned instance identifier."""
