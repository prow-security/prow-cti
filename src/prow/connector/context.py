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

"""Connector author-facing context built on top of a transport."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from prow.connector.protocol.messages import LogLevel, ValidationFailure
from prow.connector.transport import ConnectorTransport
from prow.stix.types import Bundle


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _peek_initial_last_run_at(transport: ConnectorTransport) -> datetime | None:
    store = getattr(transport, "state_store", None)
    if isinstance(store, dict):
        return _coerce_datetime(store.get("__last_run_at__"))
    return None


@dataclass(frozen=True)
class EmitResult:
    """Subset of emit acknowledgement data surfaced to connector authors."""

    accepted: int
    duplicates: int
    failures: list[ValidationFailure]


class _RoutingBoundLogger:
    """Minimal structlog-like surface that forwards to :meth:`ConnectorTransport.log`."""

    __slots__ = ("_connector_instance_id", "_tasks", "_transport")

    def __init__(
        self,
        transport: ConnectorTransport,
        *,
        connector_instance_id: str,
    ) -> None:
        self._transport = transport
        self._connector_instance_id = connector_instance_id
        self._tasks: set[asyncio.Task[None]] = set()

    def _schedule(self, level: LogLevel, message: str, fields: dict[str, Any]) -> None:
        merged = {"connector_instance_id": self._connector_instance_id, **fields}

        async def _runner() -> None:
            await self._transport.log(
                level,
                message,
                fields=merged,
                exception=None,
            )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(_runner())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._schedule(LogLevel.DEBUG, msg, kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._schedule(LogLevel.INFO, msg, kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._schedule(LogLevel.WARNING, msg, kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._schedule(LogLevel.ERROR, msg, kwargs)

    def critical(self, msg: str, **kwargs: Any) -> None:
        self._schedule(LogLevel.CRITICAL, msg, kwargs)


class ConnectorContext:
    """Runtime-provided connector lifecycle context."""

    connector_instance_id: str
    config: dict[str, Any]
    log: _RoutingBoundLogger
    last_run_at: datetime | None

    def __init__(
        self,
        transport: ConnectorTransport,
        config: dict[str, Any],
        *,
        time_source: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport
        self.config = config
        self.connector_instance_id = transport.connector_instance_id
        self.log = _RoutingBoundLogger(
            transport,
            connector_instance_id=self.connector_instance_id,
        )
        self.last_run_at = _peek_initial_last_run_at(transport)
        self._time_source = time_source or (lambda: datetime.now(UTC))

    @property
    def cancelled(self) -> asyncio.Event:
        return self._transport.cancelled

    @property
    def now(self) -> datetime:
        return self._time_source()

    async def emit(self, bundle: Bundle | dict[str, Any]) -> EmitResult:
        if isinstance(bundle, Bundle):
            payload = bundle.model_dump(mode="json")
        else:
            payload = bundle
        ack = await self._transport.emit(payload)
        return EmitResult(
            accepted=ack.accepted,
            duplicates=ack.duplicates,
            failures=list(ack.validation_failures),
        )

    async def set_state(self, key: str, value: Any) -> None:
        await self._transport.set_state(key, value)

    async def get_state(self, key: str, default: Any = None) -> Any:
        value = await self._transport.get_state(key)
        return default if value is None else value
