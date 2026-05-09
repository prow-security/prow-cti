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

"""JSONL stdio transport for connector subprocess communication.

This transport is intended for the **connector process** (or tests that
simulate it): ``writer`` carries connector-originated frames toward the
runtime (subprocess stdout) and ``reader`` carries runtime-originated
frames toward the connector (subprocess stdin).
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog

from prow.connector.protocol.codec import MessageTooLargeError, ProtocolError
from prow.connector.protocol.framing import read_messages, write_message
from prow.connector.protocol.messages import (
    CancelAckPayload,
    CancelPayload,
    EmitAckPayload,
    EmitPayload,
    Envelope,
    ErrorCode,
    GetStateAckPayload,
    GetStatePayload,
    HealthAckPayload,
    HealthStatus,
    LogLevel,
    LogPayload,
    MetricPayload,
    SetStateAckPayload,
    SetStatePayload,
    ShutdownAckPayload,
    ShutdownPayload,
)

logger = structlog.get_logger(__name__)

MAX_ACKNOWLEDGED_IN_FLIGHT = 64


class TooManyInFlightError(Exception):
    """Raised when more than 64 acknowledged operations are in flight."""

    def __init__(self) -> None:
        super().__init__(
            "Exceeded the maximum of 64 in-flight acknowledged connector operations.",
        )


_LOG_METHOD = {
    LogLevel.DEBUG: "debug",
    LogLevel.INFO: "info",
    LogLevel.WARNING: "warning",
    LogLevel.ERROR: "error",
    LogLevel.CRITICAL: "critical",
}


class StdioTransport:
    """Connector-side JSONL transport over paired asyncio streams."""

    def __init__(
        self,
        connector_instance_id: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        protocol_version: int,
    ) -> None:
        self._connector_instance_id = connector_instance_id
        self._reader = reader
        self._writer = writer
        self._protocol_version = protocol_version

        self._pending: dict[str, asyncio.Future[Envelope]] = {}
        self._pending_lock = asyncio.Lock()
        self._in_flight_ack = 0
        self._in_flight_lock = asyncio.Lock()

        self._cancelled_event = asyncio.Event()
        self._dispatch_task: asyncio.Task[None] | None = None
        self._dispatch_started = False
        self._closed = False

    @property
    def cancelled(self) -> asyncio.Event:
        return self._cancelled_event

    @property
    def connector_instance_id(self) -> str:
        return self._connector_instance_id

    def _new_message_id(self) -> str:
        return uuid4().hex

    async def _ensure_dispatch(self) -> None:
        if self._dispatch_started:
            return
        self._dispatch_started = True
        self._dispatch_task = asyncio.create_task(
            self._dispatch_loop(),
            name=f"connector-stdio-dispatch-{self._connector_instance_id}",
        )

    async def _acquire_in_flight_slot(self) -> None:
        async with self._in_flight_lock:
            if self._in_flight_ack >= MAX_ACKNOWLEDGED_IN_FLIGHT:
                raise TooManyInFlightError
            self._in_flight_ack += 1

    async def _release_in_flight_slot(self) -> None:
        async with self._in_flight_lock:
            self._in_flight_ack -= 1

    async def _register_pending(self, message_id: str) -> asyncio.Future[Envelope]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Envelope] = loop.create_future()
        async with self._pending_lock:
            self._pending[message_id] = future
        return future

    async def _pop_pending(self, message_id: str) -> asyncio.Future[Envelope] | None:
        async with self._pending_lock:
            return self._pending.pop(message_id, None)

    async def _resolve_envelope_async(self, env: Envelope) -> None:
        if env.id_ref is None:
            return
        fut = await self._pop_pending(env.id_ref)
        if fut is None or fut.done():
            return
        if env.error is not None:
            fut.set_exception(
                ProtocolError(
                    env.error.code,
                    env.error.message,
                    details=dict(env.error.details),
                ),
            )
            return
        fut.set_result(env)

    async def _dispatch_loop(self) -> None:
        try:
            async for env in read_messages(self._reader):
                await self._handle_incoming(env)
        except MessageTooLargeError as exc:
            await self._fail_all_pending(exc)
            logger.warning(
                "connector.stdio.message_too_large",
                connector_instance_id=self._connector_instance_id,
                error=str(exc),
            )
        except ProtocolError as exc:
            await self._fail_all_pending(exc)
            logger.warning(
                "connector.stdio.protocol_error",
                connector_instance_id=self._connector_instance_id,
                code=exc.code.value,
                message=exc.message,
            )
        except Exception as exc:
            wrapped = ProtocolError(
                ErrorCode.MALFORMED_MESSAGE,
                "Connector protocol dispatch loop failed.",
                details={"reason": str(exc)},
            )
            await self._fail_all_pending(wrapped)
            logger.exception(
                "connector.stdio.dispatch_crashed",
                connector_instance_id=self._connector_instance_id,
            )
        finally:
            closed = ProtocolError(
                ErrorCode.MALFORMED_MESSAGE,
                "Connector protocol stream closed.",
                details={"reason": "eof_or_transport_closed"},
            )
            await self._fail_all_pending(closed)

    async def _fail_all_pending(self, exc: BaseException) -> None:
        async with self._pending_lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for _, fut in pending:
            if not fut.done():
                fut.set_exception(exc)
        async with self._in_flight_lock:
            self._in_flight_ack = 0

    async def _handle_incoming(self, env: Envelope) -> None:
        if env.id_ref is not None:
            await self._resolve_envelope_async(env)

        if env.kind == "health" and env.error is None:
            await self._reply_health_probe(env)
        elif env.kind == "shutdown" and env.error is None:
            await self._reply_shutdown_request(env)
        elif env.kind in frozenset({"log", "metric"}):
            await self._forward_observability_from_peer(env)

    async def _reply_health_probe(self, env: Envelope) -> None:
        await write_message(
            self._writer,
            Envelope(
                v=self._protocol_version,
                id=self._new_message_id(),
                kind="health-ack",
                payload=HealthAckPayload(
                    status=HealthStatus.HEALTHY,
                    details={},
                ).model_dump(),
                id_ref=env.id,
            ),
        )

    async def _reply_shutdown_request(self, env: Envelope) -> None:
        self._cancelled_event.set()
        await write_message(
            self._writer,
            Envelope(
                v=self._protocol_version,
                id=self._new_message_id(),
                kind="shutdown-ack",
                payload=ShutdownAckPayload().model_dump(),
                id_ref=env.id,
            ),
        )

    async def _forward_observability_from_peer(self, env: Envelope) -> None:
        """If the peer sends log/metric frames, surface them on prow's logging stack."""

        try:
            if env.kind == "log":
                payload = LogPayload.model_validate(env.payload)
                bound = logger.bind(
                    connector_instance_id=self._connector_instance_id,
                    **payload.fields,
                )
                method_name = _LOG_METHOD.get(payload.level, "info")
                log_fn = getattr(bound, method_name)
                log_fn(payload.message)
            elif env.kind == "metric":
                metric_payload = MetricPayload.model_validate(env.payload)
                logger.debug(
                    "connector.metric.forwarded",
                    name=metric_payload.name,
                    value=metric_payload.value,
                    unit=metric_payload.unit,
                    tags=metric_payload.tags,
                )
        except Exception:
            logger.warning(
                "connector.stdio.observability_forward_failed",
                connector_instance_id=self._connector_instance_id,
                kind=env.kind,
                exc_info=True,
            )

    def _validate_ack_or_raise(self, env: Envelope) -> None:
        if env.error is not None:
            raise ProtocolError(
                env.error.code,
                env.error.message,
                details=dict(env.error.details),
            )

    async def emit(self, bundle: dict[str, Any]) -> EmitAckPayload:
        await self._ensure_dispatch()
        await self._acquire_in_flight_slot()
        message_id = self._new_message_id()
        future = await self._register_pending(message_id)
        try:
            payload = EmitPayload(bundle=bundle)
            await write_message(
                self._writer,
                Envelope(
                    v=self._protocol_version,
                    id=message_id,
                    kind="emit",
                    payload=payload.model_dump(mode="json"),
                ),
            )
            response = await future
            self._validate_ack_or_raise(response)
            if response.kind != "emit-ack":
                raise ProtocolError(
                    ErrorCode.MALFORMED_MESSAGE,
                    "Expected emit-ack response.",
                    details={"kind": response.kind},
                )
            return EmitAckPayload.model_validate(response.payload)
        finally:
            await self._pop_pending(message_id)
            await self._release_in_flight_slot()

    async def set_state(self, key: str, value: Any) -> None:
        await self._ensure_dispatch()
        await self._acquire_in_flight_slot()
        message_id = self._new_message_id()
        future = await self._register_pending(message_id)
        try:
            payload = SetStatePayload(key=key, value=value)
            await write_message(
                self._writer,
                Envelope(
                    v=self._protocol_version,
                    id=message_id,
                    kind="set-state",
                    payload=payload.model_dump(mode="json"),
                ),
            )
            response = await future
            self._validate_ack_or_raise(response)
            if response.kind != "set-state-ack":
                raise ProtocolError(
                    ErrorCode.MALFORMED_MESSAGE,
                    "Expected set-state-ack response.",
                    details={"kind": response.kind},
                )
            SetStateAckPayload.model_validate(response.payload)
        finally:
            await self._pop_pending(message_id)
            await self._release_in_flight_slot()

    async def get_state(self, key: str) -> Any | None:
        await self._ensure_dispatch()
        await self._acquire_in_flight_slot()
        message_id = self._new_message_id()
        future = await self._register_pending(message_id)
        try:
            payload = GetStatePayload(key=key)
            await write_message(
                self._writer,
                Envelope(
                    v=self._protocol_version,
                    id=message_id,
                    kind="get-state",
                    payload=payload.model_dump(mode="json"),
                ),
            )
            response = await future
            self._validate_ack_or_raise(response)
            if response.kind != "get-state-ack":
                raise ProtocolError(
                    ErrorCode.MALFORMED_MESSAGE,
                    "Expected get-state-ack response.",
                    details={"kind": response.kind},
                )
            ack = GetStateAckPayload.model_validate(response.payload)
            return ack.value
        finally:
            await self._pop_pending(message_id)
            await self._release_in_flight_slot()

    async def log(
        self,
        level: LogLevel,
        message: str,
        fields: dict[str, Any] | None = None,
        exception: str | None = None,
    ) -> None:
        await self._ensure_dispatch()
        payload = LogPayload(
            level=level,
            message=message,
            timestamp=datetime.now(UTC),
            fields=dict(fields or {}),
            exception=exception,
        )
        await write_message(
            self._writer,
            Envelope(
                v=self._protocol_version,
                id=self._new_message_id(),
                kind="log",
                payload=payload.model_dump(mode="json"),
            ),
        )

    async def metric(
        self,
        name: str,
        value: float,
        unit: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        await self._ensure_dispatch()
        payload = MetricPayload(
            name=name,
            value=value,
            unit=unit,
            tags=dict(tags or {}),
            timestamp=datetime.now(UTC),
        )
        await write_message(
            self._writer,
            Envelope(
                v=self._protocol_version,
                id=self._new_message_id(),
                kind="metric",
                payload=payload.model_dump(mode="json"),
            ),
        )

    async def health(self) -> HealthAckPayload:
        """Return healthy without additional protocol traffic.

        Runtime-initiated health probes are answered in :meth:`_dispatch_loop`.
        """

        return HealthAckPayload(status=HealthStatus.HEALTHY, details={})

    async def shutdown(self, grace_period_seconds: int = 30) -> None:
        await self._ensure_dispatch()
        await self._acquire_in_flight_slot()
        message_id = self._new_message_id()
        future = await self._register_pending(message_id)
        try:
            payload = ShutdownPayload(grace_period_seconds=grace_period_seconds)
            await write_message(
                self._writer,
                Envelope(
                    v=self._protocol_version,
                    id=message_id,
                    kind="shutdown",
                    payload=payload.model_dump(mode="json"),
                ),
            )
            response = await future
            self._validate_ack_or_raise(response)
            if response.kind != "shutdown-ack":
                raise ProtocolError(
                    ErrorCode.MALFORMED_MESSAGE,
                    "Expected shutdown-ack response.",
                    details={"kind": response.kind},
                )
            ShutdownAckPayload.model_validate(response.payload)
        finally:
            self._cancelled_event.set()
            await self._pop_pending(message_id)
            await self._release_in_flight_slot()
            self._closed = True
            with contextlib.suppress(Exception):
                self._writer.close()
                await self._writer.wait_closed()

    async def cancel_operation(self, target_id: str) -> bool:
        """Send ``cancel`` for a pending operation id and await ``cancel-ack``."""

        await self._ensure_dispatch()
        await self._acquire_in_flight_slot()
        message_id = self._new_message_id()
        future = await self._register_pending(message_id)
        try:
            payload = CancelPayload(target_id=target_id)
            await write_message(
                self._writer,
                Envelope(
                    v=self._protocol_version,
                    id=message_id,
                    kind="cancel",
                    payload=payload.model_dump(mode="json"),
                ),
            )
            response = await future
            self._validate_ack_or_raise(response)
            if response.kind != "cancel-ack":
                raise ProtocolError(
                    ErrorCode.MALFORMED_MESSAGE,
                    "Expected cancel-ack response.",
                    details={"kind": response.kind},
                )
            ack = CancelAckPayload.model_validate(response.payload)
            if ack.cancelled:
                target = await self._pop_pending(target_id)
                if target is not None and not target.done():
                    target.cancel()
            return ack.cancelled
        finally:
            await self._pop_pending(message_id)
            await self._release_in_flight_slot()
