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

"""In-process tests for :mod:`prow.connector.runner` with mocked stdio streams."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.protocol.negotiation import perform_hello_runtime
from prow.connector.runtime_transport import ConnectorRuntimeTransport


class _TestConnectorExitError(Exception):
    """Substitute for os._exit / SystemExit when exercising runner in-process."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


@pytest.mark.asyncio
async def test_runner_main_hello_emit_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from prow.connector import runner as runner_mod

    monkeypatch.setenv("PROW_CONNECTOR_INSTANCE_ID", "runner-inproc")
    monkeypatch.setenv("PROW_CONNECTOR_ENTRY_POINT", "minimal_test")

    store: dict[str, Any] = {}

    async def emit_handler(_inst: str, bundle: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=1, duplicates=0, validation_failures=[])

    async def get_handler(_inst: str, key: str) -> Any | None:
        return store.get(key)

    async def set_handler(_inst: str, key: str, value: Any) -> None:
        store[key] = value

    async def runtime_peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        protocol_version = await perform_hello_runtime(
            reader,
            writer,
            "0.0.0",
            {"token": "secret"},
        )
        rt = ConnectorRuntimeTransport(
            "runner-inproc",
            reader,
            writer,
            protocol_version,
            emit_handler,
            get_handler,
            set_handler,
        )
        await rt.start()
        await asyncio.sleep(0.15)
        await rt.request_shutdown(grace_period_seconds=30)
        await rt.wait_dispatch_finished()

    server = await asyncio.start_server(runtime_peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client_reader, client_writer = await asyncio.open_connection("127.0.0.1", port)

    async def fake_stdio() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return client_reader, client_writer

    monkeypatch.setattr(runner_mod, "open_connector_stdio_streams", fake_stdio)

    def fake_exit(code: int) -> None:
        raise _TestConnectorExitError(code)

    monkeypatch.setattr(runner_mod, "connector_subprocess_exit", fake_exit)

    with pytest.raises(_TestConnectorExitError) as ctx:
        await runner_mod._async_main()
    assert ctx.value.code == 0

    client_writer.close()
    await client_writer.wait_closed()
    server.close()
    await server.wait_closed()
