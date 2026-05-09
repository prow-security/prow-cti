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

"""Tests for :class:`prow.connector.transport_stdio.StdioTransport`."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from prow.connector.protocol.codec import ProtocolError
from prow.connector.protocol.framing import read_messages, write_message
from prow.connector.protocol.messages import (
    CancelAckPayload,
    EmitAckPayload,
    Envelope,
    ErrorBody,
    ErrorCode,
    ShutdownAckPayload,
    ValidationFailure,
)
from prow.connector.transport_stdio import StdioTransport, TooManyInFlightError


def _bundle() -> dict[str, Any]:
    return {"type": "bundle", "id": "bundle--" + uuid4().hex[:8], "objects": []}


@pytest.mark.asyncio
async def test_emit_round_trip_counts() -> None:
    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async for env in read_messages(reader):
            if env.kind == "emit":
                ack = EmitAckPayload(
                    accepted=2,
                    duplicates=1,
                    validation_failures=[
                        ValidationFailure(object_id="ind--1", error="shape"),
                    ],
                )
                await write_message(
                    writer,
                    Envelope(
                        v=env.v,
                        id=uuid4().hex,
                        kind="emit-ack",
                        payload=ack.model_dump(mode="json"),
                        id_ref=env.id,
                    ),
                )

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    transport = StdioTransport("instance-1", reader, writer, protocol_version=1)

    ack = await transport.emit(_bundle())
    assert ack.accepted == 2
    assert ack.duplicates == 1
    assert len(ack.validation_failures) == 1
    assert ack.validation_failures[0].object_id == "ind--1"

    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_concurrent_emits_match_ids() -> None:
    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async for env in read_messages(reader):
            if env.kind == "emit":
                ack = EmitAckPayload(accepted=1, duplicates=0, validation_failures=[])
                await write_message(
                    writer,
                    Envelope(
                        v=env.v,
                        id=uuid4().hex,
                        kind="emit-ack",
                        payload=ack.model_dump(mode="json"),
                        id_ref=env.id,
                    ),
                )

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    transport = StdioTransport("inst", reader, writer, 1)

    results = await asyncio.gather(*[transport.emit(_bundle()) for _ in range(10)])
    assert len(results) == 10
    assert all(r.accepted == 1 for r in results)

    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_too_many_in_flight_raises() -> None:
    gate = asyncio.Event()
    saw_64 = asyncio.Event()
    emit_seen = 0
    handle_tasks: list[asyncio.Task[None]] = []

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def handle(env: Envelope) -> None:
            nonlocal emit_seen
            if env.kind != "emit":
                return
            emit_seen += 1
            if emit_seen == 64:
                saw_64.set()
            await gate.wait()
            ack = EmitAckPayload(accepted=1, duplicates=0, validation_failures=[])
            await write_message(
                writer,
                Envelope(
                    v=env.v,
                    id=uuid4().hex,
                    kind="emit-ack",
                    payload=ack.model_dump(mode="json"),
                    id_ref=env.id,
                ),
            )

        async for env in read_messages(reader):
            t = asyncio.create_task(handle(env))
            handle_tasks.append(t)

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    transport = StdioTransport("inst", reader, writer, 1)

    emit_tasks = [asyncio.create_task(transport.emit(_bundle())) for _ in range(64)]
    await asyncio.wait_for(saw_64.wait(), timeout=5.0)
    with pytest.raises(TooManyInFlightError):
        await transport.emit(_bundle())

    gate.set()
    await asyncio.gather(*emit_tasks)

    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_error_envelope_rejects_pending_future() -> None:
    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async for env in read_messages(reader):
            if env.kind == "emit":
                await write_message(
                    writer,
                    Envelope(
                        v=env.v,
                        id=uuid4().hex,
                        kind="emit-ack",
                        payload={},
                        id_ref=env.id,
                        error=ErrorBody(
                            code=ErrorCode.VALIDATION_ERROR,
                            message="bad bundle",
                            details={"hint": "fix types"},
                        ),
                    ),
                )

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    transport = StdioTransport("inst", reader, writer, 1)

    with pytest.raises(ProtocolError) as excinfo:
        await transport.emit(_bundle())
    err = excinfo.value
    assert err.code is ErrorCode.VALIDATION_ERROR
    assert err.message == "bad bundle"
    assert err.details.get("hint") == "fix types"

    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_cancel_in_flight_emit() -> None:
    saw_emit = asyncio.Event()
    emit_ids: list[str] = []

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async for env in read_messages(reader):
            if env.kind == "emit":
                emit_ids.append(env.id)
                saw_emit.set()
            elif env.kind == "cancel":
                await write_message(
                    writer,
                    Envelope(
                        v=env.v,
                        id=uuid4().hex,
                        kind="cancel-ack",
                        payload=CancelAckPayload(cancelled=True).model_dump(mode="json"),
                        id_ref=env.id,
                    ),
                )

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    transport = StdioTransport("inst", reader, writer, 1)

    emit_task = asyncio.create_task(transport.emit(_bundle()))
    await asyncio.wait_for(saw_emit.wait(), timeout=2.0)
    assert len(emit_ids) == 1

    ok = await transport.cancel_operation(emit_ids[0])
    assert ok is True

    with pytest.raises(asyncio.CancelledError):
        await emit_task

    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_shutdown_sets_cancelled_and_ack() -> None:
    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async for env in read_messages(reader):
            if env.kind == "shutdown":
                await write_message(
                    writer,
                    Envelope(
                        v=env.v,
                        id=uuid4().hex,
                        kind="shutdown-ack",
                        payload=ShutdownAckPayload().model_dump(mode="json"),
                        id_ref=env.id,
                    ),
                )

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    transport = StdioTransport("inst", reader, writer, 1)

    assert not transport.cancelled.is_set()
    await transport.shutdown(grace_period_seconds=5)
    assert transport.cancelled.is_set()

    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_eof_mid_emit_fails_pending() -> None:
    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async for env in read_messages(reader):
            if env.kind == "emit":
                writer.close()
                await writer.wait_closed()
                return

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    transport = StdioTransport("inst", reader, writer, 1)

    with pytest.raises(ProtocolError) as excinfo:
        await transport.emit(_bundle())
    assert "closed" in str(excinfo.value.message).lower()

    server.close()
    await server.wait_closed()
