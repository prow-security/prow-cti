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

"""Tests for connector protocol hello negotiation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from prow.connector.protocol.negotiation import (
    NegotiationTimeoutError,
    UnsupportedVersionError,
    perform_hello_connector,
    perform_hello_runtime,
)

StreamHandler = Callable[
    [asyncio.StreamReader, asyncio.StreamWriter],
    Awaitable[Any],
]


async def _run_with_connector(
    connector: StreamHandler,
    runtime: StreamHandler,
) -> tuple[Any | BaseException, Any | BaseException]:
    connector_result: asyncio.Future[Any] = asyncio.get_running_loop().create_future()

    async def handle_client(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            connector_result.set_result(await connector(reader, writer))
        except Exception as exc:
            connector_result.set_exception(exc)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    assert server.sockets is not None
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)

    try:
        try:
            runtime_result: Any | BaseException = await runtime(reader, writer)
        except Exception as exc:
            runtime_result = exc
        try:
            connector_outcome: Any | BaseException = await connector_result
        except Exception as exc:
            connector_outcome = exc
        return runtime_result, connector_outcome
    finally:
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_successful_negotiation_agrees_on_version_one() -> None:
    config = {"api_key": "secret"}

    async def connector(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> tuple[int, dict[str, Any]]:
        return await perform_hello_connector(
            reader,
            writer,
            connector_version="1.0.0",
            supported_versions=[1],
        )

    async def runtime(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> int:
        return await perform_hello_runtime(
            reader,
            writer,
            runtime_version="0.0.0",
            config=config,
            supported_versions=[1],
        )

    runtime_result, connector_result = await _run_with_connector(connector, runtime)

    assert runtime_result == 1
    assert connector_result == (1, config)


@pytest.mark.asyncio
async def test_mismatched_versions_raise_on_both_sides() -> None:
    async def connector(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> tuple[int, dict[str, Any]]:
        return await perform_hello_connector(
            reader,
            writer,
            connector_version="1.0.0",
            supported_versions=[1],
        )

    async def runtime(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> int:
        return await perform_hello_runtime(
            reader,
            writer,
            runtime_version="0.0.0",
            config={},
            supported_versions=[2],
        )

    runtime_result, connector_result = await _run_with_connector(connector, runtime)

    assert isinstance(runtime_result, UnsupportedVersionError)
    assert isinstance(connector_result, UnsupportedVersionError)


@pytest.mark.asyncio
async def test_runtime_negotiation_times_out_when_connector_never_responds() -> None:
    async def silent_connector(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        await reader.read(1)
        writer.close()
        await writer.wait_closed()

    async def runtime(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> int:
        return await perform_hello_runtime(
            reader,
            writer,
            runtime_version="0.0.0",
            config={},
            supported_versions=[1],
            timeout_seconds=0.01,
        )

    runtime_result, connector_result = await _run_with_connector(silent_connector, runtime)

    assert isinstance(runtime_result, NegotiationTimeoutError)
    assert connector_result is None
