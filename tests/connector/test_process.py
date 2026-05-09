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

"""Real-process tests for :class:`prow.connector.process.ConnectorProcess`."""

from __future__ import annotations

from typing import Any

import pytest

from prow.connector.process import (
    ConnectorProcess,
    ConnectorProcessState,
    ProcessExitReason,
)
from prow.connector.protocol.messages import EmitAckPayload


@pytest.mark.slow
@pytest.mark.asyncio
async def test_state_progression_and_graceful_exit() -> None:
    store: dict[str, Any] = {}

    async def emit_handler(_inst: str, _bundle: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=1, duplicates=0, validation_failures=[])

    async def get_handler(_inst: str, key: str) -> Any | None:
        return store.get(key)

    async def set_handler(_inst: str, key: str, value: Any) -> None:
        store[key] = value

    proc = ConnectorProcess(
        "state-test",
        "lifecycle_test",
        {"token": "secret"},
        "0.0.0",
        emit_handler,
        get_handler,
        set_handler,
    )
    assert proc.state == ConnectorProcessState.NOT_STARTED
    await proc.start()
    assert proc.state == ConnectorProcessState.RUNNING
    await proc.request_shutdown(30)
    assert proc.state == ConnectorProcessState.DRAINING
    reason = await proc.wait()
    assert proc.state == ConnectorProcessState.EXITED
    assert reason == ProcessExitReason.GRACEFUL_SHUTDOWN


@pytest.mark.slow
@pytest.mark.asyncio
async def test_forced_shutdown_after_grace_timeout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def emit_handler(_inst: str, _bundle: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_handler(_inst: str, _key: str) -> Any | None:
        return None

    async def set_handler(_inst: str, _key: str, _value: Any) -> None:
        return None

    proc = ConnectorProcess(
        "hang-test",
        "hang_test",
        {"token": "secret"},
        "0.0.0",
        emit_handler,
        get_handler,
        set_handler,
    )
    await proc.start()
    await proc.request_shutdown(grace_period_seconds=1)
    reason = await proc.wait()
    assert reason == ProcessExitReason.TIMEOUT_KILLED
    out_err = capsys.readouterr()
    combined = out_err.out + out_err.err
    assert "shutdown_timeout" in combined or "hang-test" in combined


@pytest.mark.slow
@pytest.mark.asyncio
async def test_crash_exit_reason_and_stderr_capture(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def emit_handler(_inst: str, _bundle: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=1, duplicates=0, validation_failures=[])

    async def get_handler(_inst: str, _key: str) -> Any | None:
        return None

    async def set_handler(_inst: str, _key: str, _value: Any) -> None:
        return None

    proc = ConnectorProcess(
        "crash-test",
        "crash_test",
        {"token": "secret"},
        "0.0.0",
        emit_handler,
        get_handler,
        set_handler,
    )
    await proc.start()
    reason = await proc.wait()
    assert reason == ProcessExitReason.CRASHED

    out_err = capsys.readouterr()
    combined = out_err.out + out_err.err
    assert "crash-test" in combined
    assert "crash_connector_on_purpose" in combined
