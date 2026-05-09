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

"""Stdin/stdout streams and subprocess environment hygiene for connectors.

POSIX targets attach :class:`asyncio.StreamReader` /
:class:`asyncio.StreamWriter` with :func:`asyncio.loop.connect_read_pipe` and
:func:`asyncio.loop.connect_write_pipe`.

On Windows, :class:`asyncio.ProactorEventLoop` pipe transports use IOCP in ways
that break anonymous subprocess pipes (``recv_into`` on stdin;
``recv``-for-close-detection on stdout write transport → ``WinError 6``). The
connector subprocess therefore pumps stdin with ``asyncio.to_thread`` using
``buffer.readline()`` (``read(n)`` can block until *n* bytes on some pipe
semantics), uses blocking ``os.write`` for stdout, and exits via
:func:`connector_subprocess_exit` so ``asyncio.run`` shutdown does not wait on a
worker blocked in ``readline`` forever. All platform branching stays here.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import NoReturn, cast


def _windows_stdio_workaround() -> bool:
    """Whether to avoid asyncio pipe transports for subprocess stdio."""

    return os.name == "nt"


async def _pump_binary_stdin(reader: asyncio.StreamReader) -> None:
    """Feed ``sys.stdin.buffer`` into ``reader`` using line reads (see module doc)."""

    stdin_b = sys.stdin.buffer
    try:
        while True:
            line = await asyncio.to_thread(stdin_b.readline)
            if not line:
                reader.feed_eof()
                return
            reader.feed_data(line)
    except BaseException:
        if not reader.at_eof():
            reader.feed_eof()
        raise


def connector_subprocess_exit(code: int) -> NoReturn:
    """Terminate the connector interpreter without joining blocked thread-pool workers.

    On Windows, ``asyncio.to_thread(stdin.readline)`` can leave the default executor
    blocked on stdin forever; ``asyncio.run`` then waits for that worker during
    shutdown. ``os._exit`` skips that join (Linux keeps normal ``SystemExit``).
    """

    if os.name == "nt":
        os._exit(int(code))
    raise SystemExit(code)


class _WindowsBlockingStdoutWriter:
    """Stdout JSONL writes without Proactor pipe transports (Windows subprocess).

    Writes FD 1 directly: ``BufferedWriter`` around the pipe can delay delivery
    enough that the parent's asyncio stdout reader never completes negotiation.
    """

    __slots__ = ("_closing",)

    def __init__(self) -> None:
        self._closing = False

    def write(self, data: bytes) -> None:
        if self._closing:
            raise ConnectionResetError("stdout is closing")
        os.write(1, data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self._closing = True

    async def wait_closed(self) -> None:
        return None


def optional_inherited_environ_keys() -> tuple[str, ...]:
    """Extra keys copied from the parent only when present (Windows Python needs some)."""

    return (
        "SYSTEMROOT",
        "WINDIR",
        "PATHEXT",
        "COMSPEC",
    )


def connector_subprocess_environ(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a minimal env dict for ``asyncio.create_subprocess_exec``.

    Does not forward the parent's full environment (secrets stay out).
    """

    env: dict[str, str] = {"PYTHONUNBUFFERED": "1"}
    for key in ("PATH", "PYTHONPATH"):
        if key in os.environ:
            env[key] = os.environ[key]
    for key in optional_inherited_environ_keys():
        if key in os.environ:
            env[key] = os.environ[key]
    if extra:
        env.update(extra)
    return env


async def open_connector_stdio_streams() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Binary stdin/stdout as asyncio streams for code running inside the connector."""

    loop = asyncio.get_running_loop()
    reader: asyncio.StreamReader = asyncio.StreamReader()

    if _windows_stdio_workaround():
        # Fire-and-forget: cancelled implicitly when the interpreter exits.
        loop.create_task(_pump_binary_stdin(reader))  # noqa: RUF006
        await asyncio.sleep(0)
        blocking_out = _WindowsBlockingStdoutWriter()
        return reader, cast(asyncio.StreamWriter, blocking_out)

    stdin_protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: stdin_protocol, sys.stdin.buffer)

    transport_out, proto_out = await loop.connect_write_pipe(
        lambda: asyncio.streams.FlowControlMixin(loop),
        sys.stdout.buffer,
    )
    writer = asyncio.StreamWriter(transport_out, proto_out, None, loop)

    return reader, writer
