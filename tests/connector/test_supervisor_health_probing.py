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

"""Health-probe integration tests for :class:`prow.connector.supervisor.Supervisor`."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from prow.connector.protocol.messages import EmitAckPayload
from prow.connector.restart_policy import RestartPolicy
from prow.connector.supervisor import Supervisor
from prow.connector.supervisor_state import ConnectorState


@pytest.mark.slow
@pytest.mark.asyncio
async def test_unhealthy_health_triggers_remediate_after_two_probes() -> None:
    async def emit(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_s(_i: str, _k: str) -> Any | None:
        return None

    async def set_s(_i: str, _k: str, _v: Any) -> None:
        return None

    sup = Supervisor(
        "0.0.0",
        emit,
        get_s,
        set_s,
        default_restart_policy=RestartPolicy(
            backoff_schedule_seconds=(0.05, 0.05),
            backoff_ceiling_seconds=0.05,
            max_restarts_in_window=99,
        ),
        health_probe_interval_seconds=0.15,
    )
    sup.add_instance(
        "uh",
        "minimal_test",
        {"token": "x"},
        subprocess_extra_environ={"PROW_CONNECTOR_TEST_HEALTH_MODE": "unhealthy"},
    )
    async with sup:
        deadline = asyncio.get_event_loop().time() + 45.0
        while sup.get_instance("uh").state not in (ConnectorState.CRASHED, ConnectorState.STARTING):
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError(
                    f"expected crash/start cycle, got {sup.get_instance('uh').state!s}",
                )
            await asyncio.sleep(0.05)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_slow_then_ok_does_not_restart() -> None:
    async def emit(_i: str, _b: dict[str, Any]) -> EmitAckPayload:
        return EmitAckPayload(accepted=0, duplicates=0, validation_failures=[])

    async def get_s(_i: str, _k: str) -> Any | None:
        return None

    async def set_s(_i: str, _k: str, _v: Any) -> None:
        return None

    sup = Supervisor(
        "0.0.0",
        emit,
        get_s,
        set_s,
        health_probe_interval_seconds=0.2,
    )
    sup.add_instance(
        "slow",
        "slow_health_test",
        {"token": "x"},
        subprocess_extra_environ={"PROW_CONNECTOR_TEST_HEALTH_MODE": "slow_then_ok"},
    )
    async with sup:
        await asyncio.sleep(2.5)
        assert sup.get_instance("slow").state in (
            ConnectorState.READY,
            ConnectorState.RUNNING,
        )
