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

"""Runtime-side JSONL dispatch for one connector subprocess (inverse of StdioTransport)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
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
    HealthPayload,
    LogPayload,
    MetricPayload,
    SetStateAckPayload,
    SetStatePayload,
    ShutdownAckPayload,
    ShutdownPayload,
)

logger = structlog.get_logger(__name__)

EmitHandler = Callable[[str, dict[str, Any]], Awaitable[EmitAckPayload]]
StateGetHandler = Callable[[str, str], Awaitable[Any | None]]
StateSetHandler = Callable[[str, str, Any], Awaitable[None]]
LogHandler = Callable[[LogPayload], None]
MetricHandler = Callable[[MetricPayload], None]


class ConnectorProcessExited(Exception):  # noqa: N818
    """Raised when the connector stdout stream closes unexpectedly."""

    def __init__(self, message: str = "Connector subprocess ended the protocol stream.") -> None:
        super().__init__(message)


class ConnectorRuntimeTransport:
    """Runtime-side protocol peer: consumes connector stdout, writes connector stdin."""

    def __init__(
        self,
        connector_instance_id: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        protocol_version: int,
        emit_handler: EmitHandler,
        state_get_handler: StateGetHandler,
        state_set_handler: StateSetHandler,
        log_handler: LogHandler | None = None,
        metric_handler: MetricHandler | None = None,
    ) -> None:
        self._connector_instance_id = connector_instance_id
        self._reader = reader
        self._writer = writer
        self._protocol_version = protocol_version
        self._emit_handler = emit_handler
        self._state_get_handler = state_get_handler
        self._state_set_handler = state_set_handler
        self._log_handler = log_handler
        self._metric_handler = metric_handler

        self._pending_runtime: dict[str, asyncio.Future[Envelope]] = {}
        self._pending_lock = asyncio.Lock()

        self._dispatch_task: asyncio.Task[None] | None = None
        self._fatal_protocol_error: BaseException | None = None

    @property
    def fatal_protocol_error(self) -> BaseException | None:
        """Set when the dispatch loop stops due to a protocol violation."""

        return self._fatal_protocol_error

    def _new_message_id(self) -> str:
        return uuid4().hex

    async def _register_runtime_pending(self, message_id: str) -> asyncio.Future[Envelope]:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Envelope] = loop.create_future()
        async with self._pending_lock:
            self._pending_runtime[message_id] = fut
        return fut

    async def _pop_runtime_pending(self, message_id: str) -> asyncio.Future[Envelope] | None:
        async with self._pending_lock:
            return self._pending_runtime.pop(message_id, None)

    async def _resolve_runtime_ack(self, env: Envelope) -> None:
        if env.id_ref is None:
            return
        fut = await self._pop_runtime_pending(env.id_ref)
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

    async def start(self) -> None:
        """Start the dispatch loop that consumes connector-originated frames."""

        if self._dispatch_task is not None:
            return
        self._dispatch_task = asyncio.create_task(
            self._dispatch_loop(),
            name=f"connector-runtime-dispatch-{self._connector_instance_id}",
        )

    async def wait_dispatch_finished(self) -> None:
        """Await the dispatch loop (used during teardown)."""

        if self._dispatch_task is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await self._dispatch_task

    async def _dispatch_loop(self) -> None:
        try:
            async for env in read_messages(self._reader):
                await self._dispatch_one(env)
        except MessageTooLargeError as exc:
            await self._fail_runtime_pending(exc)
            logger.error(
                "connector.runtime.message_too_large",
                connector_instance_id=self._connector_instance_id,
                error=str(exc),
            )
            self._fatal_protocol_error = exc
        except ProtocolError as exc:
            await self._fail_runtime_pending(exc)
            logger.error(
                "connector.runtime.protocol_error",
                connector_instance_id=self._connector_instance_id,
                code=exc.code.value,
                message=exc.message,
            )
            self._fatal_protocol_error = exc
        except Exception as exc:
            wrapped = ProtocolError(
                ErrorCode.MALFORMED_MESSAGE,
                "Connector protocol dispatch failed.",
                details={"reason": str(exc)},
            )
            await self._fail_runtime_pending(wrapped)
            logger.exception(
                "connector.runtime.dispatch_crashed",
                connector_instance_id=self._connector_instance_id,
            )
            self._fatal_protocol_error = wrapped
        finally:
            exited = ConnectorProcessExited()
            await self._fail_runtime_pending(exited)

    async def _fail_runtime_pending(self, exc: BaseException) -> None:
        async with self._pending_lock:
            pending = list(self._pending_runtime.items())
            self._pending_runtime.clear()
        for _, fut in pending:
            if not fut.done():
                fut.set_exception(exc)

    async def _dispatch_one(self, env: Envelope) -> None:
        if env.id_ref is not None:
            await self._resolve_runtime_ack(env)

        kind = env.kind
        if kind in frozenset({"hello", "hello-ack"}):
            logger.error(
                "connector.runtime.unexpected_lifecycle_kind",
                connector_instance_id=self._connector_instance_id,
                kind=kind,
            )
            raise ProtocolError(
                ErrorCode.MALFORMED_MESSAGE,
                "Lifecycle message received outside negotiation.",
                details={"kind": kind},
            )

        if kind == "emit":
            await self._handle_emit(env)
        elif kind == "set-state":
            await self._handle_set_state(env)
        elif kind == "get-state":
            await self._handle_get_state(env)
        elif kind == "log":
            await self._handle_log(env)
        elif kind == "metric":
            await self._handle_metric(env)
        elif kind in frozenset(
            {
                "emit-ack",
                "set-state-ack",
                "get-state-ack",
                "health-ack",
                "cancel-ack",
                "shutdown-ack",
            },
        ):
            # Pure ack envelopes were handled via id_ref above.
            return
        else:
            logger.error(
                "connector.runtime.unknown_kind",
                connector_instance_id=self._connector_instance_id,
                kind=kind,
            )
            raise ProtocolError(
                ErrorCode.UNKNOWN_KIND,
                "Unknown connector protocol kind.",
                details={"kind": kind},
            )

    async def _handle_emit(self, env: Envelope) -> None:
        payload = EmitPayload.model_validate(env.payload)
        ack = await self._emit_handler(self._connector_instance_id, payload.bundle)
        await write_message(
            self._writer,
            Envelope(
                v=self._protocol_version,
                id=self._new_message_id(),
                kind="emit-ack",
                payload=ack.model_dump(mode="json"),
                id_ref=env.id,
            ),
        )

    async def _handle_set_state(self, env: Envelope) -> None:
        payload = SetStatePayload.model_validate(env.payload)
        await self._state_set_handler(
            self._connector_instance_id,
            payload.key,
            payload.value,
        )
        await write_message(
            self._writer,
            Envelope(
                v=self._protocol_version,
                id=self._new_message_id(),
                kind="set-state-ack",
                payload=SetStateAckPayload().model_dump(mode="json"),
                id_ref=env.id,
            ),
        )

    async def _handle_get_state(self, env: Envelope) -> None:
        payload = GetStatePayload.model_validate(env.payload)
        value = await self._state_get_handler(self._connector_instance_id, payload.key)
        ack = GetStateAckPayload(value=value)
        await write_message(
            self._writer,
            Envelope(
                v=self._protocol_version,
                id=self._new_message_id(),
                kind="get-state-ack",
                payload=ack.model_dump(mode="json"),
                id_ref=env.id,
            ),
        )

    async def _handle_log(self, env: Envelope) -> None:
        payload = LogPayload.model_validate(env.payload)
        if self._log_handler is not None:
            self._log_handler(payload)

    async def _handle_metric(self, env: Envelope) -> None:
        payload = MetricPayload.model_validate(env.payload)
        if self._metric_handler is not None:
            self._metric_handler(payload)

    def _validate_ack_envelope(self, env: Envelope, expected_kind: str) -> None:
        if env.error is not None:
            raise ProtocolError(
                env.error.code,
                env.error.message,
                details=dict(env.error.details),
            )
        if env.kind != expected_kind:
            raise ProtocolError(
                ErrorCode.MALFORMED_MESSAGE,
                f"Expected {expected_kind}.",
                details={"kind": env.kind},
            )

    async def request_health(self, timeout: float = 5.0) -> HealthAckPayload:
        await self.start()
        message_id = self._new_message_id()
        fut = await self._register_runtime_pending(message_id)
        try:
            hp = HealthPayload()
            await write_message(
                self._writer,
                Envelope(
                    v=self._protocol_version,
                    id=message_id,
                    kind="health",
                    payload=hp.model_dump(mode="json"),
                ),
            )
            env = await asyncio.wait_for(fut, timeout=timeout)
            self._validate_ack_envelope(env, "health-ack")
            return HealthAckPayload.model_validate(env.payload)
        except TimeoutError:
            pending = await self._pop_runtime_pending(message_id)
            if pending is not None and not pending.done():
                pending.cancel()
            raise
        finally:
            await self._pop_runtime_pending(message_id)

    async def request_cancel(self, target_id: str) -> bool:
        await self.start()
        message_id = self._new_message_id()
        fut = await self._register_runtime_pending(message_id)
        try:
            cp = CancelPayload(target_id=target_id)
            await write_message(
                self._writer,
                Envelope(
                    v=self._protocol_version,
                    id=message_id,
                    kind="cancel",
                    payload=cp.model_dump(mode="json"),
                ),
            )
            env = await asyncio.wait_for(fut, timeout=60.0)
            self._validate_ack_envelope(env, "cancel-ack")
            ack = CancelAckPayload.model_validate(env.payload)
            return ack.cancelled
        except TimeoutError:
            pending = await self._pop_runtime_pending(message_id)
            if pending is not None and not pending.done():
                pending.cancel()
            raise
        finally:
            await self._pop_runtime_pending(message_id)

    async def request_shutdown(self, grace_period_seconds: int = 30) -> None:
        await self.start()
        message_id = self._new_message_id()
        fut = await self._register_runtime_pending(message_id)
        try:
            sp = ShutdownPayload(grace_period_seconds=grace_period_seconds)
            await write_message(
                self._writer,
                Envelope(
                    v=self._protocol_version,
                    id=message_id,
                    kind="shutdown",
                    payload=sp.model_dump(mode="json"),
                ),
            )
            env = await asyncio.wait_for(fut, timeout=max(float(grace_period_seconds), 1.0))
            self._validate_ack_envelope(env, "shutdown-ack")
            ShutdownAckPayload.model_validate(env.payload)
        except TimeoutError as exc:
            pending = await self._pop_runtime_pending(message_id)
            if pending is not None and not pending.done():
                pending.cancel()
            raise exc
        finally:
            await self._pop_runtime_pending(message_id)

    async def close_writer(self) -> None:
        self._writer.close()
        with contextlib.suppress(Exception):
            await self._writer.wait_closed()
