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

"""Tests for connector protocol newline framing."""

from __future__ import annotations

import asyncio

import pytest

from prow.connector.protocol.codec import MessageTooLargeError, ProtocolError, encode
from prow.connector.protocol.framing import read_messages, write_message
from prow.connector.protocol.messages import Envelope


def _reader_with(data: bytes, *, eof: bool = True) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    if eof:
        reader.feed_eof()
    return reader


async def _collect(reader: asyncio.StreamReader) -> list[Envelope]:
    return [message async for message in read_messages(reader)]


@pytest.mark.asyncio
async def test_read_messages_yields_concatenated_envelopes() -> None:
    envelopes = [
        Envelope(v=1, id="message-1", kind="health"),
        Envelope(v=1, id="message-2", kind="health"),
        Envelope(v=1, id="message-3", kind="health"),
    ]
    reader = _reader_with(b"".join(encode(envelope) for envelope in envelopes))

    assert await _collect(reader) == envelopes


@pytest.mark.asyncio
async def test_read_messages_skips_empty_lines() -> None:
    envelope = Envelope(v=1, id="message-1", kind="health")
    reader = _reader_with(b"\n" + encode(envelope) + b"\n")

    assert await _collect(reader) == [envelope]


@pytest.mark.asyncio
async def test_read_messages_raises_on_oversized_line_before_decode() -> None:
    reader = _reader_with(b"x" * 11 + b"\n")

    with pytest.raises(MessageTooLargeError):
        await _collect_with_limit(reader, max_line_bytes=10)


async def _collect_with_limit(
    reader: asyncio.StreamReader,
    *,
    max_line_bytes: int,
) -> list[Envelope]:
    return [message async for message in read_messages(reader, max_line_bytes=max_line_bytes)]


@pytest.mark.asyncio
async def test_read_messages_raises_on_truncated_stream() -> None:
    reader = _reader_with(b'{"v":1,"id":"message-1"', eof=True)

    with pytest.raises(ProtocolError):
        await _collect(reader)


@pytest.mark.asyncio
async def test_write_message_followed_by_read_messages_round_trips() -> None:
    received: asyncio.Future[list[Envelope]] = asyncio.get_running_loop().create_future()

    async def handle_client(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            received.set_result(await _collect(reader))
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    envelope = Envelope(v=1, id="message-1", kind="health")

    await write_message(writer, envelope)
    writer.close()
    await writer.wait_closed()

    try:
        assert await received == [envelope]
    finally:
        server.close()
        await server.wait_closed()
        reader.feed_eof()
