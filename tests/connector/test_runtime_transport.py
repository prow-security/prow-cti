# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for :class:`prow.connector.runtime_transport.ConnectorRuntimeTransport`."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from uuid import uuid4

import pytest

from prow.connector.protocol.framing import read_messages, write_message
from prow.connector.protocol.messages import (
    CancelAckPayload,
    CancelPayload,
    EmitAckPayload,
    Envelope,
    HealthStatus,
    LogLevel,
)
from prow.connector.runtime_transport import ConnectorProcessExited, ConnectorRuntimeTransport
from prow.connector.transport_stdio import StdioTransport


def _bundle() -> dict[str, Any]:
    return {"type": "bundle", "id": "bundle--" + uuid4().hex[:8], "objects": []}


async def _close_server_writer(writer: asyncio.StreamWriter) -> None:
    """Close a server-side writer best-effort.

    Server-side connection handlers must close their writer for
    ``Server.wait_closed()`` to resolve on Python 3.12 patch releases; the
    writer may already be closed by the test body, so swallow expected errors.
    """

    with contextlib.suppress(Exception):
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_emit_round_trip_with_handler() -> None:
    saw: list[dict[str, Any]] = []

    async def emit_handler(_inst: str, bundle: dict[str, Any]) -> EmitAckPayload:
        saw.append(bundle)
        return EmitAckPayload(accepted=1, duplicates=0, validation_failures=[])

    async def get_handler(_inst: str, _key: str) -> Any | None:
        return None

    async def set_handler(_inst: str, _key: str, _value: Any) -> None:
        return None

    async def runtime_peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            rt = ConnectorRuntimeTransport(
                "rt-emit",
                reader,
                writer,
                1,
                emit_handler,
                get_handler,
                set_handler,
            )
            await rt.start()
            await asyncio.sleep(0.3)
            await rt.wait_dispatch_finished()
        finally:
            await _close_server_writer(writer)

    server = await asyncio.start_server(runtime_peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    transport = StdioTransport("rt-emit", reader, writer, 1)

    ack = await transport.emit(_bundle())
    assert ack.accepted == 1
    assert len(saw) == 1

    writer.close()
    await writer.wait_closed()
    server.close()
    await asyncio.wait_for(server.wait_closed(), timeout=5.0)


@pytest.mark.asyncio
async def test_log_and_metric_complete_without_ack_round_trip() -> None:
    """Log/metric frames have no ack; connector log/metric calls should still finish."""

    async def emit_handler(_inst: str, _bundle: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_handler(_inst: str, _key: str) -> Any | None:
        return None

    async def set_handler(_inst: str, _key: str, _value: Any) -> None:
        return None

    async def runtime_peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            rt = ConnectorRuntimeTransport(
                "rt-fnf",
                reader,
                writer,
                1,
                emit_handler,
                get_handler,
                set_handler,
            )
            await rt.start()
            await asyncio.sleep(0.4)
            await rt.wait_dispatch_finished()
        finally:
            await _close_server_writer(writer)

    server = await asyncio.start_server(runtime_peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    transport = StdioTransport("rt-fnf", reader, writer, 1)

    await transport.log(LogLevel.INFO, "hello-log", fields={"k": "v"})
    await transport.metric("m1", 1.0, unit=None, tags={})

    writer.close()
    await writer.wait_closed()
    server.close()
    await asyncio.wait_for(server.wait_closed(), timeout=5.0)


@pytest.mark.asyncio
async def test_request_health_resolves() -> None:
    health_out: list[Any] = []

    async def emit_handler(_inst: str, _bundle: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_handler(_inst: str, _key: str) -> Any | None:
        return None

    async def set_handler(_inst: str, _key: str, _value: Any) -> None:
        return None

    async def runtime_peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            rt = ConnectorRuntimeTransport(
                "rt-h",
                reader,
                writer,
                1,
                emit_handler,
                get_handler,
                set_handler,
            )
            await rt.start()
            await asyncio.sleep(0.2)
            h = await rt.request_health(timeout=5.0)
            health_out.append(h)
            await rt.wait_dispatch_finished()
        finally:
            await _close_server_writer(writer)

    server = await asyncio.start_server(runtime_peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    transport = StdioTransport("rt-h", reader, writer, 1)
    await transport.log(LogLevel.DEBUG, "prime-dispatch", fields={})
    await asyncio.sleep(0.5)

    writer.close()
    await writer.wait_closed()
    server.close()
    await asyncio.wait_for(server.wait_closed(), timeout=5.0)

    assert len(health_out) == 1
    assert health_out[0].status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_request_cancel_peer_returns_ack() -> None:
    async def emit_handler(_inst: str, _bundle: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_handler(_inst: str, _key: str) -> Any | None:
        return None

    async def set_handler(_inst: str, _key: str, _value: Any) -> None:
        return None

    cancel_out: list[bool] = []

    async def fake_connector(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async for env in read_messages(reader):
                if env.kind == "cancel":
                    CancelPayload.model_validate(env.payload)
                    ack = CancelAckPayload(cancelled=True)
                    await write_message(
                        writer,
                        Envelope(
                            v=env.v,
                            id=uuid4().hex,
                            kind="cancel-ack",
                            payload=ack.model_dump(mode="json"),
                            id_ref=env.id,
                        ),
                    )
        finally:
            await _close_server_writer(writer)

    server = await asyncio.start_server(fake_connector, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)

    rt = ConnectorRuntimeTransport(
        "rt-can",
        reader,
        writer,
        1,
        emit_handler,
        get_handler,
        set_handler,
    )
    await rt.start()
    cancel_out.append(await rt.request_cancel("some-target"))

    writer.close()
    await writer.wait_closed()
    await rt.wait_dispatch_finished()
    server.close()
    await asyncio.wait_for(server.wait_closed(), timeout=5.0)

    assert cancel_out == [True]


@pytest.mark.asyncio
async def test_eof_rejects_pending_runtime_future(monkeypatch: pytest.MonkeyPatch) -> None:
    async def emit_handler(_inst: str, _bundle: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_handler(_inst: str, _key: str) -> Any | None:
        return None

    async def set_handler(_inst: str, _key: str, _value: Any) -> None:
        return None

    health_err: list[BaseException] = []
    pending_registered = asyncio.Event()
    peer_done = asyncio.Event()
    real_register = ConnectorRuntimeTransport._register_runtime_pending

    async def register_hook(self: ConnectorRuntimeTransport, message_id: str) -> asyncio.Future:
        fut = await real_register(self, message_id)
        pending_registered.set()
        return fut

    monkeypatch.setattr(ConnectorRuntimeTransport, "_register_runtime_pending", register_hook)

    async def runtime_peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            rt = ConnectorRuntimeTransport(
                "rt-eof",
                reader,
                writer,
                1,
                emit_handler,
                get_handler,
                set_handler,
            )
            await rt.start()
            try:
                await rt.request_health(timeout=30.0)
            except Exception as exc:
                health_err.append(exc)
            await rt.wait_dispatch_finished()
        finally:
            await _close_server_writer(writer)
            peer_done.set()

    server = await asyncio.start_server(runtime_peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.wait_for(pending_registered.wait(), timeout=5.0)
    writer.close()
    await writer.wait_closed()
    server.close()
    await asyncio.wait_for(server.wait_closed(), timeout=5.0)
    await asyncio.wait_for(peer_done.wait(), timeout=30.0)

    assert len(health_err) == 1
    assert isinstance(health_err[0], ConnectorProcessExited)
