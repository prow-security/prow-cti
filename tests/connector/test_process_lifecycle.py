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

"""End-to-end subprocess lifecycle for Pass C1."""

from __future__ import annotations

from typing import Any

import pytest

from prow.connector.process import (
    ConnectorProcess,
    ConnectorProcessState,
    ProcessExitReason,
)
from prow.connector.protocol.messages import EmitAckPayload, LogPayload
from prow.connector.runtime_transport import ConnectorRuntimeTransport


@pytest.mark.slow
@pytest.mark.asyncio
async def test_subprocess_spawn_hello_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, Any]]] = []
    store: dict[str, Any] = {}
    log_envelopes: list[Any] = []

    async def emit_handler(inst: str, bundle: dict[str, Any]) -> EmitAckPayload:
        emitted.append((inst, bundle))
        return EmitAckPayload(accepted=1, duplicates=0, validation_failures=[])

    async def get_handler(inst: str, key: str) -> Any | None:
        return store.get(key)

    async def set_handler(inst: str, key: str, value: Any) -> None:
        store[key] = value

    real_log = ConnectorRuntimeTransport._handle_log

    async def capture_log(self: ConnectorRuntimeTransport, env: Any) -> None:
        assert self._connector_instance_id == "lifecycle-e2e"
        log_envelopes.append(env)
        return await real_log(self, env)

    monkeypatch.setattr(ConnectorRuntimeTransport, "_handle_log", capture_log)

    proc = ConnectorProcess(
        "lifecycle-e2e",
        "lifecycle_test",
        {"token": "secret"},
        "0.0.0",
        emit_handler,
        get_handler,
        set_handler,
    )
    await proc.start()
    assert proc.state == ConnectorProcessState.RUNNING
    await proc.request_shutdown(30)
    reason = await proc.wait()

    assert reason == ProcessExitReason.GRACEFUL_SHUTDOWN
    assert len(emitted) == 1
    assert emitted[0][0] == "lifecycle-e2e"
    assert store.get("cursor") == "done"

    messages = [LogPayload.model_validate(e.payload).message for e in log_envelopes]
    assert "lifecycle-log" in messages
    fields_union: dict[str, Any] = {}
    for e in log_envelopes:
        p = LogPayload.model_validate(e.payload)
        fields_union.update(p.fields)
    assert fields_union.get("channel") == "test"
