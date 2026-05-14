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

"""In-process connector transport for development and tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from opentelemetry.metrics import Meter

from prow.connector.protocol.messages import (
    EmitAckPayload,
    HealthAckPayload,
    HealthStatus,
    LogLevel,
    LogPayload,
    MetricPayload,
)

if TYPE_CHECKING:
    from prow.connector.log_forwarder import LogForwarder
    from prow.connector.metric_forwarder import MetricForwarder

EmitHandler = Callable[[dict[str, Any]], Awaitable[EmitAckPayload]]
StateGetHandler = Callable[[str, str], Awaitable[Any | None]]
StateSetHandler = Callable[[str, str, Any], Awaitable[None]]


class InProcessTransport:
    """Direct calls into the local prow runtime without JSONL framing."""

    def __init__(
        self,
        connector_instance_id: str,
        emit_handler: EmitHandler,
        state_store: dict[str, Any],
        logger: structlog.BoundLogger,
        meter: Meter | None = None,
        *,
        log_forwarder: LogForwarder | None = None,
        metric_forwarder: MetricForwarder | None = None,
        state_get_handler: StateGetHandler | None = None,
        state_set_handler: StateSetHandler | None = None,
    ) -> None:
        if (state_get_handler is None) ^ (state_set_handler is None):
            msg = "state_get_handler and state_set_handler must both be set or both be omitted"
            raise ValueError(msg)
        self._connector_instance_id = connector_instance_id
        self._emit_handler = emit_handler
        self._state = state_store
        self._state_get_handler = state_get_handler
        self._state_set_handler = state_set_handler
        self._logger = logger
        self._meter = meter
        self._log_forwarder = log_forwarder
        self._metric_forwarder = metric_forwarder
        self._histograms: dict[tuple[str, str], Any] = {}
        self._cancelled_event = asyncio.Event()

    @property
    def cancelled(self) -> asyncio.Event:
        return self._cancelled_event

    @property
    def connector_instance_id(self) -> str:
        return self._connector_instance_id

    @property
    def state_store(self) -> dict[str, Any]:
        """Mutable state bag shared with tests or dev persistence."""

        return self._state

    async def emit(self, bundle: dict[str, Any]) -> EmitAckPayload:
        return await self._emit_handler(bundle)

    async def set_state(self, key: str, value: Any) -> None:
        if self._state_set_handler is not None:
            await self._state_set_handler(self._connector_instance_id, key, value)
            return
        self._state[key] = value

    async def get_state(self, key: str) -> Any | None:
        if self._state_get_handler is not None:
            return await self._state_get_handler(self._connector_instance_id, key)
        return self._state.get(key)

    async def log(
        self,
        level: LogLevel,
        message: str,
        fields: dict[str, Any] | None = None,
        exception: str | None = None,
    ) -> None:
        if self._log_forwarder is not None:
            merged = dict(fields or {})
            exc_text = merged.pop("exception", exception)
            self._log_forwarder.forward(
                LogPayload(
                    level=level,
                    message=message,
                    timestamp=datetime.now(UTC),
                    fields=merged,
                    exception=exc_text if isinstance(exc_text, str) else exception,
                ),
            )
            return
        payload = dict(fields or {})
        if exception is not None:
            payload["exception"] = exception
        method = getattr(self._logger, level.value, self._logger.info)
        method(message, **payload)

    async def metric(
        self,
        name: str,
        value: float,
        unit: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        if self._metric_forwarder is not None:
            self._metric_forwarder.forward(
                MetricPayload(
                    name=name,
                    value=value,
                    unit=unit,
                    tags=dict(tags or {}),
                    timestamp=datetime.now(UTC),
                ),
            )
            return
        if self._meter is None:
            return
        attrs = {**(tags or {})}
        key = (name, unit or "")
        histogram = self._histograms.get(key)
        if histogram is None:
            histogram = self._meter.create_histogram(name, unit=unit or "")
            self._histograms[key] = histogram
        histogram.record(value, attributes=attrs)

    async def health(self) -> HealthAckPayload:
        return HealthAckPayload(status=HealthStatus.HEALTHY, details={})

    async def shutdown(self, grace_period_seconds: int = 30) -> None:
        del grace_period_seconds
        self._cancelled_event.set()
