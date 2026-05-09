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

"""Async newline framing for the connector protocol."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from prow.connector.protocol.codec import (
    MessageTooLargeError,
    ProtocolError,
    decode,
    encode,
)
from prow.connector.protocol.messages import Envelope, ErrorCode


async def read_messages(
    stream: asyncio.StreamReader,
    max_line_bytes: int = 1 << 20,
) -> AsyncIterator[Envelope]:
    """Yield envelopes parsed from a newline-delimited async stream."""

    while True:
        try:
            line = await stream.readuntil(b"\n")
        except asyncio.IncompleteReadError as exc:
            if not exc.partial:
                return
            if len(exc.partial) > max_line_bytes:
                raise MessageTooLargeError(
                    "Protocol line exceeds the maximum line size.",
                    size_bytes=len(exc.partial),
                    limit_bytes=max_line_bytes,
                ) from exc
            raise ProtocolError(
                ErrorCode.MALFORMED_MESSAGE,
                "Stream ended in the middle of a protocol message.",
                details={"partial_bytes": len(exc.partial)},
            ) from exc
        except asyncio.LimitOverrunError as exc:
            raise MessageTooLargeError(
                "Protocol line exceeds the maximum line size.",
                size_bytes=exc.consumed,
                limit_bytes=max_line_bytes,
            ) from exc

        if len(line) > max_line_bytes:
            raise MessageTooLargeError(
                "Protocol line exceeds the maximum line size.",
                size_bytes=len(line),
                limit_bytes=max_line_bytes,
            )

        if line == b"\n":
            continue

        yield decode(line)


async def write_message(
    stream: asyncio.StreamWriter,
    envelope: Envelope,
) -> None:
    """Encode, write, and flush one protocol envelope."""

    stream.write(encode(envelope))
    await stream.drain()
