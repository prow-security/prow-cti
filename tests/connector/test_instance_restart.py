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

"""Integration tests for :class:`prow.connector.instance.ConnectorInstance` restarts."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from prow.connector.instance import ConnectorInstance
from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.restart_policy import RestartPolicy
from prow.connector.supervisor_state import ConnectorState


@pytest.mark.slow
@pytest.mark.asyncio
async def test_crash_setup_hits_circuit_then_clear_restarts() -> None:
    sleeps: list[float] = []

    async def record_sleep(d: float) -> None:
        sleeps.append(d)

    policy = RestartPolicy(
        backoff_schedule_seconds=(0.05, 0.05, 0.05),
        backoff_ceiling_seconds=0.05,
        max_restarts_in_window=3,
        window_duration_seconds=300.0,
    )

    async def emit(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_s(_i: str, _k: str) -> Any | None:
        return None

    async def set_s(_i: str, _k: str, _v: Any) -> None:
        return None

    inst = ConnectorInstance(
        "crash-setup-it",
        "crash_setup_test",
        {"token": "x"},
        "0.0.0",
        emit,
        get_s,
        set_s,
        policy,
        sleep_fn=record_sleep,
    )
    await inst.start()

    deadline = asyncio.get_event_loop().time() + 45.0
    while inst.state != ConnectorState.CIRCUIT_BROKEN:
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"expected circuit_broken, still {inst.state!s}")
        await asyncio.sleep(0.05)

    assert len(sleeps) >= 2
    await inst.clear_circuit_break()
    assert inst.restart_attempts_in_window == 0
    await inst.request_shutdown(5)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_graceful_lifecycle_not_restarted() -> None:
    policy = RestartPolicy(backoff_schedule_seconds=(0.01,))

    async def emit(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_s(_i: str, _k: str) -> Any | None:
        return None

    async def set_s(_i: str, _k: str, _v: Any) -> None:
        return None

    inst = ConnectorInstance(
        "grace-it",
        "minimal_test",
        {"token": "x"},
        "0.0.0",
        emit,
        get_s,
        set_s,
        policy,
    )
    await inst.start()
    await asyncio.sleep(0.05)
    assert inst.state in (ConnectorState.READY, ConnectorState.RUNNING)
    await inst.request_shutdown(10)
    deadline = asyncio.get_event_loop().time() + 30.0
    while inst.state != ConnectorState.DEAD:
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"expected dead, got {inst.state!s}")
        await asyncio.sleep(0.05)
    assert inst.restart_attempts_in_window == 0


@pytest.mark.slow
@pytest.mark.asyncio
async def test_shutdown_cancels_pending_restart() -> None:
    policy = RestartPolicy(
        backoff_schedule_seconds=(30.0, 60.0),
        max_restarts_in_window=99,
        window_duration_seconds=300.0,
    )

    async def emit(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_s(_i: str, _k: str) -> Any | None:
        return None

    async def set_s(_i: str, _k: str, _v: Any) -> None:
        return None

    inst = ConnectorInstance(
        "cancel-it",
        "crash_setup_test",
        {"token": "x"},
        "0.0.0",
        emit,
        get_s,
        set_s,
        policy,
    )
    await inst.start()
    deadline = asyncio.get_event_loop().time() + 30.0
    while inst._pending_restart_task is None:
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("pending restart never scheduled")
        await asyncio.sleep(0.02)

    await inst.request_shutdown(1)
    await asyncio.sleep(0.05)
    assert inst.state == ConnectorState.DEAD
    assert inst._pending_restart_task is None or inst._pending_restart_task.done()
